import json
import os
import shutil
import sys

MARKER = "hooks summary"
SETTINGS_REL = os.path.join(".claude", "settings.json")


def _settings_path(root):
    return os.path.join(root, SETTINGS_REL)


def _load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    return json.loads(text) if text else {}


def _dump(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def resolve_command():
    found = shutil.which("jw")
    if found:
        return f'"{found}" hooks summary'
    return f'"{sys.executable}" -m jw hooks summary'


def install(root):
    path = _settings_path(root)
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    entries = hooks.setdefault("SessionStart", [])
    command = resolve_command()
    for entry in entries:
        for h in entry.get("hooks", []):
            if h.get("type") == "command" and MARKER in h.get("command", ""):
                already_current = h["command"] == command
                h["command"] = command
                _dump(path, data)
                return {"path": path, "action": "unchanged" if already_current else "updated"}
    entries.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})
    _dump(path, data)
    return {"path": path, "action": "installed"}


def remove(root):
    path = _settings_path(root)
    data = _load(path)
    entries = data.get("hooks", {}).get("SessionStart", [])
    kept_entries = []
    removed = False
    for entry in entries:
        current = entry.get("hooks", [])
        kept_hooks = [h for h in current if MARKER not in h.get("command", "")]
        if len(kept_hooks) != len(current):
            removed = True
        if kept_hooks:
            kept_entries.append({**entry, "hooks": kept_hooks})
    if not removed:
        return {"path": path, "action": "not installed"}
    if kept_entries:
        data["hooks"]["SessionStart"] = kept_entries
    else:
        data["hooks"].pop("SessionStart", None)
        if not data["hooks"]:
            data.pop("hooks", None)
    _dump(path, data)
    return {"path": path, "action": "removed"}
