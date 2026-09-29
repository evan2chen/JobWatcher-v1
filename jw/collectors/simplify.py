import argparse
import json
import sys
import time
import urllib.error
import urllib.request

RAW_BASE = "https://raw.githubusercontent.com"
DEFAULT_BRANCH = "dev"
DEFAULT_PATH = ".github/scripts/listings.json"
USER_AGENT = "JobWatcher/1.0 (+https://github.com/evan2chen/JobWatcher-v1)"
EXIT_UPSTREAM = 3

REPO_LEVELS = {
    "SimplifyJobs/Summer2027-Internships": "intern",
    "SimplifyJobs/New-Grad-Positions": "new-grad",
}


def level_for_repo(repo):
    if repo in REPO_LEVELS:
        return REPO_LEVELS[repo]
    name = (repo or "").lower()
    if "intern" in name:
        return "intern"
    if "new-grad" in name or "newgrad" in name or "new_grad" in name:
        return "new-grad"
    return "unknown"


def source_id(repo):
    short = repo.split("/")[-1] if repo else repo
    return f"simplify:{short}"


def observation(listing, repo, observed_at):
    return {
        "source": source_id(repo),
        "external_id": listing.get("id"),
        "observed_at": observed_at,
        "company_raw": listing.get("company_name"),
        "title_raw": listing.get("title"),
        "level": level_for_repo(repo),
        "terms": listing.get("terms") or [],
        "locations": listing.get("locations") or [],
        "url": listing.get("url"),
        "posted_at": listing.get("date_posted"),
        "updated_at": listing.get("date_updated"),
        "state_raw": {
            "active": listing.get("active", True),
            "is_visible": listing.get("is_visible", True),
        },
        "extra": {
            "category": listing.get("category"),
            "sponsorship": listing.get("sponsorship"),
            "degrees": listing.get("degrees") or [],
            "company_url": listing.get("company_url"),
        },
    }


def observations(data, repo, observed_at):
    for listing in data:
        if isinstance(listing, dict) and listing.get("id"):
            yield observation(listing, repo, observed_at)


def fetch(repo, branch, path, base_url=RAW_BASE, retries=3):
    url = f"{base_url.rstrip('/')}/{repo}/{branch}/{path}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            if attempt == retries - 1:
                raise
            print(f"retrying {url} after {exc}", file=sys.stderr)
            time.sleep(2 ** attempt)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m jw.collectors.simplify",
        description="Print a SimplifyJobs listings repo as Observation JSONL")
    parser.add_argument("repo", help="owner/name, e.g. SimplifyJobs/New-Grad-Positions")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--base-url", default=RAW_BASE)
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", newline="\n")
    try:
        data = fetch(args.repo, args.branch, args.path, args.base_url)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return EXIT_UPSTREAM

    now = int(time.time())
    for obs in observations(data, args.repo, now):
        sys.stdout.write(json.dumps(obs, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
