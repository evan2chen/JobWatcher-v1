from . import exporter, importer, reconcile


def load_state(con, company_id):
    state = reconcile.new_state()
    for posting in exporter.postings_document(con, company_id)["postings"]:
        state["postings"][posting["posting_id"]] = posting
    crosswalk = exporter.crosswalk_document(con, company_id)
    state["crosswalk"]["external"] = crosswalk["external"]
    state["crosswalk"]["natural"] = crosswalk["natural"]
    return state


def save_state(con, company_id, state):
    postings = sorted(
        state["postings"].values(),
        key=lambda p: (-(p.get("posted_at") or 0), p["posting_id"]),
    )
    con.execute("DELETE FROM postings WHERE company_id=?", (company_id,))
    con.execute("DELETE FROM crosswalk WHERE company_id=?", (company_id,))
    importer.insert_postings(con, company_id, postings)
    importer.insert_crosswalk(con, company_id, state["crosswalk"])

    next_seq = con.execute(
        "SELECT COALESCE(MAX(seq) + 1, 0) AS n FROM events WHERE company_id=?",
        (company_id,),
    ).fetchone()["n"]
    importer.insert_events(con, company_id, state["events"], start_seq=next_seq)

    has_events = con.execute(
        "SELECT 1 FROM events WHERE company_id=? LIMIT 1", (company_id,)
    ).fetchone() is not None
    con.execute(
        "INSERT INTO stores (company_id, has_postings, has_crosswalk, has_events) "
        "VALUES (?, 1, 1, ?) ON CONFLICT(company_id) DO UPDATE SET "
        "has_postings=1, has_crosswalk=1, has_events=MAX(has_events, excluded.has_events)",
        (company_id, int(has_events)),
    )
