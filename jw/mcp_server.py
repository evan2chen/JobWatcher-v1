import argparse
import json
import subprocess
import sys

from .cli import NON_AGENT_COMMANDS, build_parser

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "jobwatcher", "version": "0.2.0"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


def _subcommands(parser):
    group_action = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None
    )
    if group_action is None:
        return
    for group, gparser in group_action.choices.items():
        if group in NON_AGENT_COMMANDS:
            continue
        sub_action = next(
            (a for a in gparser._actions if isinstance(a, argparse._SubParsersAction)),
            None,
        )
        if sub_action is None:
            yield group, None, gparser
            continue
        for command, cparser in sub_action.choices.items():
            yield group, command, cparser


def _schema_for(action):
    if isinstance(action, argparse._StoreTrueAction):
        return {"type": "boolean"}
    if isinstance(action, argparse._AppendAction):
        return {"type": "array", "items": {"type": "string"}}
    prop = {"type": "integer" if action.type is int else "string"}
    if action.choices:
        prop["enum"] = list(action.choices)
    return prop


def tool_definitions(parser=None):
    parser = parser or build_parser()
    tools = []
    for group, command, cparser in _subcommands(parser):
        name = f"jw_{group}_{command}" if command else f"jw_{group}"
        properties, required = {}, []
        for action in cparser._actions:
            if action.dest in ("help", "==SUPPRESS=="):
                continue
            prop = _schema_for(action)
            if action.help:
                prop["description"] = action.help
            properties[action.dest] = prop
            if not action.option_strings:
                if action.nargs not in ("?", "*"):
                    required.append(action.dest)
            elif action.required:
                required.append(action.dest)
        tools.append({
            "name": name,
            "description": (cparser.description or cparser.prog or name).strip(),
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            "_argv": [group] + ([command] if command else []),
            "_actions": cparser._actions,
        })
    return tools


def _public(tool):
    return {k: v for k, v in tool.items() if not k.startswith("_")}


def build_argv(tool, arguments):
    argv = list(tool["_argv"])
    positionals, options = [], []
    for action in tool["_actions"]:
        if action.dest in ("help", "==SUPPRESS=="):
            continue
        if action.dest not in arguments or arguments[action.dest] is None:
            continue
        value = arguments[action.dest]
        if not action.option_strings:
            positionals.append(str(value))
            continue
        flag = next((o for o in action.option_strings if o.startswith("--")),
                    action.option_strings[0])
        if isinstance(action, argparse._StoreTrueAction):
            if value:
                options.append(flag)
        elif isinstance(action, argparse._AppendAction):
            for item in value:
                options.extend([flag, str(item)])
        else:
            options.extend([flag, str(value)])
    return argv + positionals + options


class Server:
    def __init__(self, stdin=None, stdout=None, runner=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.tools = {t["name"]: t for t in tool_definitions()}
        self.runner = runner or self._subprocess

    def _send(self, payload):
        self.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.stdout.flush()

    def _result(self, msg_id, result):
        self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def _error(self, msg_id, code, message):
        self._send({"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": code, "message": message}})

    @staticmethod
    def _subprocess(argv):
        proc = subprocess.run(
            [sys.executable, "-m", "jw", *argv],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def handle(self, message):
        method = message.get("method")
        msg_id = message.get("id")

        if msg_id is None:
            return

        if method == "initialize":
            client_version = (message.get("params") or {}).get("protocolVersion")
            self._result(msg_id, {
                "protocolVersion": client_version or PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            })
        elif method == "ping":
            self._result(msg_id, {})
        elif method == "tools/list":
            self._result(msg_id, {"tools": [_public(t) for t in self.tools.values()]})
        elif method in ("resources/list", "prompts/list"):
            self._result(msg_id, {method.split("/")[0]: []})
        elif method == "tools/call":
            self._call(msg_id, message.get("params") or {})
        else:
            self._error(msg_id, METHOD_NOT_FOUND, f"unknown method {method!r}")

    def _call(self, msg_id, params):
        name = params.get("name")
        tool = self.tools.get(name)
        if tool is None:
            self._error(msg_id, INVALID_REQUEST, f"unknown tool {name!r}")
            return
        try:
            argv = build_argv(tool, params.get("arguments") or {})
            code, stdout, stderr = self.runner(argv)
        except Exception as exc:
            self._result(msg_id, {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            })
            return
        text = stdout.strip() or (stderr.strip() or "(no output)")
        self._result(msg_id, {
            "content": [{"type": "text", "text": text}],
            "isError": code != 0,
        })

    def serve_forever(self):
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self._error(None, PARSE_ERROR, "invalid JSON")
                continue
            try:
                self.handle(message)
            except Exception as exc:
                self._error(message.get("id"), INTERNAL_ERROR,
                            f"{type(exc).__name__}: {exc}")
        return 0


def main():
    return Server().serve_forever()
