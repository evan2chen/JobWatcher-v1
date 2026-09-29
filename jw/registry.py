import json
import re
import shlex
import time

from .collectors import simplify

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,80}$")
ENV_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FILTER_KEYS = {"categories", "title_keywords", "locations", "active_only", "visible_only"}


class SourceError(Exception):
    def __init__(self, code, message, help=None):
        super().__init__(message)
        self.code = code
        self.help = help or []


def parse_command(text):
    text = (text or "").strip()
    if not text:
        raise SourceError("VALIDATION_ERROR", "the collector command is empty")
    if text.startswith("["):
        try:
            argv = json.loads(text)
        except ValueError as exc:
            raise SourceError("VALIDATION_ERROR", f"command looks like JSON but is not: {exc}")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise SourceError("VALIDATION_ERROR", "a JSON command must be a non-empty array of strings")
        return argv
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise SourceError("VALIDATION_ERROR", f"cannot parse the command: {exc}")


def parse_filters(text):
    if not text:
        return {}
    try:
        filters = json.loads(text)
    except ValueError as exc:
        raise SourceError("VALIDATION_ERROR", f"--filters must be JSON: {exc}")
    if not isinstance(filters, dict):
        raise SourceError("VALIDATION_ERROR", "--filters must be a JSON object")
    unknown = sorted(set(filters) - FILTER_KEYS)
    if unknown:
        raise SourceError("VALIDATION_ERROR",
                          f"unknown filter key(s): {', '.join(unknown)}",
                          [f"Valid keys: {', '.join(sorted(FILTER_KEYS))}"])
    return filters


def simplify_command(repo, branch=None, path=None):
    command = ["python", "-m", "jw.collectors.simplify", repo]
    if branch and branch != simplify.DEFAULT_BRANCH:
        command += ["--branch", branch]
    if path and path != simplify.DEFAULT_PATH:
        command += ["--path", path]
    return command


def simplify_name(repo):
    return simplify.source_id(repo)


def to_dict(row):
    return {
        "name": row["name"],
        "command": json.loads(row["command"]),
        "filters": json.loads(row["filters"]),
        "env": json.loads(row["env"]),
        "track_all": bool(row["track_all"]),
        "seed_hours": row["seed_hours"],
        "timeout_s": row["timeout_s"],
        "max_output_mb": row["max_output_mb"],
        "enabled": bool(row["enabled"]),
        "id_namespace": row["id_namespace"],
        "created_at": row["created_at"],
        "last_run_at": row["last_run_at"],
        "last_status": row["last_status"],
        "last_error": row["last_error"],
        "last_observations": row["last_observations"],
        "last_new": row["last_new"],
    }


def list_all(con, name=None):
    sql = "SELECT * FROM collectors"
    params = ()
    if name:
        sql += " WHERE name = ?"
        params = (name,)
    return [to_dict(r) for r in con.execute(sql + " ORDER BY seq", params)]


def get(con, name):
    rows = list_all(con, name)
    if not rows:
        raise SourceError("NOT_FOUND", f"no source named {name!r}",
                          ["Run `jw source list` to see registered sources"])
    return rows[0]


def _validate(name, env, seed_hours, timeout_s, max_output_mb):
    if not NAME_PATTERN.match(name or ""):
        raise SourceError("VALIDATION_ERROR",
                          f"source name {name!r} must start with a letter or digit and use "
                          "only letters, digits and : . _ -")
    for var in env:
        if not ENV_PATTERN.match(var):
            raise SourceError("VALIDATION_ERROR", f"{var!r} is not an environment variable name")
    if seed_hours < 0 or timeout_s < 1 or max_output_mb < 1:
        raise SourceError("VALIDATION_ERROR",
                          "seed hours must be >= 0, timeout >= 1 s, max output >= 1 MB")


SIMPLIFY_NAMESPACE = "simplify"


def add(con, name, command, filters=None, env=(), track_all=False, seed_hours=25,
        timeout_s=300, max_output_mb=64, enabled=True, id_namespace="", now=None):
    _validate(name, env, seed_hours, timeout_s, max_output_mb)
    record = {
        "name": name, "command": list(command), "filters": filters or {},
        "env": list(env), "track_all": bool(track_all), "seed_hours": seed_hours,
        "timeout_s": timeout_s, "max_output_mb": max_output_mb, "enabled": bool(enabled),
        "id_namespace": id_namespace or "",
    }
    existing = con.execute("SELECT * FROM collectors WHERE name=?", (name,)).fetchone()
    if existing is not None:
        current = to_dict(existing)
        if all(current[k] == v for k, v in record.items()):
            return current, False
        raise SourceError("ALREADY_EXISTS", f"source {name!r} is registered with a different setup",
                          [f"Run `jw source update {name} --command <cmd>` to change it"])

    seq = con.execute("SELECT COALESCE(MAX(seq) + 1, 0) AS n FROM collectors").fetchone()["n"]
    con.execute(
        "INSERT INTO collectors (name, seq, command, filters, env, track_all, seed_hours, "
        "timeout_s, max_output_mb, enabled, id_namespace, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, seq, json.dumps(record["command"], ensure_ascii=False),
         json.dumps(record["filters"], ensure_ascii=False),
         json.dumps(record["env"]), int(track_all), seed_hours, timeout_s, max_output_mb,
         int(enabled), record["id_namespace"], int(now if now is not None else time.time())),
    )
    con.commit()
    return get(con, name), True


def update(con, name, **changes):
    current = get(con, name)
    merged = dict(current)
    merged.update({k: v for k, v in changes.items() if v is not None})
    _validate(name, merged["env"], merged["seed_hours"], merged["timeout_s"],
              merged["max_output_mb"])
    fields = ("command", "filters", "env", "track_all", "seed_hours", "timeout_s",
              "max_output_mb", "id_namespace")
    changed = [k for k in fields if merged[k] != current[k]]
    if changed:
        con.execute(
            "UPDATE collectors SET command=?, filters=?, env=?, track_all=?, seed_hours=?, "
            "timeout_s=?, max_output_mb=?, id_namespace=? WHERE name=?",
            (json.dumps(merged["command"], ensure_ascii=False),
             json.dumps(merged["filters"], ensure_ascii=False), json.dumps(merged["env"]),
             int(merged["track_all"]), merged["seed_hours"], merged["timeout_s"],
             merged["max_output_mb"], merged["id_namespace"], name),
        )
        con.commit()
    return get(con, name), changed


def remove(con, name):
    get(con, name)
    con.execute("DELETE FROM collectors WHERE name=?", (name,))
    con.commit()


def set_enabled(con, name, enabled):
    current = get(con, name)
    con.execute("UPDATE collectors SET enabled=? WHERE name=?", (int(enabled), name))
    con.commit()
    return current["enabled"] != enabled


def record_run(con, name, status, error, observations, new, now=None):
    con.execute(
        "UPDATE collectors SET last_run_at=?, last_status=?, last_error=?, "
        "last_observations=?, last_new=? WHERE name=?",
        (int(now if now is not None else time.time()), status, error, observations, new, name),
    )


def adopt_legacy(con, dry_run=False, now=None):
    adopted = []
    existing = {r["name"] for r in con.execute("SELECT name FROM collectors")}
    next_seq = con.execute("SELECT COALESCE(MAX(seq) + 1, 0) AS n FROM collectors").fetchone()["n"]
    next_observed = con.execute(
        "SELECT COALESCE(MAX(seq) + 1, 0) AS n FROM observed").fetchone()["n"]
    for src in con.execute("SELECT * FROM sources ORDER BY seq").fetchall():
        name = simplify_name(src["repo"])
        if name in existing:
            continue
        ids = [r["listing_id"] for r in con.execute(
            "SELECT listing_id FROM known_ids WHERE repo=? ORDER BY seq", (src["repo"],))]
        adopted.append({"name": name, "repo": src["repo"], "known_ids": len(ids)})
        if dry_run:
            continue
        command = simplify_command(src["repo"], src["branch"], src["listings_path"])
        con.execute(
            "INSERT INTO collectors (name, seq, command, filters, env, track_all, seed_hours, "
            "timeout_s, max_output_mb, enabled, id_namespace, created_at) "
            "VALUES (?, ?, ?, ?, '[]', 0, 25, 300, 64, 1, ?, ?)",
            (name, next_seq, json.dumps(command), src["filters"], SIMPLIFY_NAMESPACE,
             int(now if now is not None else time.time())),
        )
        next_seq += 1
        rows = [(name, lid, next_observed + i) for i, lid in enumerate(ids)]
        con.executemany(
            "INSERT OR IGNORE INTO observed (source, external_id, seq) VALUES (?, ?, ?)", rows)
        next_observed += len(rows)
    if not dry_run:
        con.commit()
    return adopted
