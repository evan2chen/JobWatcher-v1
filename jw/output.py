import json
import os
import sys
import time
from datetime import datetime, timezone

from . import toon

FORMAT_ENV = "JW_FORMAT"
FORMATS = ("toon", "json")
DEFAULT_FORMAT = "toon"
TEXT_LIMIT = 160
BLOCK_LIMIT = 1000


class CliError(Exception):
    def __init__(self, code, message, exit_code=1, help=None, **extra):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.help = help or []
        self.extra = extra

    def payload(self):
        body = {"error": str(self), "code": self.code}
        body.update(self.extra)
        if self.help:
            body["help"] = self.help
        return body


def resolve_format(explicit=None):
    chosen = explicit or os.environ.get(FORMAT_ENV) or DEFAULT_FORMAT
    if chosen not in FORMATS:
        raise CliError("VALIDATION_ERROR",
                       f"format must be one of {', '.join(FORMATS)}, got {chosen!r}",
                       exit_code=2)
    return chosen


def render(payload, fmt=DEFAULT_FORMAT):
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    hints = payload.get("help") if isinstance(payload, dict) else None
    if not hints:
        return toon.encode(payload)
    body = toon.encode({k: v for k, v in payload.items() if k != "help"})
    block = [f"help[{len(hints)}]:"] + [f"{toon.INDENT}{line}" for line in hints]
    return "\n".join(([body] if body else []) + block)


def emit(payload, fmt=DEFAULT_FORMAT, stream=None):
    stream = stream or sys.stdout
    text = render(payload, fmt)
    stream.write(text + "\n" if text else "")
    stream.flush()


def age(ts, now=None):
    if ts is None:
        return None
    now = int(now if now is not None else time.time())
    delta = now - int(ts)
    if delta < 0:
        return "now"
    if delta < 3600:
        return "<1h"
    if delta < 48 * 3600:
        return f"{delta // 3600}h"
    if delta < 60 * 86400:
        return f"{delta // 86400}d"
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")


def clip(text, limit=TEXT_LIMIT, full=False):
    if text is None or full or len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}... [+{len(text) - limit} chars]"


def join(values, sep="; "):
    return sep.join(str(v) for v in values) if values else None


def display_path(path):
    if not path:
        return path
    absolute = os.path.abspath(path)
    try:
        relative = os.path.relpath(absolute)
    except ValueError:
        relative = absolute
    chosen = absolute if relative.startswith("..") else relative
    return chosen.replace(os.sep, "/")
