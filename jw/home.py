import json
import os
import subprocess
import sys
import time

from . import db, exporter, importer, output, paths, registry

STARTER_SOURCES = (
    "SimplifyJobs/Summer2027-Internships",
    "SimplifyJobs/New-Grad-Positions",
)
GITIGNORE = "jobwatcher.db\njobwatcher.db-wal\njobwatcher.db-shm\n"
STALE_SYNC_HOURS = 72


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", root, *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _init_git(root):
    try:
        if _git(root, "rev-parse", "--is-inside-work-tree").returncode == 0:
            return "already a repository"
        proc = _git(root, "init", "-q")
    except FileNotFoundError:
        return "git is not installed"
    if proc.returncode != 0:
        return f"git init failed: {(proc.stderr or proc.stdout).strip()}"
    ignore = os.path.join(root, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as fh:
            fh.write(GITIGNORE)
    return "initialised"


def _starter_companies():
    with open(paths.starter_path("companies.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def init_home(root, db_file=None, starter=False, git=False, now=None):
    now = int(now if now is not None else time.time())
    os.makedirs(root, exist_ok=True)
    target = db_file or paths.db_path(root)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    con = db.connect(target)
    created = db.init(con)

    if not os.path.exists(paths.watchlist_path(root)):
        _write_json(paths.watchlist_path(root), [])

    result = {"root": root, "db": target, "created": created,
              "schema_version": db.schema_version(con)}

    has_companies = con.execute("SELECT COUNT(*) AS n FROM companies").fetchone()["n"] > 0
    has_sources = con.execute("SELECT COUNT(*) AS n FROM collectors").fetchone()["n"] > 0
    if starter and not (has_companies or has_sources):
        companies = _starter_companies()
        _write_json(paths.companies_path(root), companies)
        con.executemany(importer.COMPANY_INSERT,
                        [importer.company_row(i, c) for i, c in enumerate(companies)])
        names = []
        for repo in STARTER_SOURCES:
            record, _ = registry.add(con, registry.simplify_name(repo),
                                     registry.simplify_command(repo),
                                     id_namespace=registry.SIMPLIFY_NAMESPACE, now=now)
            names.append(record["name"])
        con.commit()
        result["starter"] = {"companies": len(companies), "sources": names}
    elif starter:
        result["starter"] = "skipped: this home already has companies or sources"
    elif not os.path.exists(paths.companies_path(root)):
        _write_json(paths.companies_path(root), [])

    exporter.export_all(con, root, derived=True)
    if git:
        result["git"] = _init_git(root)
    result["sources"] = con.execute("SELECT COUNT(*) AS n FROM collectors").fetchone()["n"]
    return result


def _check(checks, name, status, detail):
    checks.append({"check": name, "status": status, "detail": detail})


def _store_checks(checks, target):
    if not os.path.exists(target):
        _check(checks, "store", "fail", f"no database at {output.display_path(target)}")
        return None
    con = db.connect(target, create=False)
    version = db.schema_version(con)
    if version is None:
        _check(checks, "store", "fail", "the database has no schema")
        return None
    if version < db.SCHEMA_VERSION:
        _check(checks, "store", "warn",
               f"schema v{version}, current is v{db.SCHEMA_VERSION}; run `jw db migrate`")
        return None
    _check(checks, "store", "ok", f"schema v{version}")
    return con


def _git_check(checks, root):
    try:
        inside = _git(root, "rev-parse", "--is-inside-work-tree")
    except FileNotFoundError:
        _check(checks, "backup", "warn", "git is not installed (optional backup)")
        return
    if inside.returncode == 0:
        branch = _git(root, "symbolic-ref", "--short", "HEAD").stdout.strip() or "detached"
        _check(checks, "backup", "ok", f"git repository on {branch}")
    else:
        _check(checks, "backup", "warn",
               "not a git repository (optional backup); `jw init --git` adds one")


def doctor(root, source, target, now=None):
    now = int(now if now is not None else time.time())
    checks = []
    ok_python = sys.version_info >= (3, 9)
    _check(checks, "python", "ok" if ok_python else "fail", sys.version.split()[0])
    if os.path.isdir(root):
        _check(checks, "home", "ok", f"{output.display_path(root)} ({source})")
    else:
        _check(checks, "home", "fail", f"{output.display_path(root)} does not exist ({source})")

    con = _store_checks(checks, target)
    if con is not None:
        companies = con.execute("SELECT COUNT(*) AS n FROM companies").fetchone()["n"]
        _check(checks, "companies", "ok" if companies else "warn",
               f"{companies} tracked" if companies else "none tracked; unmatched postings are only counted")
        sources = registry.list_all(con)
        enabled = [s for s in sources if s["enabled"]]
        _check(checks, "sources", "ok" if enabled else "warn",
               f"{len(enabled)} enabled of {len(sources)}" if sources else "none registered")
        for src in sources:
            if src["last_status"] not in (None, "ok", "partial"):
                _check(checks, f"source:{src['name']}", "warn",
                       f"{src['last_status']}: {src['last_error'] or 'no detail'}")
        last = db.get_meta(con, "last_sync")
        if last is None:
            _check(checks, "last_sync", "warn", "never synced")
        else:
            stale = now - int(last) > STALE_SYNC_HOURS * 3600
            _check(checks, "last_sync", "warn" if stale else "ok", output.age(int(last), now))

    site = paths.site_dir(root)
    found = os.path.isfile(os.path.join(site, "index.html"))
    _check(checks, "site", "ok" if found else "warn",
           output.display_path(site) if found else "no built site; `jw serve` has no page to show")
    _git_check(checks, root)
    _check(checks, "slack", "ok",
           "webhook configured" if os.environ.get("SLACK_WEBHOOK_URL")
           else "no webhook (only `jw slack post` needs one)")

    failing = [c for c in checks if c["status"] == "fail"]
    return {"healthy": not failing, "checks": checks}


FIXES = {
    "home": "Run `jw init` to create the home",
    "store": "Run `jw init` for a new store, or `jw db import` to load existing JSON state",
    "companies": "Run `jw source update <name> --track-all true`, or `jw company add <slug> --alias <name>`",
    "sources": "Run `jw source add --simplify SimplifyJobs/New-Grad-Positions` to add one",
    "last_sync": "Run `jw sync run` to fetch postings",
    "site": "Build the site with `npm run build` in web/, or install a wheel that bundles it",
}


def fixes(checks):
    out = []
    for check in checks:
        if check["status"] == "ok":
            continue
        name = check["check"]
        if name.startswith("source:"):
            out.append(f"Run `jw source run {name.split(':', 1)[1]} --dry-run` to see why it failed")
        elif name == "store" and "migrate" in check["detail"]:
            out.append("Run `jw db migrate` to upgrade the store")
        elif name in FIXES:
            out.append(FIXES[name])
    return out
