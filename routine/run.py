#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone


LOOKBACK_HOURS = 25
GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
USER_AGENT = "JobWatcher/1.0 (+https://github.com/evan2chen/JobWatcher-v1)"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SOURCES_PATH = os.path.join(REPO_ROOT, "sources.json")
SEEN_PATH = os.path.join(REPO_ROOT, "seen_listings.json")
WATCHLIST_PATH = os.path.join(REPO_ROOT, "watchlist.json")

TRACKER_DIR = os.path.join(REPO_ROOT, "tracker")
COMPANIES_PATH = os.path.join(TRACKER_DIR, "companies.json")

sys.path.insert(0, REPO_ROOT)

from jw.digest import (  # noqa: E402
    SLACK_MAX_CHARS,
    build_slack_message,
    matches_watchlist,
    normalize_category,
    split_slack_message,
)
from jw.notify import post_chunk  # noqa: E402


def log(msg):
    print(f"[jobwatcher] {msg}", file=sys.stderr)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def load_watchlist(path=WATCHLIST_PATH):
    try:
        raw = load_json(path)
    except (FileNotFoundError, ValueError):
        return []
    if not isinstance(raw, list):
        log(f"watchlist.json is not a JSON array — ignoring")
        return []
    return [str(c).strip().lower() for c in raw if str(c).strip()]


def iso_since(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _request(url, accept="application/vnd.github+json", raw_text=False, retries=3):
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(GITHUB_API):
        headers["Authorization"] = f"Bearer {token}"

    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return body if raw_text else json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and attempt < retries - 1:
                wait = 2 ** attempt
                log(f"HTTP {exc.code} on {url} — retrying in {wait}s")
                time.sleep(wait)
                last_err = exc
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < retries - 1:
                wait = 2 ** attempt
                log(f"network error on {url} ({exc}) — retrying in {wait}s")
                time.sleep(wait)
                last_err = exc
                continue
            raise
    if last_err:
        raise last_err


_RAW_CACHE = {}


def fetch_full_listings_raw(repo, branch, path):
    cache_key = (repo, branch, path)
    if cache_key in _RAW_CACHE:
        return _RAW_CACHE[cache_key]
    url = f"{RAW_BASE}/{repo}/{branch}/{path}"
    log(f"fetching full listings via raw: {url}")
    text = _request(url, raw_text=True, accept="*/*")
    _RAW_CACHE[cache_key] = text
    return text


def list_recent_commits(repo, branch, path, since_iso):
    url = (
        f"{GITHUB_API}/repos/{repo}/commits"
        f"?path={path}&sha={branch}&since={since_iso}&per_page=100"
    )
    return _request(url)


def get_commit_detail(repo, sha):
    return _request(f"{GITHUB_API}/repos/{repo}/commits/{sha}")


def objects_from_added_lines(patch):
    added = []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    text = "\n".join(added)

    objects = []
    depth = 0
    start = None
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    chunk = text[start : i + 1]
                    try:
                        obj = json.loads(chunk)
                        if isinstance(obj, dict) and "id" in obj:
                            objects.append(obj)
                    except json.JSONDecodeError:
                        pass
                    start = None
    return objects


def added_objects_from_commits(repo, commits, listings_path, known_ids):
    objects_by_id = {}
    patch_failed = False
    for c in commits:
        sha = c["sha"]
        detail = get_commit_detail(repo, sha)
        file_entry = next(
            (f for f in detail.get("files", []) if f.get("filename") == listings_path),
            None,
        )
        if file_entry is None:
            continue
        patch = file_entry.get("patch")
        if not patch:
            log(f"commit {sha[:10]} has no patch for {listings_path} (truncated)")
            patch_failed = True
            continue
        for obj in objects_from_added_lines(patch):
            oid = obj.get("id")
            if oid and oid not in known_ids and oid not in objects_by_id:
                objects_by_id[oid] = obj
    return objects_by_id, patch_failed


def new_objects_from_full_file(full_text, known_ids):
    data = json.loads(full_text)
    return {
        obj["id"]: obj
        for obj in data
        if obj.get("id") and obj["id"] not in known_ids
    }


def passes_active_visible(listing, filters):
    if filters.get("active_only", True) and not listing.get("active", False):
        return False
    if filters.get("visible_only", True) and not listing.get("is_visible", False):
        return False
    return True


def passes_filters(listing, filters):
    if not passes_active_visible(listing, filters):
        return False

    cats = filters.get("categories") or []
    if cats:
        canon = normalize_category(listing.get("category"))
        wanted = {normalize_category(c) for c in cats}
        if canon not in wanted:
            return False

    keywords = filters.get("title_keywords") or []
    if keywords:
        title = (listing.get("title") or "").lower()
        if not any(kw.lower() in title for kw in keywords):
            return False

    locs = filters.get("locations") or []
    if locs:
        listing_locs = " ".join(listing.get("locations") or []).lower()
        if not any(loc.lower() in listing_locs for loc in locs):
            return False

    return True


def to_seen_entry(listing, source_repo, now_ts):
    return {
        "id": listing.get("id"),
        "source_repo": source_repo,
        "company_name": listing.get("company_name"),
        "title": listing.get("title"),
        "category": normalize_category(listing.get("category")),
        "locations": listing.get("locations") or [],
        "url": listing.get("url"),
        "date_posted": listing.get("date_posted"),
        "date_first_seen": now_ts,
        "status": "new",
        "status_updated": None,
        "notes": "",
    }


def _post_slack_chunk(webhook, text):
    ok, error = post_chunk(webhook, text)
    if not ok:
        log(f"Slack post failed: {error}")
    return ok


def post_slack(text):
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        log("SLACK_WEBHOOK_URL not set — skipping Slack post")
        return False
    chunks = split_slack_message(text)
    n = len(chunks)
    ok = True
    for i, chunk in enumerate(chunks, 1):
        body = f"{chunk}\n_(part {i}/{n})_" if n > 1 else chunk
        if not _post_slack_chunk(webhook, body):
            ok = False
    if ok:
        log(f"posted digest to Slack ({n} message{'s' if n != 1 else ''})")
    return ok


def select_raw_candidates(data, known_ids, now_ts, seed_window):
    all_ids = {o["id"] for o in data if o.get("id")}
    if not known_ids:
        cutoff = now_ts - seed_window
        candidates = {
            o["id"]: o for o in data
            if o.get("id") and (o.get("date_posted") or 0) >= cutoff
        }
        return candidates, all_ids, True
    candidates = {
        o["id"]: o for o in data
        if o.get("id") and o["id"] not in known_ids
    }
    return candidates, set(known_ids), False


def _is_scope_block(exc):
    if getattr(exc, "code", None) != 403:
        return False
    try:
        body = exc.read().decode("utf-8", "replace")
    except Exception:
        return False
    return "not enabled for this session" in body


def _process_raw_only(source, filters, known_ids, seen_ids, repo, branch, path,
                      now_ts, args, watchlist):
    full_text = fetch_full_listings_raw(repo, branch, path)
    data = json.loads(full_text)
    candidates, known_ids, seeded = select_raw_candidates(
        data, known_ids, now_ts, LOOKBACK_HOURS * 3600
    )
    if seeded:
        log(f"{repo}: raw-only baseline seed — recorded {len(known_ids)} ids, "
            f"{len(candidates)} recent to surface")
    else:
        log(f"{repo}: raw-only -> {len(candidates)} candidate new listings")
    return _finalize(source, candidates, filters, known_ids, seen_ids,
                     repo, now_ts, new_sha=None, args=args, watchlist=watchlist)


def process_source(source, seen_ids, args, watchlist=None):
    repo = source["repo"]
    branch = source["branch"]
    path = source["listings_path"]
    filters = source.get("filters", {})
    known_ids = set(source.get("known_ids") or [])
    watchlist = watchlist or []
    now_ts = int(time.time())

    if args.fixture:
        snapshot = load_json(args.fixture)
        snap_ids = {o["id"] for o in snapshot if o.get("id")}
        full_text = fetch_full_listings_raw(repo, branch, path)
        candidates = new_objects_from_full_file(full_text, snap_ids)
        log(f"{repo}: fixture diff -> {len(candidates)} candidate new listings")
        return _finalize(source, candidates, filters, known_ids, seen_ids,
                         repo, now_ts, new_sha=None, args=args, watchlist=watchlist)

    if getattr(args, "raw_only", False):
        return _process_raw_only(source, filters, known_ids, seen_ids, repo,
                                 branch, path, now_ts, args, watchlist)

    try:
        commits = list_recent_commits(repo, branch, path, iso_since(LOOKBACK_HOURS))
    except urllib.error.HTTPError as exc:
        if _is_scope_block(exc):
            log(f"{repo}: commits API scope-blocked — falling back to raw-only")
            return _process_raw_only(source, filters, known_ids, seen_ids, repo,
                                     branch, path, now_ts, args, watchlist)
        raise
    if not commits:
        log(f"{repo}: no commits touching {path} in last {LOOKBACK_HOURS}h")
        return [], False
    new_sha = commits[0]["sha"]
    last_sha = source.get("last_sha")

    if last_sha == new_sha:
        log(f"{repo}: already at HEAD {new_sha[:10]} — nothing new")
        return [], False

    if not last_sha:
        log(f"{repo}: baseline seed (last_sha is null)")
        full_text = fetch_full_listings_raw(repo, branch, path)
        data = json.loads(full_text)
        known_ids = {o["id"] for o in data if o.get("id")}
        cutoff = now_ts - LOOKBACK_HOURS * 3600
        candidates = {
            o["id"]: o
            for o in data
            if o.get("id") and (o.get("date_posted") or 0) >= cutoff
        }
        log(f"{repo}: seeded {len(known_ids)} ids; {len(candidates)} recent to surface")
        return _finalize(source, candidates, filters, known_ids, seen_ids,
                         repo, now_ts, new_sha=new_sha, args=args, watchlist=watchlist)

    new_commits = []
    for c in commits:
        if c["sha"] == last_sha:
            break
        new_commits.append(c)
    log(f"{repo}: {len(new_commits)} new commit(s) since {last_sha[:10]}")

    candidates, patch_failed = added_objects_from_commits(
        repo, new_commits, path, known_ids
    )
    if patch_failed:
        log(f"{repo}: patch parsing incomplete — using raw full-file fallback")
        full_text = fetch_full_listings_raw(repo, branch, path)
        candidates = new_objects_from_full_file(full_text, known_ids)
    log(f"{repo}: {len(candidates)} candidate new listings")

    return _finalize(source, candidates, filters, known_ids, seen_ids,
                     repo, now_ts, new_sha=new_sha, args=args, watchlist=watchlist)


def _finalize(source, candidates, filters, known_ids, seen_ids, repo, now_ts,
              new_sha, args, watchlist=None):
    watchlist = watchlist or []
    survivors = []
    for oid, listing in candidates.items():
        if oid in seen_ids:
            continue
        surfaced = passes_filters(listing, filters) or (
            matches_watchlist(listing.get("company_name"), watchlist)
            and passes_active_visible(listing, filters)
        )
        if surfaced:
            entry = to_seen_entry(listing, repo, now_ts)
            survivors.append(entry)
            seen_ids.add(oid)

    known_ids.update(candidates.keys())
    source["known_ids"] = sorted(known_ids)
    if new_sha:
        source["last_sha"] = new_sha
    source["last_run_timestamp"] = now_ts

    log(f"{repo}: {len(survivors)} survivor(s) after filtering")
    return survivors, True


def run_tracker(sources, args):
    try:
        import reconcile as tracker_reconcile
        from sources import simplify
    except Exception as exc:  # pragma: no cover
        log(f"tracker: import failed ({exc}) — skipping")
        return

    try:
        companies = load_json(COMPANIES_PATH)
    except (FileNotFoundError, ValueError):
        log("tracker: no tracker/companies.json — skipping")
        return
    if not isinstance(companies, list) or not any(
        isinstance(c, dict) and c.get("id") for c in companies
    ):
        log("tracker: companies.json is empty/placeholder — skipping")
        return

    now_ts = int(time.time())
    observed = []
    for source in sources:
        if args.source and source["repo"] != args.source:
            continue
        repo, branch, path = source["repo"], source["branch"], source["listings_path"]
        try:
            data = json.loads(fetch_full_listings_raw(repo, branch, path))
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError,
                TimeoutError) as exc:
            log(f"tracker: {repo} fetch/parse failed ({exc}) — skipping source")
            continue
        observed.extend(simplify.observations(data, repo, now_ts))

    if not observed:
        log("tracker: no observations gathered — skipping")
        return

    warn = os.environ.get("TRACKER_WARN_ON_ZERO", "").lower() in ("1", "true", "yes")

    if args.dry_run:
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="jobwatcher-tracker-")
        try:
            src = os.path.join(TRACKER_DIR, "companies")
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(tmp, "companies"))
            tracker_reconcile.reconcile(
                observed, companies, tmp, now_ts, warn_on_zero=warn, log=log)
            log("--dry-run: tracker changes computed in a temp dir, not written")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return

    tracker_reconcile.reconcile(
        observed, companies, TRACKER_DIR, now_ts, warn_on_zero=warn, log=log)


def main():
    parser = argparse.ArgumentParser(description="JobWatcher engine")
    parser.add_argument("--dry-run", action="store_true",
                        help="no file writes, no Slack post")
    parser.add_argument("--no-slack", action="store_true",
                        help="mutate state but skip Slack")
    parser.add_argument("--source", help="only process this repo (owner/name)")
    parser.add_argument("--fixture",
                        help="diff live file against this local snapshot (offline)")
    parser.add_argument("--raw-only", action="store_true",
                        help="skip the commits API; diff the full raw file on ids "
                             "(for the routine VM, where that API is scope-blocked)")
    parser.add_argument("--no-tracker", action="store_true",
                        help="skip the company posting-history tracker")
    args = parser.parse_args()

    sources = load_json(SOURCES_PATH)
    seen = load_json(SEEN_PATH)
    seen_ids = {e["id"] for e in seen if e.get("id")}
    watchlist = load_watchlist()
    if watchlist:
        log(f"watchlist: {len(watchlist)} company term(s) of interest")

    survivors_by_source = {}
    any_changed = False

    for source in sources:
        if args.source and source["repo"] != args.source:
            continue
        try:
            survivors, changed = process_source(source, seen_ids, args, watchlist)
        except urllib.error.HTTPError as exc:
            log(f"{source['repo']}: HTTP error {exc.code} — skipping this source")
            log(f"  ({exc.read()[:200] if hasattr(exc, 'read') else exc})")
            continue
        any_changed = any_changed or changed
        if survivors:
            survivors_by_source[source["repo"]] = survivors
            seen.extend(survivors)

    total_new = sum(len(v) for v in survivors_by_source.values())
    watchlist_hits = sum(
        1 for survivors in survivors_by_source.values() for s in survivors
        if matches_watchlist(s.get("company_name"), watchlist)
    )
    log(f"total new survivors: {total_new}")
    log(f"watchlist matches: {watchlist_hits} of {total_new} new listings")

    if total_new and not args.dry_run and not args.no_slack:
        post_slack(build_slack_message(survivors_by_source, watchlist))
    elif total_new and args.dry_run:
        log("--dry-run: Slack payload below")
        print(build_slack_message(survivors_by_source, watchlist))

    if args.dry_run:
        log("--dry-run: not writing sources.json / seen_listings.json")
    elif any_changed:
        write_json(SOURCES_PATH, sources)
        write_json(SEEN_PATH, seen)
        log("wrote sources.json and seen_listings.json")
    else:
        log("no changes — files untouched")

    if not args.no_tracker:
        run_tracker(sources, args)


if __name__ == "__main__":
    main()
