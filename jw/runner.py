import collections
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from . import paths

EXIT_UPSTREAM = 3
TAIL_LINES = 20

BASE_ENV = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "WINDIR",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
)
PYTHON_NAMES = ("python", "python3", "python.exe", "python3.exe")


@dataclass
class Result:
    status: str
    returncode: Optional[int] = None
    stdout: bytes = b""
    stderr_tail: List[str] = field(default_factory=list)
    duration: float = 0.0
    detail: Optional[str] = None


def resolve_argv(command):
    argv = list(command)
    if argv and os.path.basename(argv[0]).lower() in PYTHON_NAMES:
        argv[0] = sys.executable
    return argv


def build_env(name, home, passthrough=()):
    env = {k: os.environ[k] for k in BASE_ENV + tuple(passthrough) if k in os.environ}
    pythonpath = [paths.code_root()]
    if os.environ.get("PYTHONPATH"):
        pythonpath.append(os.environ["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env[paths.HOME_ENV] = home
    env["JW_SOURCE"] = name
    return env


def run(command, name, home, timeout_s, max_output_mb, passthrough=()):
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            resolve_argv(command), cwd=home, env=build_env(name, home, passthrough),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return Result("failed", detail=f"cannot start {command[0]!r}: {exc}")

    cap = int(max_output_mb) * 1024 * 1024
    chunks, size = [], [0]
    overflow = threading.Event()
    tail = collections.deque(maxlen=TAIL_LINES)

    def read_stdout():
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                return
            size[0] += len(chunk)
            if size[0] > cap:
                overflow.set()
                proc.kill()
                return
            chunks.append(chunk)

    def read_stderr():
        for line in iter(proc.stderr.readline, b""):
            tail.append(line.decode("utf-8", "replace").rstrip())

    readers = [threading.Thread(target=fn, daemon=True) for fn in (read_stdout, read_stderr)]
    for thread in readers:
        thread.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()
    for thread in readers:
        thread.join(timeout=5)

    duration = time.monotonic() - started
    result = Result("ok", proc.returncode, b"".join(chunks), list(tail), duration)
    if timed_out:
        result.status, result.detail = "timeout", f"no exit within {timeout_s}s"
    elif overflow.is_set():
        result.status, result.detail = "output_too_large", f"stdout passed {max_output_mb} MB"
    elif proc.returncode == EXIT_UPSTREAM:
        result.status, result.detail = "upstream_unavailable", "collector exited 3"
    elif proc.returncode != 0:
        result.status, result.detail = "failed", f"exit code {proc.returncode}"
    return result
