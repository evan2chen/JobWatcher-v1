import json
import re
import time

from .applications import USER_CLOSED_SQL

_OPEN_SQL = f"p.state = 'open' AND NOT {USER_CLOSED_SQL}"
_REL = re.compile(r"^(\d+)([hdw])$")
_UNITS = {"h": 3600, "d": 86400, "w": 604800}


def parse_since(value, now=None):
    if value is None or value == "":
        return None
    now = int(now if now is not None else time.time())
    text = str(value).strip().lower()
    match = _REL.match(text)
    if match:
        return now - int(match.group(1)) * _UNITS[match.group(2)]
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"--since wants a unix timestamp or a span like 7d, got {value!r}")


def _posting_row(r, company=None):
    attrs = json.loads(r["attributes"])
    return {
        "posting_id": r["posting_id"],
        "company_id": r["company_id"],
        "company": company or r["company_id"],
        "title": r["title"],
        "level": r["level"],
        "terms": json.loads(r["terms"]),
        "locations": json.loads(r["locations"]),
        "apply_url": r["apply_url"],
        "posted_at": r["posted_at"],
        "first_seen": r["first_seen"],
        "last_seen": r["last_seen"],
        "closed_at": r["closed_at"],
        "state": "closed" if r["user_closed"] else r["state"],
        "category": attrs.get("category"),
        "sponsorship": attrs.get("sponsorship"),
        "degrees": attrs.get("degrees") or [],
    }


def postings_search(con, company=None, open_only=False, since=None, title=None,
                    category=None, limit=100, now=None, company_id=None):
    sql = [
        f"SELECT p.*, c.display_name, {USER_CLOSED_SQL} AS user_closed FROM postings p ",
        "LEFT JOIN companies c ON c.id = p.company_id ",
    ]
    where, params = [], []
    if company_id:
        where.append("p.company_id = ?")
        params.append(company_id)
    if company:
        where.append("(p.company_id = ? OR LOWER(c.display_name) LIKE ?)")
        params.extend([company, f"%{company.lower()}%"])
    if open_only:
        where.append(_OPEN_SQL)
    since_ts = parse_since(since, now)
    if since_ts is not None:
        where.append("COALESCE(p.posted_at, p.first_seen) >= ?")
        params.append(since_ts)
    if title:
        where.append("LOWER(p.title) LIKE ?")
        params.append(f"%{title.lower()}%")
    if where:
        sql.append("WHERE " + " AND ".join(where) + " ")
    sql.append("ORDER BY COALESCE(p.posted_at, p.first_seen) DESC, p.posting_id")

    out, total = [], 0
    for r in con.execute("".join(sql), params):
        rec = _posting_row(r, r["display_name"])
        if category and (rec["category"] or "").lower() != category.lower():
            continue
        total += 1
        if not limit or len(out) < int(limit):
            out.append(rec)
    return out, total


def postings_query(con, company=None, open_only=False, since=None, title=None,
                   category=None, limit=100, now=None):
    rows, _ = postings_search(con, company=company, open_only=open_only, since=since,
                              title=title, category=category, limit=limit, now=now)
    return rows


def posting_show(con, posting_id):
    from . import applications

    row = con.execute(
        f"SELECT p.*, c.display_name, {USER_CLOSED_SQL} AS user_closed FROM postings p "
        "LEFT JOIN companies c ON c.id = p.company_id WHERE p.posting_id=?",
        (posting_id,),
    ).fetchone()
    if row is None:
        return None
    out = _posting_row(row, row["display_name"])
    out["sources"] = [
        {
            "source": s["source_key"],
            "external_id": s["external_id"],
            "url": s["url"],
            "state": s["state"],
            "first_seen": s["first_seen"],
            "last_seen": s["last_seen"],
        }
        for s in con.execute(
            "SELECT * FROM posting_sources WHERE posting_id=? ORDER BY seq", (posting_id,)
        )
    ]
    out["events"] = [
        {"at": e["at"], "type": e["type"], "source": e["source"],
         "detail": json.loads(e["detail"]) if e["detail"] else None}
        for e in con.execute(
            "SELECT * FROM events WHERE posting_id=? ORDER BY at, id", (posting_id,)
        )
    ]
    target = {"posting_id": posting_id, "listing_id": None}
    app = applications.find(con, target)
    out["application"] = applications._row_to_dict(con, app, history=True) if app else None
    return out


def company_list(con):
    return [
        {
            "id": r["id"],
            "display_name": r["display_name"],
            "tier": r["tier"],
            "careers_url": r["careers_url"],
            "levels_url": r["levels_url"],
            "aliases": json.loads(r["aliases"]),
            "posting_count": r["posting_count"],
            "open_count": r["open_count"],
        }
        for r in con.execute(
            "SELECT c.*, "
            "  (SELECT COUNT(*) FROM postings p WHERE p.company_id = c.id) AS posting_count, "
            "  (SELECT COUNT(*) FROM postings p WHERE p.company_id = c.id "
            f"     AND {_OPEN_SQL}) AS open_count "
            "FROM companies c ORDER BY c.seq"
        )
    ]


def company_show(con, slug, events_limit=20):
    row = con.execute("SELECT * FROM companies WHERE id=?", (slug,)).fetchone()
    if row is None:
        return None
    counts = con.execute(
        f"SELECT COUNT(*) AS total, SUM({_OPEN_SQL}) AS open FROM postings p "
        "WHERE p.company_id=?",
        (slug,),
    ).fetchone()
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "tier": row["tier"],
        "careers_url": row["careers_url"],
        "levels_url": row["levels_url"],
        "aliases": json.loads(row["aliases"]),
        "notes": row["notes"],
        "posting_count": counts["total"] or 0,
        "open_count": counts["open"] or 0,
        "recent_events": [
            {"at": e["at"], "type": e["type"], "posting_id": e["posting_id"],
             "role_key": e["role_key"], "source": e["source"]}
            for e in con.execute(
                "SELECT * FROM events WHERE company_id=? ORDER BY at DESC, id DESC LIMIT ?",
                (slug, events_limit),
            )
        ],
    }


def state_show(con, db_path=None):
    from . import db as dbmod

    tables = ("sources", "known_ids", "listings", "companies", "stores", "postings",
              "posting_sources", "crosswalk", "events", "applications", "collectors",
              "observed")
    counts = {
        t: con.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables
    }
    by_status = {
        r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) AS n FROM applications GROUP BY status ORDER BY status"
        )
    }
    return {
        "db": db_path,
        "schema_version": dbmod.schema_version(con),
        "counts": counts,
        "applications_by_status": by_status,
        "last_sync": dbmod.get_meta(con, "last_sync"),
        "last_export": dbmod.get_meta(con, "last_export"),
        "last_push": dbmod.get_meta(con, "last_push"),
        "imported_from": dbmod.get_meta(con, "imported_from"),
    }


def overview(con, now=None, window_days=7):
    now = int(now if now is not None else time.time())
    since = now - window_days * 86400
    row = con.execute(
        f"SELECT COUNT(*) AS total, "
        f"  COALESCE(SUM({_OPEN_SQL}), 0) AS open, "
        f"  COALESCE(SUM(CASE WHEN {_OPEN_SQL} AND COALESCE(p.posted_at, p.first_seen) >= ? "
        f"    THEN 1 ELSE 0 END), 0) AS new "
        f"FROM postings p",
        (since,),
    ).fetchone()
    by_status = {
        r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) AS n FROM applications GROUP BY status ORDER BY status")
    }
    return {
        "postings_total": row["total"],
        "postings_open": row["open"],
        "postings_new": row["new"],
        "window_days": window_days,
        "companies": con.execute("SELECT COUNT(*) AS n FROM companies").fetchone()["n"],
        "applications_by_status": by_status,
    }
