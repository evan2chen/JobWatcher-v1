import math
import re
from decimal import Decimal

INDENT = "  "
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_NUMERIC = re.compile(r"^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$", re.IGNORECASE)
_LEADING_ZERO = re.compile(r"^0\d+$")
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_SPECIAL = set(':"\\[]{}')


def _is_primitive(value):
    return value is None or isinstance(value, (str, bool, int, float))


def _number(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        return "null"
    if value == 0:
        return "0"
    magnitude = abs(value)
    if 1e-6 <= magnitude < 1e21:
        text = format(Decimal(repr(value)), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    digits, exponent = Decimal(repr(value)).as_tuple().digits, Decimal(repr(value)).adjusted()
    mantissa = "".join(map(str, digits)).rstrip("0") or "0"
    body = mantissa[0] + ("." + mantissa[1:] if len(mantissa) > 1 else "")
    sign = "-" if value < 0 else ""
    return f"{sign}{body}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"


def needs_quotes(text):
    return (
        text == ""
        or text != text.strip()
        or text in ("true", "false", "null")
        or bool(_NUMERIC.match(text))
        or bool(_LEADING_ZERO.match(text))
        or "," in text
        or text.startswith("-")
        or any(ch in _SPECIAL or ord(ch) < 0x20 for ch in text)
    )


def _quote(text):
    out = []
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _primitive(value):
    if value is None:
        return "null"
    if isinstance(value, str):
        return _quote(value) if needs_quotes(value) else value
    return _number(value)


def _key(name):
    name = str(name)
    return name if _KEY.match(name) else _quote(name)


def _uniform_columns(items):
    if not items or not all(isinstance(i, dict) and i for i in items):
        return None
    columns = list(items[0])
    keys = set(columns)
    for item in items:
        if set(item) != keys or not all(_is_primitive(v) for v in item.values()):
            return None
    return columns


def _array(label, items, depth):
    pad = INDENT * depth
    if not items:
        return [f"{pad}{label}: []"] if label else ["[]"]
    return _sized_array(label, items, depth)


def _sized_array(label, items, depth, tabular=True):
    pad = INDENT * depth
    n = len(items)
    if all(_is_primitive(i) for i in items):
        return [f"{pad}{label}[{n}]: " + ",".join(_primitive(i) for i in items)]
    columns = _uniform_columns(items) if tabular else None
    if columns is not None:
        rows = [
            INDENT * (depth + 1) + ",".join(_primitive(item[c]) for c in columns)
            for item in items
        ]
        return [f"{pad}{label}[{n}]{{{','.join(_key(c) for c in columns)}}}:"] + rows
    lines = [f"{pad}{label}[{n}]:"]
    for item in items:
        lines.extend(_list_item(item, depth + 1))
    return lines


def _list_item(item, depth):
    pad = INDENT * depth
    if _is_primitive(item):
        return [f"{pad}- {_primitive(item)}"]
    if isinstance(item, (list, tuple)):
        if not item:
            return [f"{pad}- [0]:"]
        inner = _sized_array("", item, depth, tabular=False)
        inner[0] = f"{pad}- " + inner[0][len(pad):]
        return inner
    if not item:
        return [f"{pad}-"]
    lines = _object(item, depth + 1)
    lines[0] = f"{pad}- " + lines[0][len(pad) + len(INDENT):]
    return lines


def _field(name, value, depth):
    pad = INDENT * depth
    label = _key(name)
    if _is_primitive(value):
        return [f"{pad}{label}: {_primitive(value)}"]
    if isinstance(value, dict):
        return [f"{pad}{label}:"] + _object(value, depth + 1)
    return _array(label, list(value), depth)


def _object(obj, depth):
    lines = []
    for name, value in obj.items():
        lines.extend(_field(name, value, depth))
    return lines


def encode(value):
    if _is_primitive(value):
        return _primitive(value)
    if isinstance(value, dict):
        return "\n".join(_object(value, 0))
    return "\n".join(_array("", list(value), 0))
