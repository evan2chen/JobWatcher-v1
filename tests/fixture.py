import json
import os
import shutil
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def dump(path, obj):
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def build_tree(root):
    dump(os.path.join(root, "sources.json"), [{
        "repo": "Owner/Repo",
        "branch": "dev",
        "listings_path": ".github/scripts/listings.json",
        "last_sha": None,
        "last_run_timestamp": 1700000000,
        "known_ids": ["zzz", "aaa", "mmm"],
        "filters": {"categories": [], "title_keywords": [], "locations": [],
                    "active_only": True, "visible_only": True},
    }])
    dump(os.path.join(root, "seen_listings.json"), [
        {"id": "b", "source_repo": "Owner/Repo", "company_name": "Beta",
         "title": "SWE Intern", "category": "Software", "locations": ["NYC"],
         "url": "https://example.com/b", "date_posted": 2, "date_first_seen": 3,
         "status": "new", "status_updated": None, "notes": ""},
        {"id": "a", "source_repo": "Owner/Repo", "company_name": "Alpha",
         "title": "Quant — Café", "category": "Quant", "locations": [],
         "url": "https://example.com/a", "date_posted": 1, "date_first_seen": 2,
         "status": "applied", "status_updated": 9, "notes": "phone screen"},
    ])
    dump(os.path.join(root, "collectors.json"), [{
        "name": "simplify:Repo",
        "command": ["python", "-m", "jw.collectors.simplify", "Owner/Repo"],
        "filters": {"categories": ["Software"]},
        "env": [], "track_all": False, "seed_hours": 25, "timeout_s": 300,
        "max_output_mb": 64, "enabled": False, "id_namespace": "", "created_at": 1700000000,
    }])
    dump(os.path.join(root, "observed.json"), {
        "simplify:Repo": ["zzz", "aaa", "mmm"],
        "acme": ["acme:2", "acme:1"],
    })
    dump(os.path.join(root, "tracker", "companies.json"), [
        {"id": "alpha", "display_name": "Alpha", "tier": "S",
         "careers_url": "https://a.example", "levels_url": None,
         "aliases": {"*": ["Alpha", "Alpha Inc"]}, "notes": ""},
        {"id": "gamma", "display_name": "Gamma", "tier": "A", "careers_url": None,
         "levels_url": None, "aliases": {"*": ["Gamma"]}, "notes": "no store yet"},
    ])

    cdir = os.path.join(root, "tracker", "companies", "alpha")
    dump(os.path.join(cdir, "postings.json"), {"company_id": "alpha", "postings": [
        {"posting_id": "p2", "company_id": "alpha", "role_key": "alpha::intern::b",
         "level": "intern", "title": "B", "terms": ["Summer 2026"],
         "locations": ["SF"], "apply_url": "https://x/2", "posted_at": 20,
         "first_seen": 21, "last_seen": 22, "closed_at": None, "state": "open",
         "pay": None, "sources": {"simplify:R": {"external_id": "b", "url": "https://x/2",
                                                 "state": "active", "first_seen": 21,
                                                 "last_seen": 22}},
         "attributes": {"category": "Software", "degrees": []}},
        {"posting_id": "p1", "company_id": "alpha", "role_key": "alpha::intern::a",
         "level": "intern", "title": "A", "terms": [], "locations": [],
         "apply_url": None, "posted_at": 10, "first_seen": 11, "last_seen": 12,
         "closed_at": 12, "state": "closed", "pay": None,
         "sources": {"simplify:R": {"external_id": "e1", "url": None,
                                    "state": "closed", "first_seen": 11, "last_seen": 12}},
         "attributes": {}},
    ]})
    dump(os.path.join(cdir, "crosswalk.json"), {
        "external": {"simplify:R|b": "p2", "simplify:R|e1": "p1"},
        "natural": {"alpha | intern | b": "p2"},
    })
    write(os.path.join(cdir, "events.jsonl"),
          json.dumps({"at": 21, "posting_id": "p2", "role_key": "alpha::intern::b",
                      "type": "opened", "source": "simplify:R"}, ensure_ascii=False) + "\n" +
          json.dumps({"at": 12, "posting_id": "p1", "role_key": "alpha::intern::a",
                      "type": "updated", "source": "simplify:R",
                      "detail": {"title": ["A0", "A"]}}, ensure_ascii=False) + "\n")

    bdir = os.path.join(root, "tracker", "companies", "beta")
    dump(os.path.join(bdir, "postings.json"), {"company_id": "beta", "postings": []})


WEB_COMPANIES = [
    {"id": "zenith", "display_name": "Zenith", "tier": "S",
     "careers_url": "https://zenith.example/careers", "levels_url": None,
     "aliases": {"*": ["Zenith"]}, "notes": ""},
    {"id": "orbit", "display_name": "Orbit Capital", "tier": "A",
     "careers_url": None, "levels_url": None,
     "aliases": {"*": ["Orbit", "Orbit Capital"]}, "notes": ""},
    {"id": "lumen", "display_name": "Lumen Labs", "tier": "B",
     "careers_url": None, "levels_url": None, "aliases": {"*": ["Lumen"]}, "notes": ""},
]


def _posting(now, pid, cid, title, category, level, terms, locations, state,
             age_days, sponsorship=None, apply_url=None):
    at = now - age_days * 86400
    return {
        "posting_id": pid, "company_id": cid,
        "role_key": f"{cid}::{level}::{pid}", "level": level, "title": title,
        "terms": terms, "locations": locations, "apply_url": apply_url,
        "posted_at": at, "first_seen": at, "last_seen": now,
        "closed_at": now if state == "closed" else None, "state": state,
        "pay": None,
        "sources": {"simplify:Web": {"external_id": pid, "url": apply_url,
                                     "state": "active" if state == "open" else "closed",
                                     "first_seen": at, "last_seen": now}},
        "attributes": {"category": category, "degrees": [],
                       **({"sponsorship": sponsorship} if sponsorship else {})},
    }


def _web_stores(now):
    def p(*args, **kwargs):
        return _posting(now, *args, **kwargs)

    return {
        "zenith": [
            p("z1", "zenith", "Software Engineer Intern", "Software", "intern",
              ["Summer 2026"], ["San Francisco, CA"], "open", 2,
              sponsorship="Offers Sponsorship",
              apply_url="https://zenith.example/jobs/z1"),
            p("z2", "zenith", "Machine Learning Research Intern", "AI/ML/Data",
              "intern", ["Summer 2026"], ["Seattle, WA"], "open", 5),
            p("z3", "zenith", "Backend Engineer, New Grad", "Software",
              "new-grad", ["New Grad"], ["New York, NY"], "open", 9),
            p("z4", "zenith", "Platform Engineer Intern", "Software", "intern",
              ["Summer 2026"], ["San Francisco, CA"], "closed", 60),
        ],
        "orbit": [
            p("o1", "orbit", "Quantitative Trader Intern", "Quant", "intern",
              ["Summer 2026"], ["Chicago, IL"], "open", 3),
            p("o2", "orbit", "FPGA Engineer Intern", "Hardware", "intern",
              ["Summer 2026"], ["Austin, TX"], "open", 12),
        ],
        "lumen": [
            p("l1", "lumen", "Sales Engineer Intern", "Software", "intern",
              ["Summer 2026"], ["Remote in USA"], "open", 4),
            p("l2", "lumen", "Compiler Engineer", "Software", "new-grad",
              ["New Grad"], ["Remote in USA"], "open", 20),
        ],
    }


def write_store(root, cid, postings):
    cdir = os.path.join(root, "tracker", "companies", cid)
    dump(os.path.join(cdir, "postings.json"),
         {"company_id": cid, "postings": postings})
    dump(os.path.join(cdir, "crosswalk.json"), {
        "external": {f"simplify:Web|{p['posting_id']}": p["posting_id"]
                     for p in postings},
        "natural": {f"{cid} | {p['level']} | {p['posting_id']}": p["posting_id"]
                    for p in postings},
    })
    write(os.path.join(cdir, "events.jsonl"), "".join(
        json.dumps({"at": p["first_seen"], "posting_id": p["posting_id"],
                    "role_key": p["role_key"], "type": "opened",
                    "source": "simplify:Web"}, ensure_ascii=False) + "\n"
        for p in postings))


def build_web_tree(root, now_ts):
    build_tree(root)

    companies_path = os.path.join(root, "tracker", "companies.json")
    with open(companies_path, encoding="utf-8") as fh:
        companies = json.load(fh)
    companies.extend(WEB_COMPANIES)
    dump(companies_path, companies)

    for cid, postings in _web_stores(now_ts).items():
        write_store(root, cid, postings)

    from jw import reconcile

    tracker_dir = os.path.join(root, "tracker")
    reconcile.build_index(tracker_dir, companies, now_ts)
    reconcile.build_all_postings(tracker_dir, companies, now_ts)


BULK_TITLES = (
    "Software Engineer Intern", "Backend Engineer, Payments", "Quant: Researcher",
    "Machine Learning Engineer – Platform", "Data Scientist 日本語 🚀",
    "Site Reliability Engineer", "Firmware Engineer Intern", "Compiler Engineer, New Grad",
)
BULK_SHARED_PREFIX_IDS = (
    "abcd1234-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "abcd1234-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
)
BULK_NUMERIC_LOOKING_ID = "12345678-cccc-4ccc-8ccc-cccccccccccc"


def build_bulk_tree(root, now_ts, count=120):
    import uuid

    build_web_tree(root, now_ts)
    company = {"id": "vertex", "display_name": "Vertex Systems", "tier": "A",
               "careers_url": "https://vertex.example/careers", "levels_url": None,
               "aliases": {"*": ["Vertex", "Vertex Systems"]}, "notes": ""}
    companies_path = os.path.join(root, "tracker", "companies.json")
    with open(companies_path, encoding="utf-8") as fh:
        companies = json.load(fh)
    companies.append(company)
    dump(companies_path, companies)

    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"jw-bulk-{i}")) for i in range(count)]
    ids[:len(BULK_SHARED_PREFIX_IDS)] = BULK_SHARED_PREFIX_IDS
    ids[len(BULK_SHARED_PREFIX_IDS)] = BULK_NUMERIC_LOOKING_ID
    postings = [
        _posting(now_ts, pid, "vertex", BULK_TITLES[i % len(BULK_TITLES)],
                 "Software", "intern" if i % 2 else "new-grad", ["Summer 2027"],
                 ["Austin, TX", "Remote"], "closed" if i % 11 == 10 else "open",
                 age_days=1 + i % 90,
                 apply_url=f"https://vertex.example/jobs/{pid}")
        for i, pid in enumerate(ids)
    ]
    write_store(root, "vertex", postings)

    from jw import reconcile

    tracker_dir = os.path.join(root, "tracker")
    reconcile.build_index(tracker_dir, companies, now_ts)
    reconcile.build_all_postings(tracker_dir, companies, now_ts)
    return ids


def stage_site(root, repo_root=REPO_ROOT):
    src = os.path.join(repo_root, "docs")
    index = os.path.join(src, "index.html")
    assets = os.path.join(src, "assets")
    if not os.path.isfile(index) or not os.path.isdir(assets):
        raise SystemExit(
            "docs/ has no built site - run `npm run build` in web/ before staging a fixture")
    dest = os.path.join(root, "docs")
    os.makedirs(dest, exist_ok=True)
    shutil.copy2(index, os.path.join(dest, "index.html"))
    shutil.copytree(assets, os.path.join(dest, "assets"), dirs_exist_ok=True)
    return dest


def make_store(root, db_path):
    from jw import db, importer

    con = db.connect(db_path)
    db.init(con)
    counts = importer.import_all(con, root)
    con.close()
    return counts


def stage(outdir, now_ts=None):
    now_ts = int(now_ts if now_ts is not None else time.time())
    root = os.path.join(outdir, "repo")
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(root, exist_ok=True)

    build_web_tree(root, now_ts)
    site = stage_site(root)
    db_path = os.path.join(outdir, "store.db")
    make_store(root, db_path)
    return {"root": root, "db": db_path, "site": site, "now": now_ts}


def main(argv):
    if len(argv) != 2:
        print("usage: python tests/fixture.py <outdir>", file=sys.stderr)
        return 2
    print(json.dumps(stage(os.path.abspath(argv[1])), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
