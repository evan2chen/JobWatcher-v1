import json
import os

from . import paths


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def export_all(con, root=None, derived=False):
    root = root or paths.home()
    written = []
    written.append(export_sources(con, root))
    written.append(export_listings(con, root))
    written.append(export_companies(con, root))
    written.extend(export_tracker(con, root))
    written.extend(export_collectors(con, root))
    written.extend(export_observed(con, root))
    if derived:
        written.extend(export_derived(con, root))
    return written


def export_derived(con, root=None, now_ts=None):
    import time

    from . import reconcile

    root = root or paths.home()
    tracker_dir = paths.tracker_dir(root)
    companies = [
        {
            "id": r["id"],
            "display_name": r["display_name"],
            "tier": r["tier"],
            "careers_url": r["careers_url"],
            "levels_url": r["levels_url"],
        }
        for r in con.execute("SELECT * FROM companies ORDER BY seq")
    ]
    now_ts = int(now_ts if now_ts is not None else time.time())
    reconcile.build_index(tracker_dir, companies, now_ts)
    reconcile.build_all_postings(tracker_dir, companies, now_ts)
    return [
        os.path.join(tracker_dir, "index.json"),
        os.path.join(tracker_dir, "all_postings.json"),
    ]


def export_sources(con, root):
    path = paths.sources_path(root)
    out = []
    for src in con.execute("SELECT * FROM sources ORDER BY seq"):
        known = [
            r["listing_id"] for r in con.execute(
                "SELECT listing_id FROM known_ids WHERE repo=? ORDER BY seq",
                (src["repo"],),
            )
        ]
        out.append({
            "repo": src["repo"],
            "branch": src["branch"],
            "listings_path": src["listings_path"],
            "last_sha": src["last_sha"],
            "last_run_timestamp": src["last_run_timestamp"],
            "known_ids": known,
            "filters": json.loads(src["filters"]),
        })
    if out or os.path.exists(path):
        _write_json(path, out)
    return path


def export_listings(con, root):
    from .applications import legacy_status_map

    overrides = legacy_status_map(con)
    out = []
    for r in con.execute("SELECT * FROM listings ORDER BY seq"):
        status, status_updated, notes = r["status"], r["status_updated"], r["notes"]
        if r["id"] in overrides:
            status, status_updated, app_notes = overrides[r["id"]]
            notes = app_notes or notes
        out.append({
            "id": r["id"],
            "source_repo": r["source_repo"],
            "company_name": r["company_name"],
            "title": r["title"],
            "category": r["category"],
            "locations": json.loads(r["locations"]),
            "url": r["url"],
            "date_posted": r["date_posted"],
            "date_first_seen": r["date_first_seen"],
            "status": status,
            "status_updated": status_updated,
            "notes": notes,
        })
    path = paths.seen_path(root)
    if out or os.path.exists(path):
        _write_json(path, out)
    return path


def export_companies(con, root):
    path = paths.companies_path(root)
    out = [
        {
            "id": r["id"],
            "display_name": r["display_name"],
            "tier": r["tier"],
            "careers_url": r["careers_url"],
            "levels_url": r["levels_url"],
            "aliases": json.loads(r["aliases"]),
            "notes": r["notes"],
        }
        for r in con.execute("SELECT * FROM companies ORDER BY seq")
    ]
    _write_json(path, out)
    return path


def _sync_optional_file(path, data):
    if data:
        _write_json(path, data)
        return [path]
    if os.path.exists(path):
        os.remove(path)
    return []


def export_collectors(con, root):
    out = [
        {
            "name": r["name"],
            "command": json.loads(r["command"]),
            "filters": json.loads(r["filters"]),
            "env": json.loads(r["env"]),
            "track_all": bool(r["track_all"]),
            "seed_hours": r["seed_hours"],
            "timeout_s": r["timeout_s"],
            "max_output_mb": r["max_output_mb"],
            "enabled": bool(r["enabled"]),
            "id_namespace": r["id_namespace"],
            "created_at": r["created_at"],
        }
        for r in con.execute("SELECT * FROM collectors ORDER BY seq")
    ]
    return _sync_optional_file(paths.collectors_path(root), out)


def export_observed(con, root):
    out = {}
    for r in con.execute("SELECT source, external_id FROM observed ORDER BY seq"):
        out.setdefault(r["source"], []).append(r["external_id"])
    return _sync_optional_file(paths.observed_path(root), out)


def export_tracker(con, root):
    written = []
    tracker_root = paths.tracker_dir(root)
    for store in con.execute("SELECT * FROM stores ORDER BY company_id"):
        cid = store["company_id"]
        cdir = paths.company_dir(cid, tracker_root)
        if store["has_postings"]:
            written.append(_write_doc(cdir, "postings.json", postings_document(con, cid)))
        if store["has_crosswalk"]:
            written.append(_write_doc(cdir, "crosswalk.json", crosswalk_document(con, cid)))
        if store["has_events"]:
            written.append(_write_events(cdir, event_records(con, cid)))
    return written


def _write_doc(cdir, name, doc):
    path = os.path.join(cdir, name)
    _write_json(path, doc)
    return path


def _write_events(cdir, events):
    path = os.path.join(cdir, "events.jsonl")
    os.makedirs(cdir, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


def postings_document(con, company_id):
    postings = []
    for p in con.execute(
        "SELECT * FROM postings WHERE company_id=? ORDER BY seq", (company_id,)
    ):
        sources = {}
        for s in con.execute(
            "SELECT * FROM posting_sources WHERE posting_id=? ORDER BY seq",
            (p["posting_id"],),
        ):
            sources[s["source_key"]] = {
                "external_id": s["external_id"],
                "url": s["url"],
                "state": s["state"],
                "first_seen": s["first_seen"],
                "last_seen": s["last_seen"],
            }
        postings.append({
            "posting_id": p["posting_id"],
            "company_id": p["company_id"],
            "role_key": p["role_key"],
            "level": p["level"],
            "title": p["title"],
            "terms": json.loads(p["terms"]),
            "locations": json.loads(p["locations"]),
            "apply_url": p["apply_url"],
            "posted_at": p["posted_at"],
            "first_seen": p["first_seen"],
            "last_seen": p["last_seen"],
            "closed_at": p["closed_at"],
            "state": p["state"],
            "pay": json.loads(p["pay"]) if p["pay"] is not None else None,
            "sources": sources,
            "attributes": json.loads(p["attributes"]),
        })
    return {"company_id": company_id, "postings": postings}


def crosswalk_document(con, company_id):
    out = {"external": {}, "natural": {}}
    for kind in ("external", "natural"):
        for r in con.execute(
            "SELECT key, posting_id FROM crosswalk WHERE company_id=? AND kind=? "
            "ORDER BY seq",
            (company_id, kind),
        ):
            out[kind][r["key"]] = r["posting_id"]
    return out


def event_records(con, company_id):
    events = []
    for r in con.execute(
        "SELECT * FROM events WHERE company_id=? ORDER BY seq", (company_id,)
    ):
        ev = {
            "at": r["at"],
            "posting_id": r["posting_id"],
            "role_key": r["role_key"],
            "type": r["type"],
            "source": r["source"],
        }
        if r["detail"] is not None:
            ev["detail"] = json.loads(r["detail"])
        events.append(ev)
    return events
