import bisect

from . import toon

MIN_PREFIX = 4
SHORT_LENGTH = 8
KEEP_WHOLE = 12


class UnknownTarget(LookupError):
    pass


class AmbiguousTarget(LookupError):
    def __init__(self, message, candidates):
        super().__init__(message)
        self.candidates = candidates


def _range_query(con, table, column, prefix, select):
    return con.execute(
        f"SELECT {select} FROM {table} WHERE {column} >= ? AND {column} < ?",
        (prefix, prefix + "\U0010ffff"),
    ).fetchall()


def prefix_posting_ids(con, prefix):
    if len(prefix) < MIN_PREFIX:
        return []
    return [r["posting_id"] for r in
            _range_query(con, "postings", "posting_id", prefix, "posting_id")]


def prefix_listing_ids(con, prefix):
    if len(prefix) < MIN_PREFIX:
        return []
    return [r["id"] for r in _range_query(con, "listings", "id", prefix, "id")]


def describe(con, posting_id=None, listing_id=None, shorten=None):
    row = _describe(con, posting_id, listing_id)
    if shorten is not None:
        row["id"] = shorten(row["id"])
    return row


def _describe(con, posting_id, listing_id):
    if posting_id:
        row = con.execute(
            "SELECT c.display_name AS company, p.title AS title, p.company_id AS company_id "
            "FROM postings p LEFT JOIN companies c ON c.id = p.company_id "
            "WHERE p.posting_id=?", (posting_id,)).fetchone()
        if row is not None:
            return {"id": posting_id, "company": row["company"] or row["company_id"],
                    "title": row["title"]}
    if listing_id:
        row = con.execute(
            "SELECT company_name, title FROM listings WHERE id=?", (listing_id,)).fetchone()
        if row is not None:
            return {"id": listing_id, "company": row["company_name"], "title": row["title"]}
    return {"id": posting_id or listing_id, "company": None, "title": None}


def expand_posting(con, ident):
    exact = con.execute("SELECT posting_id FROM postings WHERE posting_id=?",
                        (ident,)).fetchone()
    if exact is not None:
        return ident
    matches = prefix_posting_ids(con, ident)
    if not matches:
        raise UnknownTarget(f"no posting with id {ident!r}")
    if len(matches) > 1:
        shorten = ShortIds(con).short
        raise AmbiguousTarget(
            f"{ident!r} matches {len(matches)} postings",
            [describe(con, posting_id=m, shorten=shorten) for m in matches[:10]])
    return matches[0]


class ShortIds:
    def __init__(self, con):
        ids = [r["posting_id"] for r in con.execute("SELECT posting_id FROM postings")]
        ids += [r["id"] for r in con.execute("SELECT id FROM listings")]
        self._sorted = sorted(set(ids))

    def short(self, full_id):
        if not full_id or len(full_id) <= KEEP_WHOLE:
            return full_id
        index = bisect.bisect_left(self._sorted, full_id)
        neighbours = [
            self._sorted[i] for i in (index - 1, index, index + 1)
            if 0 <= i < len(self._sorted) and self._sorted[i] != full_id
        ]
        length = min(SHORT_LENGTH, len(full_id))
        while length < len(full_id) and (
            toon.needs_quotes(full_id[:length])
            or any(n.startswith(full_id[:length]) for n in neighbours)
        ):
            length += 1
        return full_id[:length]
