import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

FAILED = []
CLEARED_ENV = ("JW_FORMAT", "JW_HOME", "JOBWATCHER_ROOT", "JOBWATCHER_DB", "PYTHONIOENCODING",
               "JW_DEBUG", "JW_API_TOKEN")


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILED.append(label)


def finish():
    print()
    if FAILED:
        print(f"{len(FAILED)} CHECK(S) FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in CLEARED_ENV}
    env.update(extra)
    return env


def run_jw(*args, env=None, stdin=None, cwd=None, python_path=None):
    env = dict(env if env is not None else clean_env())
    if python_path:
        env["PYTHONPATH"] = python_path
    proc = subprocess.run(
        [sys.executable, "-m", "jw", *args], cwd=cwd or REPO, capture_output=True,
        input=stdin, env=env)
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


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
        match = re.match(rf"^ *{re.escape(key)}\[(\d+)\]\{{(.*)\}}:$", line)
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


def jsonl(records):
    return "".join(json.dumps(r) + "\n" for r in records).encode("utf-8")
