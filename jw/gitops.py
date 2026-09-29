import os
import subprocess
import time

from . import db, exporter, paths

STATE_PATHS = ("sources.json", "seen_listings.json", "watchlist.json", "collectors.json",
               "observed.json", "tracker")

DEFAULT_MESSAGE = "chore: jobwatcher state snapshot"


class NotARepo(RuntimeError):
    pass


def _git(*args, check=True):
    proc = subprocess.run(
        ["git", "-C", paths.home(), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc


def _existing(paths_):
    root = paths.home()
    return [p for p in paths_ if os.path.exists(os.path.join(root, p))]


def ensure_repo():
    proc = _git("rev-parse", "--is-inside-work-tree", check=False)
    if proc.returncode != 0:
        raise NotARepo(f"{paths.home()} is not a git repository")


def pending(paths_=STATE_PATHS):
    tracked = _existing(paths_)
    if not tracked:
        return []
    proc = _git("status", "--porcelain", "--", *tracked)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def snapshot(con=None, message=None, push=False, dry_run=False, now=None):
    ensure_repo()
    if con is not None and not dry_run:
        exporter.export_all(con, paths.home(), derived=True)
    changes = pending()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    result = {"branch": branch, "changed_files": len(changes), "files": changes[:50]}

    if not changes:
        result.update({"ok": True, "committed": False, "reason": "nothing to snapshot"})
        return result
    if dry_run:
        result.update({"ok": True, "dry_run": True, "committed": False,
                       "would_commit": message or DEFAULT_MESSAGE, "would_push": push})
        return result

    _git("add", "--", *_existing(STATE_PATHS))
    _git("commit", "-m", message or DEFAULT_MESSAGE)
    sha = _git("rev-parse", "HEAD").stdout.strip()
    result.update({"ok": True, "committed": True, "commit": sha})

    if push:
        proc = _git("push", check=False)
        result["pushed"] = proc.returncode == 0
        if proc.returncode != 0:
            result["ok"] = False
            result["push_error"] = (proc.stderr or proc.stdout).strip().splitlines()[-3:]

    if con is not None:
        db.set_meta(con, "last_push" if push else "last_snapshot",
                    str(int(now if now is not None else time.time())))
        con.commit()
    return result
