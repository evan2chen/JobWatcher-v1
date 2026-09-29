import os

from . import guide

MARKER = "<!-- managed by `jw skills install`; edits are overwritten on the next install -->"
SKILLS_REL = os.path.join(".agents", "skills")


def _skill_dir(root, topic):
    return os.path.join(root, SKILLS_REL, f"jw-{topic}")


def _skill_path(root, topic):
    return os.path.join(_skill_dir(root, topic), "SKILL.md")


def render(topic, version):
    frontmatter = (
        "---\n"
        f"name: jw-{topic}\n"
        f"description: {guide.summary(topic)}\n"
        f"version: {version}\n"
        "---\n"
    )
    return f"{frontmatter}\n{MARKER}\n\n{guide.read(topic)}\n"


def _is_managed(path):
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as fh:
        return MARKER in fh.read()


def install(root, version):
    rows = []
    for topic in guide.TOPIC_NAMES:
        path = _skill_path(root, topic)
        name = f"jw-{topic}"
        if os.path.exists(path) and not _is_managed(path):
            rows.append({"name": name, "status": "left alone (not jw-managed)"})
            continue
        content = render(topic, version)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                if fh.read() == content:
                    rows.append({"name": name, "status": "unchanged"})
                    continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        rows.append({"name": name, "status": "written"})
    return rows


def list_installed(root):
    rows = []
    for topic in guide.TOPIC_NAMES:
        path = _skill_path(root, topic)
        name = f"jw-{topic}"
        if not os.path.exists(path):
            rows.append({"name": name, "installed": False, "managed": False})
            continue
        rows.append({"name": name, "installed": True, "managed": _is_managed(path)})
    return rows


def remove(root):
    removed = []
    for topic in guide.TOPIC_NAMES:
        path = _skill_path(root, topic)
        if not (os.path.exists(path) and _is_managed(path)):
            continue
        os.remove(path)
        skill_dir = _skill_dir(root, topic)
        try:
            os.rmdir(skill_dir)
        except OSError:
            pass
        removed.append(f"jw-{topic}")
    return removed
