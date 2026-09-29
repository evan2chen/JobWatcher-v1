import time

from . import ids

UnknownTarget = ids.UnknownTarget
AmbiguousTarget = ids.AmbiguousTarget

STATUSES = ("interested", "applied", "interviewing", "rejected", "offer", "skipped", "closed")

STATUS_TO_LEGACY = {
    "interested": "new",
    "applied": "applied",
    "interviewing": "interviewing",
    "rejected": "rejected",
    "offer": "offer",
    "skipped": "skip",
    "closed": "closed",
}
LEGACY_TO_STATUS = {
    "applied": "applied",
    "interviewing": "interviewing",
    "rejected": "rejected",
    "offer": "offer",
    "skip": "skipped",
    "closed": "closed",
}

USER_CLOSED_SQL = (
    "EXISTS (SELECT 1 FROM applications a WHERE a.status = 'closed' AND "
    "(a.posting_id = p.posting_id OR a.listing_id IN "
    "(SELECT s.external_id FROM posting_sources s WHERE s.posting_id = p.posting_id)))"
)


def _exact_target(con, ident):
    row = con.execute(
        "SELECT posting_id, company_id FROM postings WHERE posting_id=?", (ident,)
    ).fetchone()
    if row is not None:
        listing = con.execute(
            "SELECT l.id FROM posting_sources ps JOIN listings l ON l.id = ps.external_id "
            "WHERE ps.posting_id=? ORDER BY ps.seq LIMIT 1",
            (ident,),
        ).fetchone()
        return {
            "posting_id": ident,
            "listing_id": listing["id"] if listing else None,
            "company_id": row["company_id"],
        }

    row = con.execute("SELECT id FROM listings WHERE id=?", (ident,)).fetchone()
    if row is not None:
        posting = con.execute(
            "SELECT p.posting_id, p.company_id FROM posting_sources ps "
            "JOIN postings p ON p.posting_id = ps.posting_id "
            "WHERE ps.external_id=? LIMIT 1",
            (ident,),
        ).fetchone()
        return {
            "posting_id": posting["posting_id"] if posting else None,
            "listing_id": ident,
            "company_id": posting["company_id"] if posting else None,
        }

    return None


def resolve(con, ident):
    target = _exact_target(con, ident)
    if target is not None:
        return target

    targets = {}
    for posting_id in ids.prefix_posting_ids(con, ident):
        found = _exact_target(con, posting_id)
        targets[(found["posting_id"], found["listing_id"])] = found
    for listing_id in ids.prefix_listing_ids(con, ident):
        found = _exact_target(con, listing_id)
        targets[(found["posting_id"], found["listing_id"])] = found
    if not targets:
        raise UnknownTarget(f"no posting or listing with id {ident!r}")
    if len(targets) > 1:
        shorten = ids.ShortIds(con).short
        raise AmbiguousTarget(
            f"{ident!r} matches {len(targets)} records",
            [ids.describe(con, t["posting_id"], t["listing_id"], shorten)
             for t in list(targets.values())[:10]])
    return next(iter(targets.values()))


def find(con, target):
    if target.get("posting_id"):
        row = con.execute(
            "SELECT * FROM applications WHERE posting_id=?", (target["posting_id"],)
        ).fetchone()
        if row is not None:
            return row
    if target.get("listing_id"):
        return con.execute(
            "SELECT * FROM applications WHERE listing_id=?", (target["listing_id"],)
        ).fetchone()
    return None


def _row_to_dict(con, row, history=False):
    out = {
        "id": row["id"],
        "posting_id": row["posting_id"],
        "listing_id": row["listing_id"],
        "company_id": row["company_id"],
        "status": row["status"],
        "status_at": row["status_at"],
        "notes": row["notes"],
        "created_at": row["created_at"],
    }
    if history:
        out["history"] = [
            {"at": h["at"], "status": h["status"], "note": h["note"]}
            for h in con.execute(
                "SELECT at, status, note FROM application_history "
                "WHERE application_id=? ORDER BY at, id",
                (row["id"],),
            )
        ]
    return out


def set_status(con, ident, status, note=None, now=None):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    now = int(now if now is not None else time.time())
    target = resolve(con, ident)
    existing = find(con, target)

    if existing is None:
        cur = con.execute(
            "INSERT INTO applications (posting_id, listing_id, company_id, status, "
            "status_at, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (target["posting_id"], target["listing_id"], target["company_id"],
             status, now, note or "", now),
        )
        con.execute(
            "INSERT INTO application_history (application_id, at, status, note) "
            "VALUES (?, ?, ?, ?)",
            (cur.lastrowid, now, status, note),
        )
        con.commit()
        row = con.execute(
            "SELECT * FROM applications WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_dict(con, row, history=True), True

    unchanged = existing["status"] == status and not note
    posting_id = existing["posting_id"] or target["posting_id"]
    listing_id = existing["listing_id"] or target["listing_id"]
    company_id = existing["company_id"] or target["company_id"]
    linked = (posting_id != existing["posting_id"]) or (listing_id != existing["listing_id"])

    if unchanged and not linked:
        return _row_to_dict(con, existing, history=True), False

    notes = existing["notes"]
    if note:
        notes = f"{notes}\n{note}".strip() if notes else note
    con.execute(
        "UPDATE applications SET posting_id=?, listing_id=?, company_id=?, status=?, "
        "status_at=?, notes=? WHERE id=?",
        (posting_id, listing_id, company_id, status,
         now if not unchanged else existing["status_at"], notes, existing["id"]),
    )
    if not unchanged or note:
        con.execute(
            "INSERT INTO application_history (application_id, at, status, note) "
            "VALUES (?, ?, ?, ?)",
            (existing["id"], now, status, note),
        )
    con.commit()
    row = con.execute("SELECT * FROM applications WHERE id=?", (existing["id"],)).fetchone()
    return _row_to_dict(con, row, history=True), True


def append_note(con, ident, text, now=None):
    if not text:
        raise ValueError("note text is required")
    now = int(now if now is not None else time.time())
    target = resolve(con, ident)
    existing = find(con, target)
    if existing is None:
        record, _ = set_status(con, ident, "interested", note=text, now=now)
        return record, True

    notes = f"{existing['notes']}\n{text}".strip() if existing["notes"] else text
    con.execute("UPDATE applications SET notes=? WHERE id=?", (notes, existing["id"]))
    con.execute(
        "INSERT INTO application_history (application_id, at, status, note) "
        "VALUES (?, ?, ?, ?)",
        (existing["id"], now, existing["status"], text),
    )
    con.commit()
    row = con.execute("SELECT * FROM applications WHERE id=?", (existing["id"],)).fetchone()
    return _row_to_dict(con, row, history=True), False


def clear(con, ident):
    target = resolve(con, ident)
    existing = find(con, target)
    if existing is None:
        return False
    con.execute("DELETE FROM application_history WHERE application_id=?",
                (existing["id"],))
    con.execute("DELETE FROM applications WHERE id=?", (existing["id"],))
    con.commit()
    return True


_LIST_SELECT = (
    "SELECT a.*, "
    "  COALESCE(p.title, l.title) AS title, "
    "  COALESCE(c.display_name, l.company_name, a.company_id) AS company, "
    "  COALESCE(p.apply_url, l.url) AS url "
    "FROM applications a "
    "LEFT JOIN postings p ON p.posting_id = a.posting_id "
    "LEFT JOIN listings l ON l.id = a.listing_id "
    "LEFT JOIN companies c ON c.id = a.company_id "
)


def _joined(con, row):
    rec = _row_to_dict(con, row)
    rec.update({"title": row["title"], "company": row["company"], "url": row["url"]})
    return rec


def get(con, application_id):
    row = con.execute(_LIST_SELECT + "WHERE a.id = ?", (application_id,)).fetchone()
    return _joined(con, row) if row is not None else None


def list_applications(con, status=None, company=None, since=None, limit=None):
    sql = [_LIST_SELECT]
    where, params = [], []
    if status:
        where.append("a.status = ?")
        params.append(status)
    if company:
        where.append("(a.company_id = ? OR LOWER(COALESCE(c.display_name, l.company_name, '')) "
                     "LIKE ?)")
        params.extend([company, f"%{company.lower()}%"])
    if since:
        where.append("a.status_at >= ?")
        params.append(int(since))
    if where:
        sql.append("WHERE " + " AND ".join(where) + " ")
    sql.append("ORDER BY a.status_at DESC, a.id DESC")
    if limit:
        sql.append(" LIMIT ?")
        params.append(int(limit))

    return [_joined(con, row) for row in con.execute("".join(sql), params)]


def legacy_status_map(con):
    return {
        r["listing_id"]: (STATUS_TO_LEGACY[r["status"]], r["status_at"], r["notes"])
        for r in con.execute(
            "SELECT listing_id, status, status_at, notes FROM applications "
            "WHERE listing_id IS NOT NULL"
        )
        if r["status"] in STATUS_TO_LEGACY
    }
