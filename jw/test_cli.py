import contextlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from jw import cli, guide, toon  # noqa: E402
from tests import fixture  # noqa: E402

FAILED = []
LONG_NOTE = "recruiter said the team is hiring across " + "platform and infra " * 15


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILED.append(label)


class Env:
    def __init__(self, tmp):
        self.tmp = tmp
        self.root = os.path.join(tmp, "repo")
        self.db = os.path.join(tmp, "cli.db")
        self.now = int(time.time())
        self.ids = fixture.build_bulk_tree(self.root, self.now)
        fixture.make_store(self.root, self.db)

    def env(self, **extra):
        base = {k: v for k, v in os.environ.items()
                if k not in ("JW_FORMAT", "PYTHONIOENCODING", "JW_DEBUG")}
        base["JOBWATCHER_DB"] = self.db
        base["JW_HOME"] = self.root
        base.update(extra)
        return base

    def raw(self, *args, stdin=None, env=None, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "jw", *args], cwd=cwd or REPO, capture_output=True,
            input=stdin, env=env or self.env())

    def cli(self, *args, env=None, cwd=None):
        proc = self.raw(*args, env=env, cwd=cwd)
        return (proc.returncode, proc.stdout.decode("utf-8"),
                proc.stderr.decode("utf-8"))

    def json(self, *args):
        code, out, _ = self.cli("--format", "json", *args)
        return code, json.loads(out)


def split_cells(line):
    cells, current, quoted, index = [], [], False, 0
    while index < len(line):
        ch = line[index]
        if quoted and ch == "\\":
            current.append(line[index + 1])
            index += 2
            continue
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            cells.append("".join(current))
            current = []
        else:
            current.append(ch)
        index += 1
    cells.append("".join(current))
    return cells


def table(text, key):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.match(rf"^{re.escape(key)}\[(\d+)\]\{{(.*)\}}:$", line)
        if match:
            columns = match.group(2).split(",")
            rows = lines[i + 1:i + 1 + int(match.group(1))]
            return [dict(zip(columns, split_cells(r.strip()))) for r in rows]
    return None


def scalar(text, key):
    match = re.search(rf"^ *{re.escape(key)}: (.*)$", text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1)
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] == '"' else value


def help_lines(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^help\[\d+\]:$", line):
            out = []
            for row in lines[i + 1:]:
                if not row.startswith("  "):
                    break
                out.append(row.strip())
            return out
    return []


def check_toon_vectors():
    path = os.path.join(REPO, "tests", "toon_vectors.json")
    with open(path, encoding="utf-8") as fh:
        vectors = json.load(fh)
    bad = [v["toon"] for v in vectors if toon.encode(v["value"]) != v["toon"]]
    check(f"the TOON encoder matches the reference encoder on {len(vectors)} vectors",
          not bad)


def check_utf8(env):
    win = env.env(PYTHONIOENCODING="cp1252")
    proc = env.raw("--format", "json", "postings", "query", "--full", "--title", "Data Sci",
                   env=win)
    try:
        titles = {p["title"] for p in json.loads(proc.stdout.decode("utf-8"))["postings"]}
    except (UnicodeDecodeError, ValueError):
        titles = set()
    check("non-ASCII titles reach a cp1252-configured pipe as intact UTF-8",
          "Data Scientist 日本語 🚀" in titles)
    proc = env.raw("--format", "json", "postings", "query", "--full", "--title", "Platform",
                   env=win)
    titles = {p["title"] for p in json.loads(proc.stdout.decode("utf-8"))["postings"]}
    check("an en dash survives the same pipe", "Machine Learning Engineer – Platform" in titles)

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "jw_postings_query",
                    "arguments": {"title": "– Platform", "limit": 3}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "jw_postings_query",
                    "arguments": {"title": "Platform", "limit": 3, "format": "json"}}},
    ]
    stdin = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests).encode("utf-8")
    proc = env.raw("mcp", stdin=stdin, env=win)
    replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line]
    text = replies[1]["result"]["content"][0]["text"]
    check("MCP reads a non-ASCII argument and returns the matching title",
          "Machine Learning Engineer – Platform" in text)
    check("MCP returns TOON by default", text.startswith("count: "))
    as_json = replies[2]["result"]["content"][0]["text"]
    check("MCP honours format=json", json.loads(as_json)["count"] == 3)


def check_format_selection(env):
    code, out, err = env.cli("postings", "query", "--limit", "2")
    check("output defaults to TOON", code == 0 and out.startswith("count: 2"))
    check("nothing goes to stderr on success", err == "")
    code, out, _ = env.cli("postings", "query", "--limit", "2", "--format", "json")
    body = json.loads(out)
    check("--format json after the subcommand gives compact JSON",
          body["count"] == 2 and out.count("\n") == 1 and '": ' not in out)
    code, out, _ = env.cli("--format", "json", "postings", "query", "--limit", "2")
    check("--format json before the subcommand works too", json.loads(out)["count"] == 2)
    code, out, _ = env.cli("postings", "query", "--limit", "2",
                           env=env.env(JW_FORMAT="json"))
    check("JW_FORMAT sets the default format", json.loads(out)["count"] == 2)
    code, out, err = env.cli("--format", "yaml", "postings", "query")
    check("an unknown format is refused with exit 2", code == 2 and "VALIDATION_ERROR" in out)


def check_postings_view(env):
    code, out, _ = env.cli("postings", "query", "--open", "--limit", "100")
    rows = table(out, "postings")
    check("a list is a TOON table with four default columns",
          rows and list(rows[0]) == ["id", "company", "title", "posted"])
    check("count and total aggregates lead the output",
          scalar(out, "count") == "100" and int(scalar(out, "total")) > 100)
    check("open-only output omits the redundant state column", "state" not in rows[0])

    code, out, _ = env.cli("postings", "query", "--limit", "5")
    check("without --open the state column is added",
          list(table(out, "postings")[0])[-1] == "state")

    code, out, _ = env.cli("postings", "query")
    rows = table(out, "postings")
    total = int(scalar(out, "total"))
    check("the default page is 25 rows", len(rows) == 25)
    check("truncation says exactly how many more match",
          any(f"{total - 25} more match" in h for h in help_lines(out)))

    code, out, _ = env.cli("postings", "query", "--limit", "0")
    check("--limit 0 returns every match", len(table(out, "postings")) == total)

    code, body = env.json("postings", "query", "--full", "--limit", "2")
    first = body["postings"][0]
    check("--full returns every stored field with raw timestamps and full ids",
          len(first["id"]) > 8 and isinstance(first["posted_at"], int)
          and "apply_url" in first and "degrees" in first)

    code, out, _ = env.cli("postings", "query", "--title", "zzz-nothing", "--open")
    check("an empty result says so explicitly",
          scalar(out, "count") == "0" and "postings: []" in out and help_lines(out))

    code, out, _ = env.cli("postings", "show", "z1")
    check("a recent posting is aged in the unit --since accepts", scalar(out, "posted") == "2d")
    code, out, _ = env.cli("postings", "query", "--company", "vertex", "--limit", "0")
    check("an old posting falls back to an ISO date",
          any(re.match(r"^\d{4}-\d\d-\d\d$", r["posted"]) for r in table(out, "postings")))


def check_short_ids(env):
    code, out, _ = env.cli("postings", "query", "--company", "vertex", "--limit", "0")
    rows = table(out, "postings")
    shown = [r["id"] for r in rows]
    check("every id in a list is unique", len(set(shown)) == len(shown))
    check("ids are shortened to a prefix", all(8 <= len(i) < 36 for i in shown))
    check("a prefix that reads as a number is lengthened so it stays a string",
          not any(i.startswith('"') for i in shown)
          and any(i.startswith("12345678-") for i in shown))
    shared = [r["id"] for r in rows if r["id"].startswith("abcd1234")]
    check("ids that share a prefix are lengthened until distinct",
          len(shared) == 2 and shared[0] != shared[1] and all(len(i) > 8 for i in shared))

    code, out, _ = env.cli("postings", "show", shared[0])
    check("a shown id is accepted by postings show", code == 0 and scalar(out, "id") == shared[0])

    code, out, err = env.cli("postings", "show", "abcd1234")
    check("an ambiguous prefix is refused with exit 2 and its candidates",
          code == 2 and scalar(out, "code") == "AMBIGUOUS"
          and len(table(out, "candidates") or []) == 2)

    code, out, err = env.cli("postings", "show", "zzzzzzzz")
    check("an unknown id is a structured NOT_FOUND on stdout only",
          code == 2 and scalar(out, "code") == "NOT_FOUND" and err == ""
          and any("jw postings query" in h for h in help_lines(out)))

    code, out, _ = env.cli("status", "set", shared[0], "--status", "applied",
                           "--note", LONG_NOTE)
    check("a short id records a status and echoes what it resolved to",
          code == 0 and scalar(out, "changed") == "true"
          and scalar(out, "status") == "applied" and scalar(out, "company") == "Vertex Systems")
    code, out, _ = env.cli("status", "set", shared[0], "--status", "applied")
    check("repeating the same status is a reported no-op", scalar(out, "changed") == "false")

    code, out, _ = env.cli("postings", "show", shared[0])
    clipped = scalar(out, "notes")
    check("long text is clipped with the remaining length",
          clipped and re.search(r"\[\+\d+ chars\]$", clipped) and len(clipped) < len(LONG_NOTE))
    code, body = env.json("postings", "show", shared[0], "--full")
    check("--full returns the whole note", body["application"]["notes"] == LONG_NOTE)

    code, out, _ = env.cli("status", "set", shared[0], "--status", "applied", "--dry-run")
    check("a dry run previews the resolved target",
          scalar(out, "dry_run") == "true" and "Vertex Systems" in out)


def check_aggregates(env):
    code, out, _ = env.cli("applications", "list")
    check("applications carry a by_status aggregate",
          re.search(r"^by_status:\n  applied: 2$", out, re.MULTILINE) is not None)
    code, out, _ = env.cli("company", "list")
    tiers = re.search(r"^by_tier:\n((?:  .+\n)+)", out, re.MULTILINE)
    counted = sum(int(line.split(": ")[1]) for line in tiers.group(1).splitlines())
    check("companies carry a by_tier aggregate that adds up",
          counted == int(scalar(out, "total")))
    code, out, _ = env.cli("company", "show", "vertex")
    check("a company shows its open postings and how many more there are",
          len(table(out, "open_postings")) == 10
          and int(scalar(out, "open_postings_more")) > 0)
    check("and its recent events", len(table(out, "recent_events")) == 5)


def check_errors_and_content_first(env):
    code, out, err = env.cli("postings", "query", "--nope")
    check("an unknown flag is refused loudly and names the command",
          code == 2 and "--nope" in out and "jw postings query" in out and err == "")

    code, out, err = env.cli()
    check("bare jw shows live data, not help",
          code == 0 and int(re.search(r"total: (\d+)", out).group(1)) > 100
          and table(out, "newest") and "Usage" not in out)
    check("and lists next steps", len(help_lines(out)) >= 2)

    missing = os.path.join(env.tmp, "nothing.db")
    code, out, err = env.cli("--db", missing)
    check("bare jw without a store says so and how to fix it, exit 0",
          code == 0 and scalar(out, "status") == "missing"
          and any("jw db import" in h for h in help_lines(out)) and not os.path.exists(missing))
    code, out, _ = env.cli("--db", missing, "state", "show")
    check("a command against a missing store is a NO_STORE error with exit 2",
          code == 2 and scalar(out, "code") == "NO_STORE")


def check_help_hints(env):
    batteries = [
        ("postings", "query", "--limit", "3"), ("postings", "query", "--limit", "3",
                                                 "--open"),
        ("postings", "query", "--title", "zzz"), ("postings", "show", "z1"),
        ("company", "list"), ("company", "show", "vertex"), ("applications", "list"),
        ("status", "set", "z1", "--status", "applied", "--dry-run"),
        ("postings", "show", "zzzzzzzz"), ("state", "show"), (),
    ]
    parser = cli.build_parser()
    invalid = []
    total = 0
    for args in batteries:
        code, out, _ = env.cli(*args)
        for line in help_lines(out):
            for command in re.findall(r"`(jw [^`]+)`", line):
                total += 1
                argv = shlex.split(re.sub(r"<([^>]+)>", r"\1", command))[1:]
                try:
                    parser.parse_args(argv)
                except Exception:
                    invalid.append(command)
    check(f"all {total} suggested commands are valid invocations", total > 10 and not invalid)


def check_size_budget(env):
    code, out, _ = env.cli("postings", "query", "--open", "--limit", "100")
    code, full, _ = env.cli("--format", "json", "postings", "query", "--open", "--limit",
                            "100", "--full")
    check("100 postings cost under 10 KB by default", len(out.encode("utf-8")) < 10_000)
    check("and under a quarter of the full JSON record",
          len(out.encode("utf-8")) * 4 < len(full.encode("utf-8")))
    code, out, _ = env.cli("company", "list")
    check("the whole company directory costs under 6 KB", len(out.encode("utf-8")) < 6_000)


EMIT_SCRIPT = """import os
import sys


def read(name, default=""):
    path = os.path.join("collectors", name)
    return open(path, encoding="utf-8").read() if os.path.exists(path) else default


sys.stderr.write(read("emit.err"))
for line in read("emit.jsonl").splitlines():
    if line.strip():
        print(line)
sys.exit(int(read("emit.exit", "0") or 0))
"""


def _write_collector(env, observations, exit_code=0, stderr=""):
    folder = os.path.join(env.root, "collectors")
    os.makedirs(folder, exist_ok=True)
    for name, text in (("emit.py", EMIT_SCRIPT), ("emit.exit", str(exit_code)),
                       ("emit.err", stderr),
                       ("emit.jsonl", "".join(json.dumps(o) + "\n" for o in observations))):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write(text)


def _observation(env, external_id, title="Kernel Engineer Intern"):
    return {"source": "emit", "external_id": external_id, "company_raw": "Zenith",
            "title_raw": title, "level": "intern", "terms": ["Summer 2027"],
            "locations": ["NYC"], "url": f"https://example.com/{external_id}",
            "posted_at": env.now, "extra": {"category": "Software"}}


def check_sync(env):
    _write_collector(env, [_observation(env, "emit-1")])
    code, out, _ = env.cli("source", "add", "emit", "--command", "python collectors/emit.py")
    check("a collector registers by name and command", code == 0 and scalar(out, "name") == "emit")

    code, out, _ = env.cli("sync", "run")
    check("a sync reports what is new as a short table",
          code == 0 and scalar(out, "new_listings") == "1"
          and table(out, "listings")[0]["title"] == "Kernel Engineer Intern")
    check("and lists each source with its status",
          table(out, "sources")[0]["name"] == "emit" and table(out, "sources")[0]["status"] == "ok")
    check("and keeps the digest text out of the default output", "digest_text" not in out)
    check("and offers the digest as a next step", any("--full" in h for h in help_lines(out)))

    _write_collector(env, [_observation(env, "emit-1"), _observation(env, "emit-2")])
    code, out, _ = env.cli("--format", "json", "sync", "run", "--full")
    check("--full includes the digest text",
          code == 0 and "Kernel Engineer Intern" in json.loads(out)["digest_text"])

    _write_collector(env, [_observation(env, "emit-1")], exit_code=3, stderr="HTTP error 503")
    code, out, _ = env.cli("sync", "run")
    check("an unavailable upstream is exit 3 with the failing source named",
          code == 3 and scalar(out, "code") == "UPSTREAM_UNAVAILABLE"
          and table(out, "failures")[0]["name"] == "emit")

    _write_collector(env, [_observation(env, "emit-1")], exit_code=1, stderr="boom")
    code, out, _ = env.cli("sync", "run")
    check("any other collector failure is exit 1",
          code == 1 and scalar(out, "code") == "SYNC_FAILED")
    check("and points at the dry run that shows why",
          any("jw source run emit --dry-run" in h for h in help_lines(out)))


def _extract_jw_commands(text):
    commands = list(re.findall(r"`(jw [^`\n]+)`", text))
    in_block = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if in_block and line.strip().startswith("jw "):
            commands.append(line.strip())
    return commands


def _check_commands_parse(label, parser, commands):
    invalid = []
    for command in commands:
        argv = shlex.split(re.sub(r"<([^>]+)>", r"\1", command))[1:]
        try:
            parser.parse_args(argv)
        except SystemExit:
            invalid.append(command)
        except Exception:
            invalid.append(command)
    check(f"{label}: all {len(commands)} `jw ...` commands parse against the real CLI",
          len(commands) > 10 and not invalid)
    if invalid:
        print("  invalid:", invalid)


def check_guide(env):
    code, out, _ = env.cli("guide")
    check("guide index lists every topic",
          code == 0 and len(table(out, "topics")) == len(guide.TOPIC_NAMES))
    code, out, _ = env.cli("guide", "core")
    check("a topic reads back its own content",
          code == 0 and scalar(out, "topic") == "core" and "postings query" in out)
    code, out, _ = env.cli("guide", "nope")
    check("an unknown topic is NOT_FOUND and lists the real ones",
          code == 2 and scalar(out, "code") == "NOT_FOUND"
          and all(t in help_lines(out)[0] for t in guide.TOPIC_NAMES))

    parser = cli.build_parser()
    commands = []
    for name in guide.TOPIC_NAMES:
        commands.extend(_extract_jw_commands(guide.read(name)))
    _check_commands_parse("guide", parser, commands)


def check_skills_and_hooks(env):
    parser = cli.build_parser()
    proj = tempfile.mkdtemp(prefix="jw-skills-e2e-")
    try:
        code, out, _ = env.cli("skills", "install", "--root", proj)
        rows = table(out, "skills")
        check("skills install writes every topic",
              code == 0 and rows and all(r["status"] == "written" for r in rows))

        skill_commands = []
        for name in guide.TOPIC_NAMES:
            path = os.path.join(proj, ".agents", "skills", f"jw-{name}", "SKILL.md")
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            check(f"jw-{name} has spec-shaped frontmatter",
                  text.startswith(f"---\nname: jw-{name}\ndescription: "))
            skill_commands.extend(_extract_jw_commands(text))
        _check_commands_parse("skills", parser, skill_commands)

        code, out, _ = env.cli("skills", "install", "--root", proj)
        check("reinstalling is a no-op",
              code == 0 and all(r["status"] == "unchanged" for r in table(out, "skills")))

        core_path = os.path.join(proj, ".agents", "skills", "jw-core", "SKILL.md")
        with open(core_path, "a", encoding="utf-8") as fh:
            fh.write("\nhand edit\n")
        code, out, _ = env.cli("skills", "install", "--root", proj)
        rows = {r["name"]: r["status"] for r in table(out, "skills")}
        check("a jw-managed file that was edited is rewritten on the next install",
              code == 0 and rows["jw-core"] == "written"
              and rows["jw-setup"] == "unchanged")

        notify_path = os.path.join(proj, ".agents", "skills", "jw-notify", "SKILL.md")
        with open(notify_path, "w", encoding="utf-8") as fh:
            fh.write("hand-written, no jw marker\n")
        code, out, _ = env.cli("skills", "install", "--root", proj)
        rows = {r["name"]: r["status"] for r in table(out, "skills")}
        check("a file jw never wrote is left alone, not overwritten",
              code == 0 and rows["jw-notify"] == "left alone (not jw-managed)"
              and open(notify_path, encoding="utf-8").read() == "hand-written, no jw marker\n")

        code, out, _ = env.cli("skills", "remove", "--root", proj)
        removed = re.search(r"^removed\[(\d+)\]: (.*)$", out, re.MULTILINE)
        check("remove deletes every jw-managed skill but leaves the conflict",
              code == 0 and removed and removed.group(1) == "5"
              and "jw-notify" not in removed.group(2)
              and not os.path.exists(core_path) and os.path.exists(notify_path))

        code, out, _ = env.cli("hooks", "install", "--root", proj)
        check("hooks install registers a SessionStart hook",
              code == 0 and scalar(out, "action") == "installed")
        settings_path = os.path.join(proj, ".claude", "settings.json")
        with open(settings_path, encoding="utf-8") as fh:
            data = json.load(fh)
        entries = data["hooks"]["SessionStart"]
        check("the hook is a well-formed command entry",
              len(entries) == 1 and entries[0]["hooks"][0]["type"] == "command"
              and entries[0]["hooks"][0]["command"].endswith("hooks summary"))

        code, out, _ = env.cli("hooks", "install", "--root", proj)
        with open(settings_path, encoding="utf-8") as fh:
            data = json.load(fh)
        check("reinstalling the hook does not duplicate it",
              code == 0 and scalar(out, "action") == "unchanged"
              and len(data["hooks"]["SessionStart"]) == 1)

        code, out, _ = env.cli("hooks", "summary", cwd=proj)
        check("the hook's own command prints a terse status line",
              code in (0, 1) and ("postings" in out or "status" in out))

        code, out, _ = env.cli("hooks", "remove", "--root", proj)
        check("hooks remove clears the entry", code == 0 and scalar(out, "action") == "removed")
        code, out, _ = env.cli("hooks", "remove", "--root", proj)
        check("removing again is reported, not an error",
              code == 0 and scalar(out, "action") == "not installed")
    finally:
        shutil.rmtree(proj, ignore_errors=True)


def main():
    tmp = tempfile.mkdtemp(prefix="jw-cli-e2e-")
    try:
        env = Env(tmp)
        os.environ["JW_HOME"] = env.root
        check_toon_vectors()
        check_utf8(env)
        check_format_selection(env)
        check_postings_view(env)
        check_short_ids(env)
        check_aggregates(env)
        check_errors_and_content_first(env)
        check_help_hints(env)
        check_size_budget(env)
        check_sync(env)
        check_guide(env)
        check_skills_and_hooks(env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILED:
        print(f"{len(FAILED)} CHECK(S) FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
