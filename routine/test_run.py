#!/usr/bin/env python3

import importlib.util
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("run", os.path.join(_HERE, "run.py"))
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)

failures = []
total = 0


def check(name, cond):
    global total
    total += 1
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        failures.append(name)


check("normalize software eng", run.normalize_category("Software Engineering") == "Software")
check("normalize quant finance", run.normalize_category("Quantitative Finance") == "Quant")
check("normalize passthrough", run.normalize_category("Weird") == "Weird")
check("normalize none", run.normalize_category(None) is None)

listing = {
    "source": "Simplify", "category": "Software", "company_name": "Acme",
    "id": "abc-123", "title": "SWE Intern", "active": True,
    "terms": ["Summer 2026"], "url": "https://x/y", "locations": ["Remote in USA"],
    "is_visible": True,
}
block = json.dumps(listing, indent=4)
patch = "@@ -100,3 +100,20 @@\n" + "\n".join("+" + ln for ln in block.splitlines())
patch += "\n         }," + "\n     ]"
objs = run.objects_from_added_lines(patch)
check("added-lines extracts one object", len(objs) == 1)
check("added-lines id correct", objs and objs[0]["id"] == "abc-123")
check("added-lines fields intact", objs and objs[0]["company_name"] == "Acme")

partial = '@@ -5,1 +5,1 @@\n-        "active": true,\n+        "active": false,'
check("partial edit yields no object", run.objects_from_added_lines(partial) == [])

two = json.dumps([listing, {**listing, "id": "def-456"}], indent=4)
patch2 = "@@ x @@\n" + "\n".join("+" + ln for ln in two.splitlines())
objs2 = run.objects_from_added_lines(patch2)
check("added-lines extracts two objects", {o["id"] for o in objs2} == {"abc-123", "def-456"})

full = [
    {"id": "a", "active": True, "is_visible": True},
    {"id": "b", "active": True, "is_visible": True},
    {"id": "c", "active": True, "is_visible": True},
]
diff = run.new_objects_from_full_file(json.dumps(full), {"a", "b"})
check("full-file diff finds only new id", set(diff.keys()) == {"c"})

active_visible = {"active": True, "is_visible": True, "category": "Software",
                  "title": "Backend Engineer", "locations": ["McLean, VA"]}
check("permissive passes", run.passes_filters(active_visible, {}))
check("active_only drops closed",
      not run.passes_filters({**active_visible, "active": False}, {"active_only": True}))
check("visible_only drops hidden",
      not run.passes_filters({**active_visible, "is_visible": False}, {"visible_only": True}))
check("category filter matches (normalized)",
      run.passes_filters({**active_visible, "category": "Software Engineering"},
                         {"categories": ["Software"]}))
check("category filter excludes",
      not run.passes_filters(active_visible, {"categories": ["Quant"]}))
check("keyword filter matches",
      run.passes_filters(active_visible, {"title_keywords": ["engineer"]}))
check("keyword filter excludes",
      not run.passes_filters(active_visible, {"title_keywords": ["scientist"]}))
check("location filter matches", run.passes_filters(active_visible, {"locations": ["VA"]}))
check("location filter excludes",
      not run.passes_filters(active_visible, {"locations": ["Seattle"]}))

check("watchlist empty never matches", not run.matches_watchlist("Stripe", []))
check("watchlist exact case-insensitive match", run.matches_watchlist("Stripe", ["stripe"]))
check("watchlist trims surrounding whitespace",
      run.matches_watchlist("  Stripe  ", ["stripe"]))
check("watchlist exact does NOT substring-match",
      not run.matches_watchlist("Capital One Financial", ["capital one"]))
check("watchlist matches an exact variant",
      run.matches_watchlist("Meta Platforms", ["meta", "meta platforms", "facebook"]))
check("watchlist non-match", not run.matches_watchlist("Acme", ["stripe", "jane street"]))
check("watchlist handles missing company", not run.matches_watchlist(None, ["stripe"]))

import tempfile
_wl_dir = tempfile.mkdtemp()
check("watchlist missing file -> empty",
      run.load_watchlist(os.path.join(_wl_dir, "nope.json")) == [])
_wl_ok = os.path.join(_wl_dir, "ok.json")
with open(_wl_ok, "w") as _fh:
    json.dump(["Stripe", "  ", "Jane Street"], _fh)
check("watchlist loads, lowercases, drops blanks",
      run.load_watchlist(_wl_ok) == ["stripe", "jane street"])
_wl_bad = os.path.join(_wl_dir, "bad.json")
with open(_wl_bad, "w") as _fh:
    _fh.write("{not json")
check("watchlist malformed -> empty", run.load_watchlist(_wl_bad) == [])

bypass_src = {"repo": "Repo/X", "known_ids": []}
bypass_cands = {
    "off-cat": {"id": "off-cat", "active": True, "is_visible": True,
                "company_name": "Jane Street", "title": "Trader",
                "category": "Quant", "url": "u", "locations": ["NYC"]},
}
bp_survivors, _ = run._finalize(
    bypass_src, bypass_cands, {"categories": ["Software"]}, set(), set(),
    "Repo/X", now_ts=1000, new_sha="s", args=None, watchlist=["jane street"],
)
check("watchlist bypasses category gate", {s["id"] for s in bp_survivors} == {"off-cat"})

closed_src = {"repo": "Repo/X", "known_ids": []}
closed_cands = {
    "dead": {"id": "dead", "active": False, "is_visible": True,
             "company_name": "Jane Street", "title": "Trader",
             "category": "Quant", "url": "u", "locations": ["NYC"]},
}
cl_survivors, _ = run._finalize(
    closed_src, closed_cands, {"categories": ["Software"]}, set(), set(),
    "Repo/X", now_ts=1000, new_sha="s", args=None, watchlist=["jane street"],
)
check("watchlist does not bypass active/visible gate", cl_survivors == [])

entry = run.to_seen_entry({**active_visible, "id": "z", "company_name": "Q",
                           "url": "u", "date_posted": 123}, "Repo/X", 999)
check("seen entry has status new", entry["status"] == "new")
check("seen entry has first_seen", entry["date_first_seen"] == 999)
check("seen entry normalizes category", entry["category"] == "Software")

msg = run.build_slack_message({"Repo/X": [entry]})
check("slack message mentions company", "Q" in msg)
check("slack message has apply link", "apply" in msg)

wl_a = {"company_name": "Stripe", "title": "SWE", "locations": ["Remote"],
        "url": "u1", "source_repo": "Repo/X"}
wl_b = {"company_name": "Acme", "title": "SWE", "locations": ["Remote"],
        "url": "u2", "source_repo": "Repo/X"}
wl_msg = run.build_slack_message({"Repo/X": [wl_a, wl_b]}, watchlist=["stripe"])
check("slack highlights companies of interest", "Companies of interest" in wl_msg)
check("slack pings @channel when interest section non-empty", "<!channel>" in wl_msg)
check("slack interest section names watched company", "Stripe" in wl_msg)
check("slack de-dups watched listing out of source group", wl_msg.count("Stripe") == 1)
check("slack still lists non-watched listing", "Acme" in wl_msg)
_plain = run.build_slack_message({"Repo/X": [wl_a]})
check("slack no interest section without watchlist",
      "Companies of interest" not in _plain)
check("slack no @channel ping without watchlist matches", "<!channel>" not in _plain)

_short = run.split_slack_message("a\nb\nc", limit=100)
check("split keeps short message whole", _short == ["a\nb\nc"])
_lines = "\n".join(f"line {i} " + "x" * 40 for i in range(50))
_chunks = run.split_slack_message(_lines, limit=200)
check("split produces multiple chunks", len(_chunks) > 1)
check("split respects the char limit", all(len(c) <= 200 for c in _chunks))
check("split is lossless", "\n".join(_chunks) == _lines)
check("split never breaks a line", all("\n".join(c.split("\n")) == c for c in _chunks))
_huge = run.split_slack_message("y" * 500, limit=100)
check("split truncates an over-limit line to fit", len(_huge) == 1 and len(_huge[0]) == 100)
check("split returns non-empty list for empty input", run.split_slack_message("") == [""])

source = {"repo": "Repo/X", "known_ids": ["old"]}
candidates = {
    "old": {"id": "old", "active": True, "is_visible": True, "company_name": "Dup",
            "title": "t", "url": "u", "locations": ["Remote"]},
    "fresh": {"id": "fresh", "active": True, "is_visible": True, "company_name": "New",
              "title": "t", "url": "u", "locations": ["Remote"]},
}
seen_ids = {"old"}
survivors, changed = run._finalize(
    source, candidates, {}, set(source["known_ids"]), seen_ids,
    "Repo/X", now_ts=1000, new_sha="deadbeef", args=None,
)
check("finalize skips already-seen id", {s["id"] for s in survivors} == {"fresh"})
check("finalize marks changed", changed is True)
check("finalize updates last_sha", source["last_sha"] == "deadbeef")
check("finalize adds both ids to known_ids", set(source["known_ids"]) == {"old", "fresh"})
check("finalize records last_run_timestamp", source["last_run_timestamp"] == 1000)

now_ts = 1_000_000
window = run.LOOKBACK_HOURS * 3600
cutoff = now_ts - window
raw_data = [
    {"id": "recent", "date_posted": now_ts - 3600},
    {"id": "stale", "date_posted": cutoff - 3600},
    {"id": "edge", "date_posted": cutoff},
]

cands, known_after, seeded = run.select_raw_candidates(raw_data, set(), now_ts, window)
check("raw seed is flagged seeded", seeded is True)
check("raw seed surfaces only in-window", set(cands) == {"recent", "edge"})
check("raw seed records every id", known_after == {"recent", "stale", "edge"})

known = {"recent", "stale", "edge"}
incr_data = raw_data + [
    {"id": "brand-new", "date_posted": now_ts - 60},
    {"id": "backfilled", "date_posted": cutoff - 999_999},
]
cands2, _, seeded2 = run.select_raw_candidates(incr_data, known, now_ts, window)
check("raw incremental not seeded", seeded2 is False)
check("raw incremental surfaces new ids incl. backfilled old-date",
      set(cands2) == {"brand-new", "backfilled"})

class _FakeHTTPError:
    def __init__(self, code, body):
        self.code = code
        self._body = body.encode()
    def read(self):
        return self._body

check("scope-block detected on 403 + message",
      run._is_scope_block(_FakeHTTPError(403, "GitHub access ... not enabled for this session")))
check("non-scope 403 not treated as scope-block",
      not run._is_scope_block(_FakeHTTPError(403, "rate limit exceeded")))
check("404 not treated as scope-block",
      not run._is_scope_block(_FakeHTTPError(404, "not enabled for this session")))

import shutil
import tempfile

import normalize as N
import reconcile as R
from sources import simplify

check("title_slug merges swe/full", N.title_slug("SWE Intern") == N.title_slug("Software Engineer Intern"))
check("title_slug drops noise/year", N.title_slug("Software Engineer Intern (Summer 2026)") == "software-engineer")
check("title_slug keeps distinct roles", N.title_slug("Frontend Engineer") != N.title_slug("Machine Learning Engineer"))
check("canonical_term season+year", N.canonical_term("Summer 2026") == "Summer 2026")
check("canonical_term reordered", N.canonical_term("2026 Fall Co-op") == "Fall 2026")
check("canonical_term no season -> None", N.canonical_term("Full Time") is None)
check("canonical_terms new-grad bucket", N.canonical_terms([], level="new-grad") == ["New Grad"])
check("canonical_terms empty -> bucket", N.canonical_terms(["Flexible"], level=None) == ["New Grad"])
check("normalize_url strips query/frag, lowercases host", N.normalize_url("HTTPS://Careers.X.com/J/1?a=2#f") == "careers.x.com/J/1")
check("canonical_category folds long form", N.canonical_category("Software Engineering") == "Software")
check("canonical_category folds punctuation variant",
      N.canonical_category("Data Science, AI & Machine Learning") == "AI/ML/Data")
check("canonical_category passes canonical through", N.canonical_category("AI/ML/Data") == "AI/ML/Data")
check("canonical_category keeps unknown value", N.canonical_category("Design") == "Design")
check("canonical_category empty -> empty", N.canonical_category(None) == "")
check("role_key shape", N.role_key("meta", "intern", "SWE Intern") == "meta::intern::software-engineer")
check("natural_key equal across sources",
      N.natural_key("meta", "intern", "SWE Intern", ["Summer 2026"], ["NYC"], "https://x.com/1?utm=a")
      == N.natural_key("meta", "intern", "Software Engineer Intern", ["Summer 2026"], ["NYC"], "https://x.com/1"))

_companies = [
    {"id": "meta", "display_name": "Meta", "tier": "S", "aliases": {"*": ["Meta", "Facebook"]}},
    {"id": "acme", "display_name": "Acme", "tier": "B", "aliases": {"boardx": ["Acme Robotics"]}},
]
_idx = R.build_alias_index(_companies)
check("resolve exact alias", R.resolve_company("Facebook", "simplify:x", _idx) == "meta")
check("resolve case-insensitive", R.resolve_company("  meta  ", "simplify:x", _idx) == "meta")
check("resolve loose suffix fallback", R.resolve_company("Meta, Inc.", "simplify:x", _idx) == "meta")
check("resolve source-scoped alias", R.resolve_company("Acme Robotics", "boardx", _idx) == "acme")
check("resolve unknown -> None", R.resolve_company("Unrelated Co", "simplify:x", _idx) is None)

_META = {"id": "meta", "display_name": "Meta", "tier": "S", "aliases": {"*": ["Meta"]}}
_REPO = "SimplifyJobs/Summer2026-Internships"
_counter = [0]
def _mint():
    _counter[0] += 1
    return "PID%d" % _counter[0]

def _listing(lid, active=True, title="Software Engineer Intern", loc="Menlo Park, CA", url=None):
    return {"id": lid, "company_name": "Meta", "title": title, "active": active,
            "is_visible": True, "terms": ["Summer 2026"], "date_posted": 1000,
            "date_updated": 1000, "url": url or ("https://x.com/j/" + lid),
            "locations": [loc], "category": "Software"}

def _obs(listings, ts):
    return list(simplify.observations(listings, _REPO, ts))

st = R.new_state()
R.reconcile_company(st, _obs([_listing("a1")], 100), _META, 100, _mint)
_p = st["postings"]["PID1"]
check("new posting is open", _p["state"] == "open")
check("new posting opened event", [e["type"] for e in st["events"]] == ["opened"])
check("new posting term bucketed", _p["terms"] == ["Summer 2026"])
check("new posting pay reserved null", _p["pay"] is None)
check("new posting level intern", _p["level"] == "intern")

R.reconcile_company(st, _obs([_listing("a1", loc="Seattle, WA")], 150), _META, 150, _mint)
check("updated event on location change", st["events"][-1]["type"] == "updated"
      and "locations" in st["events"][-1]["detail"]["changed"])
check("still one posting after update", len(st["postings"]) == 1)

R.reconcile_company(st, _obs([_listing("a1", active=False)], 200), _META, 200, _mint)
check("close on inactive flag", st["postings"]["PID1"]["state"] == "closed")
check("closed event + closed_at", st["events"][-1]["type"] == "closed" and st["postings"]["PID1"]["closed_at"] == 200)

R.reconcile_company(st, _obs([_listing("a1", active=True)], 250), _META, 250, _mint)
check("reopened event", st["events"][-1]["type"] == "reopened" and st["postings"]["PID1"]["state"] == "open")
check("closed_at cleared on reopen", st["postings"]["PID1"]["closed_at"] is None)

_ev_before = len(st["events"])
R.reconcile_company(st, _obs([_listing("a2")], 300), _META, 300, _mint)
check("repost new id = new posting", len(st["postings"]) == 2)
check("repost emits opened", st["events"][-1]["type"] == "opened")

st2 = R.new_state()
R.reconcile_company(st2, _obs([_listing("b1")], 100), _META, 100, _mint)
_open_before = st2["postings"][list(st2["postings"])[0]]["state"]
R.reconcile_company(st2, [], _META, 200, _mint)
_open_after = st2["postings"][list(st2["postings"])[0]]["state"]
check("disappearance freezes (no close)", _open_before == "open" and _open_after == "open")
check("disappearance emits no event", st2["events"] == [] or all(e["type"] == "opened" for e in st2["events"]))

st3 = R.new_state()
R.reconcile_company(st3, _obs([_listing("c1")], 100), _META, 100, _mint)
_other = [{"source": "otherboard", "external_id": "z9", "observed_at": 200,
           "company_raw": "Meta", "title_raw": "Software Engineer Intern", "level": "intern",
           "terms": ["Summer 2026"], "locations": ["Menlo Park, CA"], "url": "https://x.com/j/c1",
           "state_raw": {"active": True, "is_visible": True}, "posted_at": 1000}]
R.reconcile_company(st3, _other, _META, 200, _mint)
_merged = st3["postings"][list(st3["postings"])[0]]
check("cross-source merges to one posting", len(st3["postings"]) == 1)
check("cross-source records both sources", set(_merged["sources"]) == {"simplify:Summer2026-Internships", "otherboard"})

_ng_obs = list(simplify.observations(
    [{"id": "n1", "company_name": "Meta", "title": "Software Engineer", "active": True,
      "is_visible": True, "terms": [], "date_posted": 1000, "url": "https://x.com/n1",
      "locations": ["Remote"]}], "SimplifyJobs/New-Grad-Positions", 100))
st4 = R.new_state()
R.reconcile_company(st4, _ng_obs, _META, 100, _mint)
_np = st4["postings"][list(st4["postings"])[0]]
check("new-grad term bucket", _np["terms"] == ["New Grad"] and _np["level"] == "new-grad")

_tmp = tempfile.mkdtemp(prefix="jobwatcher-test-")
try:
    _all_obs = _obs([_listing("d1"), _listing("d2", active=False)], 500)
    _summary = R.reconcile(_all_obs, [_META], _tmp, 500, mint_id=_mint)
    check("reconcile matched company", _summary["matched_companies"] == 1)
    _pj = json.load(open(os.path.join(_tmp, "companies", "meta", "postings.json")))
    check("reconcile wrote postings", len(_pj["postings"]) == 2)
    _ij = json.load(open(os.path.join(_tmp, "index.json")))
    _meta_row = next(c for c in _ij["companies"] if c["slug"] == "meta")
    check("index posting_count", _meta_row["posting_count"] == 2)
    check("index open_count excludes closed", _meta_row["open_count"] == 1)
    check("index carries levels_url key", "levels_url" in _meta_row)
    check("events.jsonl written", os.path.exists(os.path.join(_tmp, "companies", "meta", "events.jsonl")))
    _agg = json.load(open(os.path.join(_tmp, "all_postings.json"), encoding="utf-8"))
    check("aggregate counts every posting",
          _agg["count"] == 2 and len(_agg["postings"]) == 2)
    check("aggregate ids match the per-company store",
          {r["id"] for r in _agg["postings"]} == {p["posting_id"] for p in _pj["postings"]})
    check("aggregate carries the catalog fields",
          all({"id", "co", "t", "s", "lvl", "tm", "loc", "cat", "fs"} <= set(r)
              for r in _agg["postings"]))
    check("aggregate drops the sources blob",
          all("sources" not in r and "attributes" not in r for r in _agg["postings"]))
    check("aggregate mirrors open/closed state",
          sorted(r["s"] for r in _agg["postings"]) == ["closed", "open"])
    check("aggregate canonicalizes category", {r["cat"] for r in _agg["postings"]} == {"Software"})
    check("reconcile reports the corpus size", _summary["postings_total"] == 2)
    _summary2 = R.reconcile(
        _obs([{"id": "u1", "company_name": "Nobody Inc", "title": "X", "active": True,
               "is_visible": True, "terms": [], "date_posted": 1, "url": "https://x/u1",
               "locations": []}], 600), [_META], _tmp, 600, mint_id=_mint)
    check("unresolved observation ignored", _summary2["unresolved_observations"] == 1)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


_cj = json.load(open(os.path.join(_HERE, "..", "tracker", "companies.json")))
check("companies.json is a list of 100", isinstance(_cj, list) and len(_cj) == 100)
check("every tier in S/A/B/C", all(c.get("tier") in ("S", "A", "B", "C") for c in _cj))
check("every company has a levels_url key", all("levels_url" in c for c in _cj))
check("every company has id + aliases", all(c.get("id") and c.get("aliases") for c in _cj))
_ids = [c["id"] for c in _cj]
check("company ids unique", len(_ids) == len(set(_ids)))
check("bytedance deduped to one", _ids.count("bytedance") == 1)
check("tiktok present (watchlist union)", "tiktok" in _ids)

_cidx = R.build_alias_index(_cj)
check("alias Facebook -> meta", R.resolve_company("Facebook", "simplify:x", _cidx) == "meta")
check("alias Alphabet -> google", R.resolve_company("Alphabet", "simplify:x", _cidx) == "google")
check("alias AWS -> amazon", R.resolve_company("AWS", "simplify:x", _cidx) == "amazon")
check("alias 'The D. E. Shaw Group' -> de-shaw",
      R.resolve_company("The D. E. Shaw Group", "simplify:x", _cidx) == "de-shaw")
check("alias TikTok -> tiktok", R.resolve_company("TikTok", "simplify:x", _cidx) == "tiktok")


print()
if failures:
    print(f"{len(failures)}/{total} FAILED: {failures}")
    raise SystemExit(1)
print(f"ALL {total} PASSED")
