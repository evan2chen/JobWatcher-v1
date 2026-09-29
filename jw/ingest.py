import collections
import hashlib
import json
import time

from . import filters, importer, normalize, reconcile, schema, tracker_store
from .digest import normalize_category

MAX_ERRORS_SHOWN = 10
UNRESOLVED_SHOWN = 10
DEFAULT_CONFIG = {"filters": {}, "track_all": False, "seed_hours": 25, "baseline": False}


class Batch:
    def __init__(self):
        self.observations = []
        self.errors = []
        self.lines = 0

    @property
    def rejected(self):
        return len({e["line"] for e in self.errors})


def parse_batch(text, source=None, now=None):
    now = int(now if now is not None else time.time())
    batch = Batch()
    for number, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        batch.lines += 1
        try:
            obs = json.loads(raw)
        except ValueError as exc:
            batch.errors.append({"line": number, "error": f"not valid JSON ({exc})"})
            continue
        problems = schema.validate(obs) if isinstance(obs, dict) else [
            "observation: must be object, got " + type(obs).__name__]
        if not problems and source is not None and obs["source"] != source:
            problems = [f"source: must be {source!r} for this collector, got {obs['source']!r}"]
        if problems:
            batch.errors.extend({"line": number, "error": p} for p in problems)
            continue
        batch.observations.append(schema.normalize(obs, now))
    return batch


def _companies(con):
    return [
        {"id": r["id"], "display_name": r["display_name"], "aliases": json.loads(r["aliases"])}
        for r in con.execute("SELECT id, display_name, aliases FROM companies ORDER BY seq")
    ]


def _register_alias(index, company_id, name):
    exact, loose = index
    exact.setdefault((reconcile.WILDCARD, name.strip().lower()), company_id)
    key = normalize.normalize_company(name)
    if key:
        loose.setdefault((reconcile.WILDCARD, key), company_id)


def _new_slug(name, taken):
    base = normalize.slugify(normalize.normalize_company(name)) or normalize.slugify(name)
    if not base:
        base = "company-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    slug, suffix = base, 2
    while slug in taken:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _resolve(con, observations, config_for):
    companies = _companies(con)
    taken = {c["id"] for c in companies}
    index = reconcile.build_alias_index(companies)
    by_company = collections.OrderedDict()
    unresolved = collections.Counter()
    created = []
    next_seq = con.execute("SELECT COALESCE(MAX(seq) + 1, 0) AS n FROM companies").fetchone()["n"]

    for obs in observations:
        company_id = reconcile.resolve_company(obs["company_raw"], obs["source"], index)
        if company_id is None and config_for(obs["source"]).get("track_all"):
            name = obs["company_raw"].strip()
            company_id = _new_slug(name, taken)
            record = {"id": company_id, "display_name": name, "tier": None,
                      "careers_url": None, "levels_url": None,
                      "aliases": {"*": [name]}, "notes": ""}
            con.execute(importer.COMPANY_INSERT, importer.company_row(next_seq, record))
            next_seq += 1
            taken.add(company_id)
            _register_alias(index, company_id, name)
            created.append(record)
        if company_id is None:
            unresolved[obs["company_raw"]] += 1
            continue
        by_company.setdefault(company_id, []).append(obs)
    return by_company, unresolved, created


def _reconcile(con, by_company, now):
    events = collections.Counter()
    for company_id, obs_list in by_company.items():
        state = tracker_store.load_state(con, company_id)
        reconcile.reconcile_company(state, obs_list, {"id": company_id}, now)
        events.update(e["type"] for e in state["events"])
        if state["dirty"]:
            tracker_store.save_state(con, company_id, state)
    return events


def _chunks(items, size=500):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _namespaces(con):
    return {r["name"]: r["id_namespace"] or r["name"]
            for r in con.execute("SELECT name, id_namespace FROM collectors")}


def _conflicts(con, source, new_ids, namespaces):
    mine = namespaces.get(source, source)
    found = {}
    for chunk in _chunks(new_ids):
        marks = ",".join("?" * len(chunk))
        for row in con.execute(
            f"SELECT external_id, source FROM observed WHERE source != ? "
            f"AND external_id IN ({marks})", [source, *chunk]
        ):
            if namespaces.get(row["source"], row["source"]) != mine:
                found[row["external_id"]] = row["source"]
    return found


def _listing_entry(obs, now):
    return {
        "id": obs["external_id"],
        "source_repo": obs["source"],
        "company_name": obs["company_raw"],
        "title": obs["title_raw"],
        "category": normalize_category((obs.get("extra") or {}).get("category")),
        "locations": obs.get("locations") or [],
        "url": obs.get("url"),
        "date_posted": obs.get("posted_at"),
        "date_first_seen": now,
        "status": "new",
        "status_updated": None,
        "notes": "",
    }


def _screen(con, observations):
    known = {}
    for source in {o["source"] for o in observations}:
        known[source] = {r["external_id"] for r in con.execute(
            "SELECT external_id FROM observed WHERE source=?", (source,))}
    fresh, seen_in_batch = [], set()
    for obs in observations:
        key = (obs["source"], obs["external_id"])
        if obs["external_id"] in known[obs["source"]] or key in seen_in_batch:
            continue
        seen_in_batch.add(key)
        fresh.append(obs)

    collisions, rejected = [], set()
    namespaces = _namespaces(con)
    for source in known:
        ids = [o["external_id"] for o in fresh if o["source"] == source]
        for external_id, other in _conflicts(con, source, ids, namespaces).items():
            collisions.append({
                "external_id": external_id,
                "error": f"already used by source {other!r}; prefix ids with the source "
                         "name, or give both sources one --id-namespace if they list the same jobs",
            })
            rejected.add((source, external_id))
    return fresh, rejected, collisions


def _surface(con, fresh, config_for, watchlist, now):
    surfaced = []
    listed = set()
    for chunk in _chunks([o["external_id"] for o in fresh]):
        marks = ",".join("?" * len(chunk))
        listed.update(r["id"] for r in con.execute(
            f"SELECT id FROM listings WHERE id IN ({marks})", chunk))

    for obs in fresh:
        config = config_for(obs["source"])
        if obs["external_id"] in listed:
            continue
        if config.get("baseline"):
            cutoff = now - int(config.get("seed_hours", 25)) * 3600
            if (obs.get("posted_at") or 0) < cutoff:
                continue
        if filters.surfaces(obs, config.get("filters") or {}, watchlist):
            surfaced.append(_listing_entry(obs, now))

    seq = con.execute("SELECT COALESCE(MAX(seq) + 1, 0) AS n FROM listings").fetchone()["n"]
    con.executemany(
        "INSERT INTO listings (id, seq, source_repo, company_name, title, category, "
        "locations, url, date_posted, date_first_seen, status, status_updated, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (e["id"], seq + i, e["source_repo"], e["company_name"], e["title"], e["category"],
             json.dumps(e["locations"], ensure_ascii=False), e["url"], e["date_posted"],
             e["date_first_seen"], e["status"], e["status_updated"], e["notes"])
            for i, e in enumerate(surfaced)
        ],
    )
    return surfaced


def _record_observed(con, fresh, rejected):
    seq = con.execute("SELECT COALESCE(MAX(seq) + 1, 0) AS n FROM observed").fetchone()["n"]
    rows = [(o["source"], o["external_id"]) for o in fresh
            if (o["source"], o["external_id"]) not in rejected]
    con.executemany(
        "INSERT INTO observed (source, external_id, seq) VALUES (?, ?, ?)",
        [(s, e, seq + i) for i, (s, e) in enumerate(rows)],
    )
    return len(rows)


def apply(con, observations, config_for, watchlist=(), now=None, track_tracker=True):
    now = int(now if now is not None else time.time())
    fresh, rejected, collisions = _screen(con, observations)
    accepted = [o for o in observations if (o["source"], o["external_id"]) not in rejected]

    if track_tracker:
        by_company, unresolved, created = _resolve(con, accepted, config_for)
        events = _reconcile(con, by_company, now)
    else:
        by_company, unresolved, created, events = {}, collections.Counter(), [], collections.Counter()

    surfaced = _surface(con, [o for o in fresh if (o["source"], o["external_id"]) not in rejected],
                        config_for, list(watchlist), now)
    new_ids = _record_observed(con, fresh, rejected)

    return {
        "observations": len(accepted),
        "new_observed": new_ids,
        "opened": events.get("opened", 0),
        "updated": events.get("updated", 0),
        "closed": events.get("closed", 0),
        "reopened": events.get("reopened", 0),
        "companies_touched": len(by_company),
        "created_companies": created,
        "unresolved": sum(unresolved.values()),
        "unresolved_distinct": len(unresolved),
        "unresolved_top": [{"name": n, "observations": c}
                           for n, c in unresolved.most_common(UNRESOLVED_SHOWN)],
        "surfaced": surfaced,
        "collisions": collisions,
    }
