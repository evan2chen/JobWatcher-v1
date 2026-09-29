#!/usr/bin/env python3
"""Source-agnostic reconciler for the company posting tracker.

Standard-library only (runs in the routine VM).

The design is three layers (see docs/data-model.md):

  * **Canonical**  — Companies, Roles (derived), Postings. Source-independent.
  * **Crosswalk**  — (source, external_id) and natural-key -> posting_id.
  * **History**    — append-only lifecycle *transition* events (events.jsonl).

Any source feeds the reconciler the *same* normalized ``Observation`` dict; the
reconciler resolves it to a canonical company -> posting, merges lifecycle, and
emits transition events. Adding a new job board means writing one adapter that
emits Observations — nothing in here changes.

Lifecycle rules (per product decisions):
  * A posting closes **only** when a source reports it inactive/not-visible.
    Merely disappearing from a feed does NOT close it — ``last_seen`` freezes.
  * A brand-new source id is a **new posting** (its own ``opened`` event) under
    the same role. ``reopened`` fires only when the *same* posting goes active
    again after a flagged close.
"""

import json
import os
import uuid

from .normalize import (
    canonical_category,
    canonical_terms,
    natural_key,
    normalize_company,
    primary_location,
    role_key,
)

# --- company resolution ----------------------------------------------------

WILDCARD = "*"


def build_alias_index(companies):
    """Build lookup tables from companies.json entries.

    ``aliases`` may be a plain list (treated as wildcard, i.e. any source) or a
    dict of ``{source_or_"*": [alias, ...]}``. Returns (exact, loose):
      * exact[(scope, alias_lower)] = company_id     — exact case-insensitive
      * loose[(scope, normalized_company)] = company_id — suffix-stripped fallback
    """
    exact, loose = {}, {}
    for c in companies:
        cid = c.get("id")
        if not cid:
            continue
        aliases = c.get("aliases") or []
        if isinstance(aliases, list):
            aliases = {WILDCARD: aliases}
        for scope, names in aliases.items():
            for name in names or []:
                key = str(name).strip().lower()
                if not key:
                    continue
                exact.setdefault((scope, key), cid)
                nk = normalize_company(name)
                if nk:
                    loose.setdefault((scope, nk), cid)
    return exact, loose


def resolve_company(company_raw, source, alias_index):
    """Resolve a raw company string to a canonical company_id, or None.

    Tries source-scoped then wildcard, exact match first (like ``matches_watchlist``
    in run.py), then a suffix-stripped loose match as a fallback.
    """
    exact, loose = alias_index
    name = (company_raw or "").strip().lower()
    for scope in (source, WILDCARD):
        cid = exact.get((scope, name))
        if cid:
            return cid
    nk = normalize_company(company_raw)
    for scope in (source, WILDCARD):
        cid = loose.get((scope, nk))
        if cid:
            return cid
    return None


# --- observation helpers ---------------------------------------------------

def _obs_active(obs):
    """A source considers a posting live unless it flags active/visible false."""
    sr = obs.get("state_raw") or {}
    active = sr.get("active", True)
    visible = sr.get("is_visible", True)
    return bool(active) and bool(visible)


def _ext_key(source, external_id):
    return f"{source}|{external_id}"


# The material fields whose change on an active observation emits an "updated" event.
_MATERIAL = ("title", "terms", "locations", "apply_url")


# --- in-memory state -------------------------------------------------------

def new_state():
    return {
        "postings": {},                          # posting_id -> posting dict
        "crosswalk": {"external": {}, "natural": {}},
        "events": [],                            # events emitted this run (to flush)
        "dirty": False,
    }


def _canonical_state(posting):
    for entry in posting["sources"].values():
        if entry.get("state") == "active":
            return "open"
    return "closed"


def _emit(state, posting, etype, at, source, detail=None):
    ev = {
        "at": at,
        "posting_id": posting["posting_id"],
        "role_key": posting["role_key"],
        "type": etype,
        "source": source,
    }
    if detail:
        ev["detail"] = detail
    state["events"].append(ev)
    state["dirty"] = True


def apply_observation(state, obs, company, now_ts, mint_id=None):
    """Reconcile a single Observation into ``state`` (in place)."""
    mint_id = mint_id or (lambda: str(uuid.uuid4()))
    cid = company["id"]
    source = obs["source"]
    external_id = obs.get("external_id")
    level = obs.get("level")
    title = obs.get("title_raw")
    terms = canonical_terms(obs.get("terms"), level)
    locations = list(obs.get("locations") or [])
    url = obs.get("url")
    active = _obs_active(obs)
    src_state = "active" if active else "closed"

    xw = state["crosswalk"]
    nk = natural_key(cid, level, title, obs.get("terms"), locations, url)

    pid = None
    if external_id is not None:
        pid = xw["external"].get(_ext_key(source, external_id))
    if pid is None:
        pid = xw["natural"].get(nk)

    src_entry = {
        "external_id": external_id,
        "url": url,
        "state": src_state,
        "first_seen": now_ts,
        "last_seen": now_ts,
    }

    if pid is None or pid not in state["postings"]:
        # --- new posting -----------------------------------------------------
        pid = mint_id()
        posting = {
            "posting_id": pid,
            "company_id": cid,
            "role_key": role_key(cid, level, title),
            "level": level,
            "title": title,
            "terms": terms,
            "locations": locations,
            "apply_url": url,
            "posted_at": obs.get("posted_at"),
            "first_seen": now_ts,
            "last_seen": now_ts,
            "closed_at": None,
            "state": "open" if active else "closed",
            "pay": None,
            "sources": {source: src_entry},
            "attributes": dict(obs.get("extra") or {}),
        }
        state["postings"][pid] = posting
        if external_id is not None:
            xw["external"][_ext_key(source, external_id)] = pid
        xw["natural"][nk] = pid
        # "opened" reflects the real post time when known.
        _emit(state, posting, "opened", posting.get("posted_at") or now_ts, source)
        if not active:
            posting["closed_at"] = now_ts
            _emit(state, posting, "closed", now_ts, source)
        return pid

    # --- existing posting ----------------------------------------------------
    posting = state["postings"][pid]
    prev_state = posting["state"]
    posting["last_seen"] = now_ts
    state["dirty"] = True

    entry = posting["sources"].get(source)
    if entry is None:
        posting["sources"][source] = src_entry
    else:
        entry["last_seen"] = now_ts
        entry["state"] = src_state
        entry["url"] = url
        entry["external_id"] = external_id

    # Keep crosswalk fresh (cheap; lets a later source match this posting).
    if external_id is not None:
        xw["external"][_ext_key(source, external_id)] = pid
    xw["natural"][nk] = pid

    # Display fields track the most recent *active* observation (recency wins);
    # a stale/inactive observation never rewrites the display.
    if active:
        changed = []
        candidate = {
            "title": title,
            "terms": terms,
            "locations": locations,
            "apply_url": url,
        }
        for field in _MATERIAL:
            if posting.get(field) != candidate[field]:
                changed.append(field)
        if changed:
            detail = {"changed": changed,
                      "from": {f: posting.get(f) for f in changed},
                      "to": {f: candidate[f] for f in changed}}
            for f in changed:
                posting[f] = candidate[f]
            posting["role_key"] = role_key(cid, level, posting["title"])
            _emit(state, posting, "updated", now_ts, source, detail)

    new_state_val = _canonical_state(posting)
    posting["state"] = new_state_val
    if prev_state != new_state_val:
        if new_state_val == "closed":
            posting["closed_at"] = now_ts
            _emit(state, posting, "closed", now_ts, source)
        else:
            posting["closed_at"] = None
            _emit(state, posting, "reopened", now_ts, source)
    return pid


def reconcile_company(state, observations, company, now_ts, mint_id=None):
    """Apply all of a company's observations for this run. Returns event count."""
    before = len(state["events"])
    for obs in observations:
        apply_observation(state, obs, company, now_ts, mint_id)
    return len(state["events"]) - before


# --- disk IO ---------------------------------------------------------------

def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _write_json_compact(path, data):
    """Whitespace-free JSON, for large generated artifacts nobody reads by hand."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, separators=(",", ":"), ensure_ascii=False)
        fh.write("\n")


def load_state(company_dir):
    state = new_state()
    postings = _read_json(os.path.join(company_dir, "postings.json"), {})
    for p in (postings.get("postings") if isinstance(postings, dict) else postings) or []:
        state["postings"][p["posting_id"]] = p
    xw = _read_json(os.path.join(company_dir, "crosswalk.json"),
                    {"external": {}, "natural": {}})
    state["crosswalk"]["external"] = xw.get("external", {})
    state["crosswalk"]["natural"] = xw.get("natural", {})
    return state


def save_state(company_dir, company, state):
    postings = sorted(
        state["postings"].values(),
        key=lambda p: (-(p.get("posted_at") or 0), p["posting_id"]),
    )
    _write_json(os.path.join(company_dir, "postings.json"),
                {"company_id": company["id"], "postings": postings})
    _write_json(os.path.join(company_dir, "crosswalk.json"), state["crosswalk"])
    if state["events"]:
        os.makedirs(company_dir, exist_ok=True)
        with open(os.path.join(company_dir, "events.jsonl"), "a", encoding="utf-8") as fh:
            for ev in state["events"]:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _company_dir(tracker_dir, cid):
    return os.path.join(tracker_dir, "companies", cid)


def build_index(tracker_dir, companies, now_ts):
    """Rebuild tracker/index.json — the UI landing manifest."""
    entries = []
    for c in companies:
        cid = c["id"]
        postings = _read_json(
            os.path.join(_company_dir(tracker_dir, cid), "postings.json"), {})
        plist = postings.get("postings", []) if isinstance(postings, dict) else []
        open_count = sum(1 for p in plist if p.get("state") == "open")
        last_updated = max((p.get("last_seen") or 0 for p in plist), default=0)
        entries.append({
            "slug": cid,
            "display_name": c.get("display_name") or cid,
            "tier": c.get("tier"),
            "careers_url": c.get("careers_url"),
            "levels_url": c.get("levels_url"),
            "posting_count": len(plist),
            "open_count": open_count,
            "last_updated": last_updated,
        })
    _write_json(os.path.join(tracker_dir, "index.json"),
                {"generated_at": now_ts, "companies": entries})


# The aggregate's field names are abbreviated on purpose: the browser fetches the
# whole corpus on every cold load, and ~2.8k records of long key names is most of
# the payload. The decoder that mirrors this map lives in web/src/lib/data.ts —
# change one and you must change the other.
def _slim(posting, cid):
    attrs = posting.get("attributes") or {}
    return {
        "id": posting.get("posting_id"),
        "co": posting.get("company_id") or cid,
        "rk": posting.get("role_key"),
        "lvl": posting.get("level"),
        "t": posting.get("title"),
        "tm": posting.get("terms") or [],
        "loc": posting.get("locations") or [],
        "u": posting.get("apply_url"),
        "pa": posting.get("posted_at"),
        "fs": posting.get("first_seen"),
        "ls": posting.get("last_seen"),
        "ca": posting.get("closed_at"),
        "s": posting.get("state"),
        "cat": canonical_category(attrs.get("category")),
        "sp": attrs.get("sponsorship"),
        "deg": attrs.get("degrees") or [],
    }


def build_all_postings(tracker_dir, companies, now_ts):
    """Write tracker/all_postings.json — the whole corpus in one slim file.

    The Pages catalog needs every posting at once; the alternative is 100 per-company
    fetches on every cold load. Deliberately *derived*: rebuilt from the per-company
    stores on every run, so unlike the rest of tracker/ it never needs restoring from
    the data branch — a missing file self-heals on the next run. ``sources`` and the
    crosswalk are dropped; the UI has no use for them and they are the bulk of the size.
    """
    out = []
    for c in companies:
        cid = c["id"]
        postings = _read_json(
            os.path.join(_company_dir(tracker_dir, cid), "postings.json"), {})
        plist = postings.get("postings", []) if isinstance(postings, dict) else []
        out.extend(_slim(p, cid) for p in plist)
    # Newest first, posting_id as the tiebreak so the file is byte-stable run to run.
    out.sort(key=lambda r: (-(r["pa"] or 0), r["id"] or ""))
    _write_json_compact(
        os.path.join(tracker_dir, "all_postings.json"),
        {"generated_at": now_ts, "count": len(out), "postings": out})
    return out


# --- top-level entry point -------------------------------------------------

def reconcile(observations, companies, tracker_dir, now_ts,
              warn_on_zero=False, log=None, mint_id=None):
    """Reconcile a batch of Observations from one or more sources.

    ``observations`` is a flat iterable of Observation dicts (any source).
    ``companies`` is the parsed companies.json list. Writes per-company stores
    under ``tracker_dir`` and rebuilds the index. Returns a summary dict.
    """
    log = log or (lambda m: None)
    alias_index = build_alias_index(companies)

    by_company = {}
    sources_this_run = set()
    unresolved = 0
    for obs in observations:
        sources_this_run.add(obs.get("source"))
        cid = resolve_company(obs.get("company_raw"), obs.get("source"), alias_index)
        if cid is None:
            unresolved += 1
            continue
        by_company.setdefault(cid, []).append(obs)

    companies_by_id = {c["id"]: c for c in companies if c.get("id")}
    touched = 0
    total_events = 0
    for cid, company in companies_by_id.items():
        obs_list = by_company.get(cid, [])
        cdir = _company_dir(tracker_dir, cid)
        had_store = os.path.exists(os.path.join(cdir, "postings.json"))
        if not obs_list and not had_store:
            continue
        state = load_state(cdir)
        if obs_list:
            events = reconcile_company(state, obs_list, company, now_ts, mint_id)
            total_events += events
            if state["dirty"]:
                save_state(cdir, company, state)
                touched += 1
        else:
            # Company known but matched nothing this run. Disappearance never
            # closes anything; just optionally flag possible alias drift.
            if warn_on_zero and any(p.get("state") == "open"
                                    for p in state["postings"].values()):
                log(f"tracker: '{cid}' matched 0 listings this run "
                    f"(possible alias drift?)")

    build_index(tracker_dir, companies, now_ts)
    corpus = build_all_postings(tracker_dir, companies, now_ts)
    summary = {
        "matched_companies": len([c for c in by_company]),
        "unresolved_observations": unresolved,
        "companies_touched": touched,
        "events": total_events,
        "postings_total": len(corpus),
        "sources": sorted(s for s in sources_this_run if s),
    }
    log(f"tracker: {summary['matched_companies']} companies matched, "
        f"{touched} updated, {total_events} lifecycle event(s), "
        f"{unresolved} unresolved observation(s), "
        f"{len(corpus)} posting(s) in the catalog aggregate")
    return summary
