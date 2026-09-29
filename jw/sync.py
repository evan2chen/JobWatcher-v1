import collections
import json
import os
import time

from . import config, db, digest, exporter, ingest, paths, registry, runner

OK_STATUSES = ("ok", "partial")

LOCK_KEY = "sync_lock"
LOCK_STALE_AFTER_SECONDS = 600


class Busy(Exception):
    def __init__(self, holder, now):
        started_at = holder.get("started_at", now)
        super().__init__(
            f"another sync started {now - started_at}s ago (pid {holder.get('pid')}) "
            "and is still running"
        )
        self.code = "BUSY"
        self.help = ["Wait for it to finish, or retry in a few seconds"]


def _acquire_lock(con, now):
    con.execute("BEGIN IMMEDIATE")
    try:
        existing = db.get_meta(con, LOCK_KEY)
        if existing:
            holder = json.loads(existing)
            if now - holder.get("started_at", 0) < LOCK_STALE_AFTER_SECONDS:
                con.rollback()
                raise Busy(holder, now)
        db.set_meta(con, LOCK_KEY, json.dumps({"pid": os.getpid(), "started_at": now}))
        con.commit()
    except Busy:
        raise
    except Exception:
        con.rollback()
        raise


def _release_lock(con):
    con.execute("DELETE FROM meta WHERE key=?", (LOCK_KEY,))
    con.commit()


def collector_config(con, collector):
    has_history = con.execute(
        "SELECT 1 FROM observed WHERE source=? LIMIT 1", (collector["name"],)).fetchone()
    return {
        "filters": collector["filters"],
        "track_all": collector["track_all"],
        "seed_hours": collector["seed_hours"],
        "baseline": has_history is None,
    }


def _health_error(result):
    detail = result.detail or ""
    if result.stderr_tail:
        detail = f"{detail}: {result.stderr_tail[-1]}" if detail else result.stderr_tail[-1]
    return detail[:300] or None


def run_collector(con, collector, root, watchlist, now, dry_run=False, track_tracker=True):
    name = collector["name"]
    row = {"name": name}
    result = runner.run(collector["command"], name, root, collector["timeout_s"],
                        collector["max_output_mb"], collector["env"])
    row["seconds"] = round(result.duration, 1)
    if result.status != "ok":
        row.update(status=result.status, error=_health_error(result),
                   stderr_tail=result.stderr_tail)
        if not dry_run:
            registry.record_run(con, name, result.status, row["error"], None, None, now)
            con.commit()
        return row, []

    batch = ingest.parse_batch(result.stdout.decode("utf-8", "replace"), source=name, now=now)
    row["rejected"] = batch.rejected
    row["errors"] = batch.errors[:ingest.MAX_ERRORS_SHOWN]
    if batch.errors and not batch.observations:
        error = f"line {batch.errors[0]['line']}: {batch.errors[0]['error']}"
        row.update(status="invalid", error=error, observations=0)
        if not dry_run:
            registry.record_run(con, name, "invalid", error, 0, 0, now)
            con.commit()
        return row, []

    try:
        config_for = collector_config(con, collector)
        summary = ingest.apply(con, batch.observations, lambda _s: config_for, watchlist, now,
                               track_tracker=track_tracker)
        status = "partial" if batch.errors or summary["collisions"] else "ok"
        if dry_run:
            con.rollback()
        else:
            if summary["created_companies"]:
                config.companies_append(summary["created_companies"], root)
            registry.record_run(con, name, status, None, summary["observations"],
                                len(summary["surfaced"]), now)
            con.commit()
    except Exception:
        con.rollback()
        raise

    row.update(status=status, observations=summary["observations"],
               new=len(summary["surfaced"]), opened=summary["opened"],
               updated=summary["updated"], closed=summary["closed"],
               unresolved=summary["unresolved"],
               unresolved_top=summary["unresolved_top"],
               created_companies=[c["id"] for c in summary["created_companies"]],
               collisions=summary["collisions"][:ingest.MAX_ERRORS_SHOWN])
    return row, summary["surfaced"]


def build_digest(listings, watchlist):
    by_source = collections.OrderedDict()
    for entry in listings:
        by_source.setdefault(entry["source_repo"], []).append(entry)
    hits = sum(1 for e in listings if digest.matches_watchlist(e.get("company_name"), watchlist))
    text = digest.build_slack_message(by_source, watchlist) if listings else None
    return {
        "new_listings": len(listings),
        "by_source": {k: len(v) for k, v in by_source.items()},
        "watchlist_hits": hits,
        "digest_text": text,
        "listings": listings,
    }


def _merge_unresolved(rows):
    merged = collections.Counter()
    for row in rows:
        for item in row.get("unresolved_top") or []:
            merged[item["name"]] += item["observations"]
    return [{"name": n, "observations": c} for n, c in merged.most_common(ingest.UNRESOLVED_SHOWN)]


def export_state(con, root, now):
    exporter.export_all(con, root, derived=True)
    db.set_meta(con, "last_export", str(now))
    con.commit()


def sync_run(con, source=None, no_tracker=False, dry_run=False, root=None, now=None):
    root = root or paths.home()
    now = int(now if now is not None else time.time())
    if source:
        collectors = [registry.get(con, source)]
    else:
        collectors = [c for c in registry.list_all(con) if c["enabled"]]
    if not collectors:
        raise registry.SourceError(
            "NO_SOURCES", "no enabled sources are registered",
            ["Run `jw source add --simplify SimplifyJobs/New-Grad-Positions` to add one",
             "Run `jw init --starter` on a new home for the starter sources"])

    if not dry_run:
        _acquire_lock(con, now)
    try:
        watchlist = digest.normalize_watchlist(config.watchlist_list(root))
        rows, surfaced = [], []
        for collector in collectors:
            row, listings = run_collector(con, collector, root, watchlist, now, dry_run=dry_run,
                                          track_tracker=not no_tracker)
            rows.append(row)
            surfaced.extend(listings)

        if not dry_run and any(r["status"] in OK_STATUSES for r in rows):
            export_state(con, root, now)
            db.set_meta(con, "last_sync", str(now))
            con.commit()
    finally:
        if not dry_run:
            _release_lock(con)

    result = {"dry_run": dry_run, "sources": rows}
    result.update(build_digest(surfaced, watchlist))
    result["opened"] = sum(r.get("opened", 0) for r in rows)
    result["unresolved"] = sum(r.get("unresolved", 0) for r in rows)
    result["unresolved_top"] = _merge_unresolved(rows)
    result["created_companies"] = [c for r in rows for c in r.get("created_companies", [])]
    result["failed"] = sum(1 for r in rows if r["status"] not in OK_STATUSES)
    return result


def digest_since(con, since, root=None):
    watchlist = digest.normalize_watchlist(config.watchlist_list(root))
    rows = [
        {
            "id": r["id"],
            "source_repo": r["source_repo"],
            "company_name": r["company_name"],
            "title": r["title"],
            "locations": json.loads(r["locations"]),
            "url": r["url"],
        }
        for r in con.execute(
            "SELECT * FROM listings WHERE COALESCE(date_first_seen, 0) >= ? ORDER BY seq",
            (int(since),),
        )
    ]
    return build_digest(rows, watchlist)
