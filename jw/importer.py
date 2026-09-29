import json
import os

from . import db, paths


def _load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if default is None:
            raise
        return default


FILE_BACKED = (
    "known_ids", "sources", "listings", "companies", "stores",
    "posting_sources", "postings", "crosswalk", "events", "collectors", "observed",
)


def import_all(con, root=None, replace=False):
    root = root or paths.home()
    if replace:
        for table in FILE_BACKED:
            con.execute(f"DELETE FROM {table}")
    counts = {}
    counts["sources"], counts["known_ids"] = _import_sources(con, root)
    counts["listings"] = _import_listings(con, root)
    counts["companies"] = _import_companies(con, root)
    tracker = _import_tracker(con, root)
    counts.update(tracker)
    counts["collectors"] = _import_collectors(con, root)
    counts["observed"] = _import_observed(con, root)
    counts["applications_adopted"] = _adopt_listing_status(con)
    db.set_meta(con, "imported_from", root)
    con.commit()
    return counts


def _adopt_listing_status(con):
    from .applications import LEGACY_TO_STATUS

    adopted = 0
    for row in con.execute(
        "SELECT l.id, l.status, l.status_updated, l.notes, l.date_first_seen "
        "FROM listings l LEFT JOIN applications a ON a.listing_id = l.id "
        "WHERE a.id IS NULL AND l.status != 'new'"
    ).fetchall():
        status = LEGACY_TO_STATUS.get(row["status"])
        if status is None:
            continue
        at = row["status_updated"] or row["date_first_seen"] or 0
        cur = con.execute(
            "INSERT INTO applications (posting_id, listing_id, company_id, status, "
            "status_at, notes, created_at) VALUES (NULL, ?, NULL, ?, ?, ?, ?)",
            (row["id"], status, at, row["notes"] or "", at),
        )
        con.execute(
            "INSERT INTO application_history (application_id, at, status, note) "
            "VALUES (?, ?, ?, ?)",
            (cur.lastrowid, at, status, "adopted from seen_listings.json"),
        )
        adopted += 1
    return adopted


def _import_sources(con, root):
    sources = _load(paths.sources_path(root), [])
    n_ids = 0
    for seq, src in enumerate(sources):
        con.execute(
            "INSERT INTO sources (repo, seq, branch, listings_path, last_sha, "
            "last_run_timestamp, filters) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                src["repo"], seq, src["branch"], src["listings_path"],
                src.get("last_sha"), src.get("last_run_timestamp"),
                json.dumps(src.get("filters", {}), ensure_ascii=False),
            ),
        )
        rows = [(src["repo"], lid, i) for i, lid in enumerate(src.get("known_ids", []))]
        con.executemany(
            "INSERT INTO known_ids (repo, listing_id, seq) VALUES (?, ?, ?)", rows
        )
        n_ids += len(rows)
    return len(sources), n_ids


def _import_listings(con, root):
    listings = _load(paths.seen_path(root), [])
    con.executemany(
        "INSERT INTO listings (id, seq, source_repo, company_name, title, category, "
        "locations, url, date_posted, date_first_seen, status, status_updated, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                e["id"], seq, e["source_repo"], e.get("company_name"), e.get("title"),
                e.get("category"), json.dumps(e.get("locations", []), ensure_ascii=False),
                e.get("url"), e.get("date_posted"), e.get("date_first_seen"),
                e.get("status", "new"), e.get("status_updated"), e.get("notes", ""),
            )
            for seq, e in enumerate(listings)
        ],
    )
    return len(listings)


def company_row(seq, c):
    return (
        c["id"], seq, c["display_name"], c.get("tier"), c.get("careers_url"),
        c.get("levels_url"), json.dumps(c.get("aliases", {}), ensure_ascii=False),
        c.get("notes", ""),
    )


COMPANY_INSERT = (
    "INSERT INTO companies (id, seq, display_name, tier, careers_url, levels_url, "
    "aliases, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


def _import_companies(con, root):
    companies = _load(paths.companies_path(root), [])
    con.executemany(COMPANY_INSERT,
                    [company_row(seq, c) for seq, c in enumerate(companies)])
    return len(companies)


def _import_collectors(con, root):
    collectors = _load(paths.collectors_path(root), [])
    for seq, c in enumerate(collectors):
        con.execute(
            "INSERT INTO collectors (name, seq, command, filters, env, track_all, "
            "seed_hours, timeout_s, max_output_mb, enabled, id_namespace, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                c["name"], seq, json.dumps(c["command"], ensure_ascii=False),
                json.dumps(c.get("filters", {}), ensure_ascii=False),
                json.dumps(c.get("env", []), ensure_ascii=False),
                int(c.get("track_all", False)), c.get("seed_hours", 25),
                c.get("timeout_s", 300), c.get("max_output_mb", 64),
                int(c.get("enabled", True)), c.get("id_namespace", ""),
                c.get("created_at", 0),
            ),
        )
    return len(collectors)


def _import_observed(con, root):
    observed = _load(paths.observed_path(root), {})
    seq = 0
    rows = []
    for source, external_ids in observed.items():
        for external_id in external_ids:
            rows.append((source, external_id, seq))
            seq += 1
    con.executemany(
        "INSERT INTO observed (source, external_id, seq) VALUES (?, ?, ?)", rows)
    return len(rows)


def _import_tracker(con, root):
    base = paths.companies_dir(paths.tracker_dir(root))
    counts = {"postings": 0, "posting_sources": 0, "crosswalk": 0, "events": 0, "stores": 0}
    if not os.path.isdir(base):
        return counts

    for company_id in sorted(os.listdir(base)):
        cdir = os.path.join(base, company_id)
        if not os.path.isdir(cdir):
            continue
        p_path = os.path.join(cdir, "postings.json")
        x_path = os.path.join(cdir, "crosswalk.json")
        e_path = os.path.join(cdir, "events.jsonl")
        has_p, has_x, has_e = (os.path.isfile(f) for f in (p_path, x_path, e_path))
        if not (has_p or has_x or has_e):
            continue

        con.execute(
            "INSERT INTO stores (company_id, has_postings, has_crosswalk, has_events) "
            "VALUES (?, ?, ?, ?)",
            (company_id, int(has_p), int(has_x), int(has_e)),
        )
        counts["stores"] += 1

        if has_p:
            doc = _load(p_path, {})
            postings = doc.get("postings", []) if isinstance(doc, dict) else (doc or [])
            n_postings, n_sources = insert_postings(con, company_id, postings)
            counts["postings"] += n_postings
            counts["posting_sources"] += n_sources
        if has_x:
            counts["crosswalk"] += insert_crosswalk(con, company_id, _load(x_path, {}))
        if has_e:
            counts["events"] += insert_events(con, company_id, _read_events(e_path))
    return counts


def insert_postings(con, company_id, postings):
    n_sources = 0
    for p_seq, p in enumerate(postings):
        con.execute(
            "INSERT INTO postings (posting_id, seq, company_id, role_key, level, title, "
            "terms, locations, apply_url, posted_at, first_seen, last_seen, closed_at, "
            "state, pay, attributes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p["posting_id"], p_seq, p.get("company_id", company_id), p.get("role_key"),
                p.get("level"), p.get("title"),
                json.dumps(p.get("terms", []), ensure_ascii=False),
                json.dumps(p.get("locations", []), ensure_ascii=False),
                p.get("apply_url"), p.get("posted_at"), p.get("first_seen"),
                p.get("last_seen"), p.get("closed_at"), p.get("state", "open"),
                json.dumps(p.get("pay"), ensure_ascii=False),
                json.dumps(p.get("attributes", {}), ensure_ascii=False),
            ),
        )
        for seq, (source_key, entry) in enumerate(p.get("sources", {}).items()):
            con.execute(
                "INSERT INTO posting_sources (posting_id, source_key, seq, external_id, "
                "url, state, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    p["posting_id"], source_key, seq, entry.get("external_id"),
                    entry.get("url"), entry.get("state"), entry.get("first_seen"),
                    entry.get("last_seen"),
                ),
            )
            n_sources += 1
    return len(postings), n_sources


def insert_crosswalk(con, company_id, doc):
    n = 0
    for kind in ("external", "natural"):
        for seq, (key, posting_id) in enumerate(doc.get(kind, {}).items()):
            con.execute(
                "INSERT INTO crosswalk (company_id, kind, key, posting_id, seq) "
                "VALUES (?, ?, ?, ?, ?)",
                (company_id, kind, key, posting_id, seq),
            )
            n += 1
    return n


def _read_events(path):
    events = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def insert_events(con, company_id, events, start_seq=0):
    rows = [
        (
            company_id, start_seq + offset, ev["at"], ev["posting_id"], ev.get("role_key"),
            ev["type"], ev.get("source"),
            json.dumps(ev["detail"], ensure_ascii=False) if "detail" in ev else None,
        )
        for offset, ev in enumerate(events)
    ]
    con.executemany(
        "INSERT INTO events (company_id, seq, at, posting_id, role_key, type, source, "
        "detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)
