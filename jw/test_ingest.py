import argparse
import http.server
import importlib.util
import json
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from jw import db, exporter, filters, importer, ingest, reconcile, schema, sync  # noqa: E402
from jw.collectors import simplify  # noqa: E402
from tests import fixture  # noqa: E402
from tests.harness import (check, clean_env, finish, help_lines, jsonl, run_jw,  # noqa: E402
                           scalar, table)

NOW = int(time.time())

FEED = """import os
import sys

name = os.environ["JW_SOURCE"].replace(":", "_")


def read(path, default=""):
    return open(path, encoding="utf-8").read() if os.path.exists(path) else default


sys.stderr.write(read(f"data/{name}.err"))
for line in read(f"data/{name}.jsonl").splitlines():
    if line.strip():
        print(line)
sys.exit(int(read(f"data/{name}.exit", "0") or 0))
"""

SIMPLIFY_FEED = """import json
import time

from jw.collectors import simplify

data = json.load(open("data/feed.json", encoding="utf-8"))
for obs in simplify.observations(data, "Owner/Repo", int(time.time())):
    print(json.dumps(obs, ensure_ascii=False))
"""

ENV_PROBE = """import json
import os

print(json.dumps({
    "source": os.environ["JW_SOURCE"], "external_id": "env:1", "company_raw": "Zenith",
    "title_raw": "Env Probe",
    "extra": {"secret": "SECRET_TOKEN" in os.environ, "declared": os.environ.get("DECLARED_TOKEN"),
              "home": os.environ["JW_HOME"], "cwd": os.getcwd(),
              "slack": "SLACK_WEBHOOK_URL" in os.environ},
}))
"""

SLOW = "import time\ntime.sleep(60)\n"
FLOOD = "import sys\nfor i in range(400):\n    sys.stdout.write('x' * 8192 + chr(10))\n"
GARBAGE = "print('this is not an observation')\n"
BOOM = "import sys\nsys.stderr.write('boom happened')\nsys.exit(1)\n"


def obs(source, ext, company="Zenith", title="Kernel Engineer Intern", **over):
    record = {"source": source, "external_id": ext, "company_raw": company, "title_raw": title,
              "level": "intern", "terms": ["Summer 2027"], "locations": ["NYC"],
              "url": f"https://example.com/{ext}", "posted_at": NOW,
              "extra": {"category": "Software"}}
    record.update(over)
    return record


class Home:
    def __init__(self, tmp, name):
        self.root = os.path.join(tmp, name)
        self.cwd = os.path.join(tmp, f"cwd-{name}")
        os.makedirs(self.cwd)

    def jw(self, *args, stdin=None, **env):
        return run_jw(*args, env=clean_env(JW_HOME=self.root, **env), stdin=stdin,
                      cwd=self.cwd, python_path=REPO)

    def json(self, *args):
        code, out, _ = self.jw("--format", "json", *args)
        return code, json.loads(out)

    def setup(self):
        self.jw("init")
        self.jw("company", "add", "zenith", "--alias", "Zenith")
        self.jw("company", "add", "orbit", "--alias", "Orbit Capital", "--alias", "Orbit")
        return self

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def feed(self, source, records=(), exit_code=0, stderr=""):
        name = source.replace(":", "_")
        self.write("collectors/feed.py", FEED)
        self.write(f"data/{name}.jsonl", "".join(json.dumps(r) + "\n" for r in records))
        self.write(f"data/{name}.exit", str(exit_code))
        self.write(f"data/{name}.err", stderr)

    def counts(self):
        return self.json("state", "show", "--full")[1]["counts"]

    def postings(self, company):
        return self.json("postings", "query", "--company", company, "--limit", "0", "--full")[1]

    def posting(self, prefix):
        return self.json("postings", "show", prefix, "--full")[1]


def check_schema(tmp):
    h = Home(tmp, "schema").setup()
    code, out, _ = h.jw("schema", "observation")
    fields = table(out, "fields")
    required = {f["name"] for f in fields if f["required"] == "yes"}
    check("the schema command lists every field with its type and whether it is required",
          code == 0 and required == {"source", "external_id", "company_raw", "title_raw"}
          and len(fields) == 13)
    check("and gives an example, the rules, and the next commands",
          "example:" in out and "rules[" in out and any("jw ingest" in x for x in help_lines(out)))
    code, body = h.json("schema", "observation", "--full")
    check("--full returns the JSON Schema the validator enforces",
          body["schema"]["additionalProperties"] is False
          and body["schema"]["required"] == ["source", "external_id", "company_raw", "title_raw"])
    check("the example validates against it", schema.validate(body["example"]) == [])
    code, out, _ = h.jw("ingest", "--dry-run", stdin=jsonl([body["example"]]))
    check("and ingests", code == 0 and scalar(out, "observations") == "1")


def check_ingest(tmp):
    h = Home(tmp, "ingest").setup()
    batch = [obs("adhoc", "a:1"),
             obs("adhoc", "a:2", company="Orbit Capital", title="Quant Trader Intern"),
             obs("adhoc", "a:3", company="Nowhere Ltd")]
    code, out, err = h.jw("ingest", stdin=jsonl(batch))
    check("ingest reads Observation JSONL from stdin and reports what it did",
          code == 0 and scalar(out, "observations") == "3" and scalar(out, "opened") == "2"
          and scalar(out, "surfaced") == "3" and err == "")
    check("a posting for a tracked company exists afterwards",
          [p["title"] for p in h.postings("zenith")["postings"]] == ["Kernel Engineer Intern"])
    check("an unmatched company is reported, never silently dropped",
          scalar(out, "unresolved") == "1"
          and table(out, "unresolved_top")[0]["name"] == "Nowhere Ltd")
    code, out, _ = h.jw("ingest", stdin=jsonl(batch))
    check("ingesting the same batch again changes nothing",
          scalar(out, "opened") == "0" and scalar(out, "new") == "0" and scalar(out, "surfaced") == "0")

    good = obs("adhoc", "a:20")
    lines = [
        json.dumps(good),
        "{not json",
        json.dumps({"source": "adhoc", "external_id": "a:21", "company_raw": "Zenith"}),
        json.dumps(dict(good, external_id="a:22", posted_at=NOW * 1000)),
        json.dumps(dict(good, external_id="a:23", title="unexpected")),
        json.dumps(dict(good, external_id="a:24", level="senior")),
        json.dumps(dict(good, external_id="a:25", terms="Summer")),
        json.dumps(dict(good, external_id="a:26")),
    ]
    code, out, _ = h.jw("ingest", stdin=("\n".join(lines) + "\n").encode("utf-8"))
    errors = table(out, "errors")
    text = " ".join(e["error"] for e in errors)
    check("bad lines are rejected with their line numbers while the good ones still apply",
          code == 0 and scalar(out, "observations") == "2" and scalar(out, "rejected") == "6"
          and [e["line"] for e in errors] == ["2", "3", "4", "5", "6", "7"])
    check("and each error says what to fix",
          all(part in text for part in ("not valid JSON", "title_raw: is required", "milliseconds",
                                        "unexpected field", "must be one of", "must be array")))

    before = h.counts()
    code, out, _ = h.jw("ingest", stdin=b"not json at all\n")
    check("input with no valid line is exit 1 and names the problem",
          code == 1 and scalar(out, "code") == "NO_VALID_OBSERVATIONS")
    code, out, _ = h.jw("ingest", "--strict", stdin=("\n".join(lines[:3]) + "\n").encode("utf-8"))
    check("--strict applies nothing when any line is invalid",
          code == 1 and scalar(out, "code") == "INVALID_INPUT" and h.counts() == before)
    code, out, _ = h.jw("ingest", stdin=b"")
    check("empty input is a NO_INPUT error, exit 2", code == 2 and scalar(out, "code") == "NO_INPUT")
    code, out, _ = h.jw("ingest", "--source", "other", stdin=jsonl([obs("adhoc", "a:30")]))
    check("--source refuses lines that name another source",
          code == 1 and "source: must be 'other'" in out)

    h.jw("ingest", stdin=jsonl([obs("first", "shared:1")]))
    code, out, _ = h.jw("ingest", stdin=jsonl([obs("second", "shared:1", company="Orbit Capital")]))
    check("an external_id already used by another source is rejected",
          "already used by source 'first'" in out and scalar(out, "observations") == "0"
          and h.postings("orbit")["count"] == 1)

    before = h.counts()
    code, out, _ = h.jw("ingest", "--dry-run", "--track-all",
                        stdin=jsonl([obs("adhoc", "a:40", company="Brand New Co")]))
    check("--dry-run reports what would happen and writes nothing",
          scalar(out, "dry_run") == "true" and "brand-new" in out and h.counts() == before)

    code, out, _ = h.jw("ingest", "--track-all",
                        stdin=jsonl([obs("adhoc", "a:41", company="Nowhere Ltd")]))
    with open(os.path.join(h.root, "tracker", "companies.json"), encoding="utf-8") as fh:
        ids = [c["id"] for c in json.load(fh)]
    check("--track-all creates a company for an unmatched name and records it in the config",
          "nowhere" in ids and "nowhere" in out)
    code, out, _ = h.jw("ingest", stdin=jsonl([obs("adhoc", "a:42", company="Nowhere Ltd")]))
    check("and later batches match it by alias without the flag", scalar(out, "unresolved") == "0")


def check_lifecycle(tmp):
    h = Home(tmp, "lifecycle").setup()
    h.jw("ingest", stdin=jsonl([obs("adhoc", "l:1"), obs("adhoc", "l:2", title="Other Role")]))
    h.jw("ingest", stdin=jsonl([obs("adhoc", "l:2", title="Other Role")]))
    states = {p["title"]: p["state"] for p in h.postings("zenith")["postings"]}
    check("a posting that vanishes from the feed stays open", states["Kernel Engineer Intern"] == "open")
    code, out, _ = h.jw("ingest", stdin=jsonl([obs("adhoc", "l:1", state_raw={"active": False})]))
    check("a posting the source flags closed is closed", scalar(out, "closed") == "1")
    code, out, _ = h.jw("ingest", stdin=jsonl([obs("adhoc", "l:1")]))
    check("and reopens when the source reports it active again", scalar(out, "reopened") == "1")
    code, out, _ = h.jw("ingest", stdin=jsonl([obs("adhoc", "l:1", title="Kernel Engineer Intern II")]))
    check("a changed title is an update, not a new posting",
          scalar(out, "updated") == "1" and scalar(out, "opened") == "0")


def check_collectors(tmp):
    h = Home(tmp, "collect").setup()
    h.feed("agent-acme", [obs("agent-acme", "acme:1"),
                          obs("agent-acme", "acme:2", company="Orbit Capital",
                              title="Quant Trader Intern")])
    code, out, _ = h.jw("source", "add", "agent-acme", "--command", "python collectors/feed.py")
    check("a collector is registered by name and command", code == 0 and scalar(out, "changed") == "true")
    code, out, _ = h.jw("source", "list")
    check("and listed before it has run", scalar(out, "count") == "1"
          and table(out, "sources")[0]["status"] == "never run")
    code, out, _ = h.jw("sync", "run")
    row = table(out, "sources")[0]
    check("a sync runs it and ingests its output",
          code == 0 and row["status"] == "ok" and row["observations"] == "2" and row["new"] == "2"
          and h.postings("zenith")["count"] == 1)
    code, out, _ = h.jw("sync", "run")
    check("a second sync with the same feed finds nothing new", scalar(out, "new_listings") == "0")
    h.feed("agent-acme", [obs("agent-acme", "acme:1", title="Kernel Engineer Intern II"),
                          obs("agent-acme", "acme:2", company="Orbit Capital",
                              title="Quant Trader Intern")])
    code, body = h.json("sync", "run", "--full")
    check("a changed feed shows up as an update", body["sources"][0]["updated"] == 1)
    code, out, _ = h.jw("source", "list")
    check("and the source list shows its health", table(out, "sources")[0]["status"] == "ok")
    code, out, _ = h.jw("db", "verify")
    check("the home's JSON tree round-trips through the store after syncs",
          code == 0 and scalar(out, "mismatches") == "0")

    for name, body_text, extra in (
        ("crash", BOOM, []),
        ("hang", SLOW, ["--timeout", "1"]),
        ("flood", FLOOD, ["--max-output-mb", "1"]),
        ("garbage", GARBAGE, []),
    ):
        h.write(f"collectors/{name}.py", body_text)
        h.jw("source", "add", name, "--command", f"python collectors/{name}.py", *extra)
    h.jw("source", "add", "ghost", "--command", "definitely-not-a-program")
    before = h.counts()
    expected = {"crash": "failed", "hang": "timeout", "flood": "output_too_large",
                "garbage": "invalid", "ghost": "failed"}
    got = {}
    for name in expected:
        code, out, _ = h.jw("source", "run", name)
        got[name] = (code, scalar(out, "code"), (table(out, "sources") or [{}])[0].get("status"))
    check("every kind of collector failure is reported with its own status",
          {k: v[2] for k, v in got.items()} == expected)
    check("and each is exit 1 with SYNC_FAILED",
          all(v[0] == 1 and v[1] == "SYNC_FAILED" for v in got.values()))
    check("and a failing collector ingests nothing", h.counts() == before)
    code, out, _ = h.jw("--format", "json", "source", "list", "--full")
    sources = {s["name"]: s for s in json.loads(out)["sources"]}
    check("the failure and its stderr line are kept as the source's health",
          sources["crash"]["last_status"] == "failed" and "boom happened" in sources["crash"]["last_error"]
          and sources["hang"]["last_status"] == "timeout")
    code, out, _ = h.jw("doctor")
    check("doctor points at each failing source",
          any("jw source run crash --dry-run" in x for x in help_lines(out)))

    h.write("collectors/envprobe.py", ENV_PROBE)
    h.jw("source", "add", "env-probe", "--command", "python collectors/envprobe.py",
         "--env", "DECLARED_TOKEN")
    h.jw("source", "run", "env-probe", SECRET_TOKEN="hunter2", DECLARED_TOKEN="passed-through",
         SLACK_WEBHOOK_URL="https://hooks.example/x")
    with open(os.path.join(h.root, "tracker", "companies", "zenith", "postings.json"),
              encoding="utf-8") as fh:
        attrs = [p for p in json.load(fh)["postings"] if p["title"] == "Env Probe"][0]["attributes"]
    check("a collector sees only allowlisted environment variables plus the ones it declares",
          attrs["secret"] is False and attrs["slack"] is False and attrs["declared"] == "passed-through")
    check("and runs in the home with JW_HOME set",
          os.path.samefile(attrs["cwd"], h.root) and os.path.samefile(attrs["home"], h.root))


def check_sync_lock(tmp):
    h = Home(tmp, "lock").setup()
    h.feed("agent-lock", [obs("agent-lock", "lock:1")])
    h.jw("source", "add", "agent-lock", "--command", "python collectors/feed.py")

    db_path = os.path.join(h.root, "jobwatcher.db")
    holder = db.connect(db_path, create=False)
    now = int(time.time())
    sync._acquire_lock(holder, now)
    try:
        code, out, _ = h.jw("sync", "run")
        check("a sync refuses to run while another one holds the lock",
              code == 3 and scalar(out, "code") == "BUSY")
    finally:
        sync._release_lock(holder)
    holder.close()

    code, out, _ = h.jw("sync", "run")
    check("and succeeds once the lock is released",
          code == 0 and scalar(out, "new_listings") == "1")

    con = db.connect(db_path, create=False)
    check("a completed sync leaves no lock behind", db.get_meta(con, sync.LOCK_KEY) is None)

    stale_now = int(time.time())
    db.set_meta(con, sync.LOCK_KEY, json.dumps({"pid": 999999, "started_at": stale_now}))
    con.commit()
    code, out, _ = h.jw("sync", "run")
    check("a fresh lock still refuses a concurrent sync",
          code == 3 and scalar(out, "code") == "BUSY")

    db.set_meta(con, sync.LOCK_KEY, json.dumps(
        {"pid": 999999, "started_at": stale_now - sync.LOCK_STALE_AFTER_SECONDS - 1}))
    con.commit()
    code, out, _ = h.jw("sync", "run")
    check("a stale lock is taken over instead of refused", code == 0)
    con.close()


def check_baseline_and_filters(tmp):
    h = Home(tmp, "baseline").setup()
    old, recent = NOW - 5 * 86400, NOW - 3600
    h.feed("base", [obs("base", "b:1", posted_at=old), obs("base", "b:2", posted_at=recent)])
    h.jw("source", "add", "base", "--command", "python collectors/feed.py")
    code, out, _ = h.jw("sync", "run")
    check("the first run tracks every posting but surfaces only the recent ones",
          scalar(out, "new_listings") == "1" and h.postings("zenith")["count"] == 2)
    h.feed("base", [obs("base", "b:1", posted_at=old), obs("base", "b:2", posted_at=recent),
                    obs("base", "b:3", posted_at=old)])
    code, out, _ = h.jw("sync", "run")
    check("after that, every new posting surfaces however old it is", scalar(out, "new_listings") == "1")

    h.jw("watchlist", "add", "Orbit Capital")
    h.feed("filt", [
        obs("filt", "f:1", extra={"category": "Software"}),
        obs("filt", "f:2", extra={"category": "Quant"}, title="Quant Trader Intern"),
        obs("filt", "f:3", company="Orbit Capital", extra={"category": "Hardware"}),
        obs("filt", "f:4", state_raw={"active": False}, extra={"category": "Quant"}),
    ])
    h.jw("source", "add", "filt", "--command", "python collectors/feed.py",
         "--filters", '{"categories": ["Quant"]}')
    code, body = h.json("sync", "run", "--full", "--source", "filt")
    surfaced = sorted(x["id"] for x in body["listings"])
    check("source filters and the watchlist decide what surfaces, as the legacy engine did",
          surfaced == ["f:2", "f:3"])


def check_registry(tmp):
    h = Home(tmp, "registry").setup()
    cmd = "python collectors/feed.py"
    code, out, _ = h.jw("source", "add", "alpha", "--command", cmd)
    code, out, _ = h.jw("source", "add", "alpha", "--command", cmd)
    check("adding the same source twice is a no-op", scalar(out, "changed") == "false")
    code, out, _ = h.jw("source", "add", "alpha", "--command", "python other.py")
    check("adding it with a different setup is ALREADY_EXISTS and points at update",
          code == 1 and scalar(out, "code") == "ALREADY_EXISTS"
          and any("jw source update alpha" in x for x in help_lines(out)))
    for label, args in (
        ("a bad name", ["add", "bad name!", "--command", cmd]),
        ("a missing name", ["add", "--command", cmd]),
        ("both --command and --simplify", ["add", "x", "--command", cmd, "--simplify", "O/R"]),
        ("unparseable filters", ["add", "x", "--command", cmd, "--filters", "{nope"]),
        ("an unknown filter key", ["add", "x", "--command", cmd, "--filters", '{"cats": []}']),
    ):
        code, out, _ = h.jw("source", *args)
        check(f"{label} is a VALIDATION_ERROR, exit 2", code == 2 and scalar(out, "code") == "VALIDATION_ERROR")
    code, out, _ = h.jw("source", "update", "alpha", "--track-all", "true", "--timeout", "5")
    check("update changes only what was passed",
          "updated[2]: track_all,timeout_s" in out)
    code, out, _ = h.jw("source", "disable", "alpha")
    code, out, _ = h.jw("sync", "run")
    check("a disabled source is left out, and with none enabled sync says so",
          code == 2 and scalar(out, "code") == "NO_SOURCES")
    h.feed("alpha", [obs("alpha", "al:1")])
    code, out, _ = h.jw("source", "run", "alpha")
    check("but running it by name still works", code == 0 and scalar(out, "new_listings") == "1")
    code, out, _ = h.jw("source", "remove", "alpha")
    code, out, _ = h.jw("source", "list")
    check("removing a source leaves its postings", scalar(out, "count") == "0"
          and h.postings("zenith")["count"] == 1)
    code, out, _ = h.jw("source", "remove", "alpha")
    check("removing an unknown source is NOT_FOUND, exit 2", code == 2 and scalar(out, "code") == "NOT_FOUND")


def check_legacy_adoption(tmp):
    tree = os.path.join(tmp, "legacy")
    fixture.build_tree(tree)
    for name in ("collectors.json", "observed.json"):
        os.remove(os.path.join(tree, name))
    h = Home(tmp, "legacy")
    h.root = tree
    code, out, _ = h.jw("db", "import")
    code, out, _ = h.jw("source", "adopt-legacy", "--dry-run")
    check("adopt-legacy previews what it would register", scalar(out, "adopted") == "1"
          and h.counts()["collectors"] == 0)
    code, out, _ = h.jw("source", "adopt-legacy")
    counts = h.counts()
    check("adopting turns each legacy source into a collector and keeps its known ids",
          scalar(out, "adopted") == "1" and counts["collectors"] == 1 and counts["observed"] == 3)
    code, body = h.json("source", "list", "--full")
    check("with its filters and the Simplify id namespace",
          body["sources"][0]["filters"]["active_only"] is True
          and body["sources"][0]["name"] == "simplify:Repo"
          and body["sources"][0]["id_namespace"] == "simplify")
    code, out, _ = h.jw("source", "adopt-legacy")
    check("adopting again does nothing", scalar(out, "adopted") == "0")

    h.jw("source", "update", "simplify:Repo", "--command", "python collectors/feed.py")
    h.feed("simplify:Repo", [
        obs("simplify:Repo", "zzz", company="Alpha"), obs("simplify:Repo", "aaa", company="Alpha"),
        obs("simplify:Repo", "new-1", company="Alpha"),
        obs("simplify:Repo", "new-2", company="Alpha", posted_at=NOW - 90 * 86400),
    ])
    code, body = h.json("sync", "run", "--full")
    check("the first sync after adoption surfaces exactly the ids the legacy engine had not seen",
          sorted(x["id"] for x in body["listings"]) == ["new-1", "new-2"])


def check_shared_namespace(tmp):
    h = Home(tmp, "namespace").setup()
    for name in ("simplify:A", "simplify:B"):
        h.jw("source", "add", name, "--command", "python collectors/feed.py",
             "--id-namespace", "simplify")
    h.feed("simplify:A", [obs("simplify:A", "dup-1"), obs("simplify:A", "only-a")])
    h.feed("simplify:B", [obs("simplify:B", "dup-1"), obs("simplify:B", "only-b")])
    code, body = h.json("sync", "run", "--full")
    per_source = {s["name"]: (s["status"], s["new"]) for s in body["sources"]}
    check("sources in one id namespace surface a listing they both carry once",
          code == 0 and per_source == {"simplify:A": ("ok", 2), "simplify:B": ("ok", 1)}
          and sorted(x["id"] for x in body["listings"]) == ["dup-1", "only-a", "only-b"])
    listed = h.postings("zenith")["postings"]
    check("and the listing they share is one posting with both as sources",
          sorted(len(h.posting(p["id"])["sources"]) for p in listed) == [1, 1, 2])

    h.jw("source", "add", "other-board", "--command", "python collectors/feed.py")
    h.feed("other-board", [obs("other-board", "dup-1")])
    code, out, _ = h.jw("source", "run", "other-board")
    check("a source in another namespace cannot reuse the id",
          "already used by source" in out and scalar(out, "new_listings") == "0")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve_directory(directory):
    handler = lambda *a, **k: QuietHandler(*a, directory=directory, **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def raw_listing(i, company="Zenith", **over):
    listing = {"id": f"simplify-{i}", "source": "Simplify", "company_name": company,
               "title": f"Software Engineer Intern {i}", "active": True, "is_visible": True,
               "category": "Software", "terms": ["Summer 2027"], "locations": ["NYC"],
               "url": f"https://example.com/{i}", "date_posted": NOW - 600,
               "sponsorship": "Other", "degrees": ["Bachelor's"], "company_url": None}
    listing.update(over)
    return listing


def check_simplify_collector(tmp):
    h = Home(tmp, "simplify").setup()
    web = os.path.join(tmp, "web")
    path = os.path.join(web, "Owner", "Repo", "dev", ".github", "scripts")
    os.makedirs(path)
    with open(os.path.join(path, "listings.json"), "w", encoding="utf-8") as fh:
        json.dump([raw_listing(1), raw_listing(2, company="Unlisted Co")], fh)
    server = serve_directory(web)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        code, out, _ = h.jw("source", "add", "simplify:Repo", "--command",
                            f"python -m jw.collectors.simplify Owner/Repo --base-url {url}")
        code, out, _ = h.jw("sync", "run")
        posting = h.postings("zenith")["postings"][0]
        keys = [s["source"] for s in h.posting(posting["id"])["sources"]]
        check("the built-in Simplify collector feeds the same pipeline as a hand-written one",
              code == 0 and scalar(out, "new_listings") == "2" and keys == ["simplify:Repo"])
        check("and the untracked company is counted, not dropped", scalar(out, "unresolved") == "1")
    finally:
        server.shutdown()
        server.server_close()
    code, out, _ = h.jw("sync", "run")
    check("when the site is unreachable the collector exits 3 and sync reports UPSTREAM_UNAVAILABLE",
          code == 3 and scalar(out, "code") == "UPSTREAM_UNAVAILABLE")


def check_mcp(tmp):
    h = Home(tmp, "mcp").setup()
    sample = os.path.join(h.root, "sample.jsonl")
    with open(sample, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obs("adhoc", "m:1")) + "\n")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "jw_ingest", "arguments": {"file": sample}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "jw_source_list", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "jw_schema_observation", "arguments": {}}},
    ]
    code, out, _ = run_jw("mcp", env=clean_env(JW_HOME=h.root), cwd=h.cwd, python_path=REPO,
                          stdin=jsonl(messages))
    replies = {r["id"]: r for r in (json.loads(l) for l in out.splitlines() if l)}
    check("an agent can ingest through MCP with a file argument",
          "observations: 1" in replies[2]["result"]["content"][0]["text"])
    check("and the server keeps answering afterwards, so no tool call consumed its stdin",
          set(replies) == {1, 2, 3, 4} and "count: 0" in replies[3]["result"]["content"][0]["text"])
    check("the contract is one tool call away", "fields[" in replies[4]["result"]["content"][0]["text"])


def check_shims():
    routine = os.path.join(REPO, "routine")
    sys.path.insert(0, routine)
    try:
        import normalize as shim_normalize
        import reconcile as shim_reconcile
        from sources import simplify as shim_simplify
    finally:
        sys.path.remove(routine)
    from jw import normalize as jw_normalize
    check("the routine's reconcile, normalize and Simplify adapter are the jw modules",
          shim_reconcile is reconcile and shim_normalize is jw_normalize
          and shim_simplify is simplify)


def load_legacy():
    spec = importlib.util.spec_from_file_location("legacy_run", os.path.join(REPO, "routine", "run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPANIES = ["Zenith", "Orbit Capital", "Jane Street", "Acme Corp", "Globex", "Initech", "Hooli"]
CATEGORIES = ["Software", "Software Engineering", "Quant", "Quantitative Finance", "AI/ML/Data",
              "Data Science, AI & Machine Learning", "Hardware", "Product", None, "Weird"]
TITLES = ["Software Engineer Intern", "Quantitative Researcher", "ML Research Scientist",
          "FPGA Engineer", "Data Analyst", "Backend Engineer, New Grad", "Product Manager Intern"]
PLACES = [["NYC"], ["SF", "Remote in USA"], ["McLean, VA"], [], ["London"], ["Remote in USA"]]


def generate(rng, start, count, recent_fraction=0.3):
    listings = []
    for i in range(start, start + count):
        recent = rng.random() < recent_fraction
        listings.append({
            "id": f"L{i:05d}", "source": "Simplify", "company_name": rng.choice(COMPANIES),
            "title": f"{rng.choice(TITLES)} {i}", "category": rng.choice(CATEGORIES),
            "locations": rng.choice(PLACES), "active": rng.random() < 0.85,
            "is_visible": rng.random() < 0.9, "terms": ["Summer 2027"],
            "url": f"https://example.com/{i}", "sponsorship": "Other", "degrees": [],
            "company_url": None,
            "date_posted": NOW - (rng.randint(600, 6 * 3600) if recent
                                  else rng.randint(40 * 3600, 30 * 86400)),
        })
    return listings


FILTER_SETS = (
    {},
    {"categories": ["Software"]},
    {"categories": ["Quant", "AI/ML/Data"], "locations": ["NYC"]},
    {"title_keywords": ["intern", "research"], "active_only": False},
    {"visible_only": False, "locations": ["remote"]},
)
WATCHLISTS = ([], ["jane street", "acme corp"])


def check_filter_parity(legacy):
    rng = random.Random(7)
    listings = generate(rng, 0, 400)
    repo = "Owner/Repo"
    mismatches = 0
    for filter_set in FILTER_SETS:
        for watchlist in WATCHLISTS:
            for listing in listings:
                expected = legacy.passes_filters(listing, filter_set) or (
                    legacy.matches_watchlist(listing["company_name"], watchlist)
                    and legacy.passes_active_visible(listing, filter_set))
                got = filters.surfaces(simplify.observation(listing, repo, NOW), filter_set, watchlist)
                mismatches += expected != got
    check(f"the surfacing rules agree with the legacy engine on {len(listings) * 10} decisions",
          mismatches == 0)


def lines_of(text):
    return {re.sub(r"  \(.*\)$", "", line) for line in text.splitlines() if line.startswith("•")}


def check_digest_parity(tmp, legacy):
    rng = random.Random(11)
    repo, branch, path = "Owner/Repo", "dev", ".github/scripts/listings.json"
    before = generate(rng, 0, 300)
    added = generate(rng, 300, 80, recent_fraction=0.5)
    flipped = [dict(l, active=not l["active"]) for l in before[:25]]
    after = flipped + before[25:] + added
    for n, (filter_set, watchlist) in enumerate(((FILTER_SETS[1], ["jane street"]),
                                                  (FILTER_SETS[2], []),
                                                  (FILTER_SETS[0], ["acme corp"]))):
        source = {"repo": repo, "branch": branch, "listings_path": path, "filters": filter_set,
                  "known_ids": sorted(l["id"] for l in before)}
        legacy._RAW_CACHE[(repo, branch, path)] = json.dumps(after)
        survivors, _ = legacy.process_source(
            source, set(), argparse.Namespace(raw_only=True, fixture=None), watchlist)
        legacy_text = legacy.build_slack_message({repo: survivors}, watchlist)

        h = Home(tmp, f"parity-{n}").setup()
        for term in watchlist:
            h.jw("watchlist", "add", term)
        seed = [simplify.observation(l, repo, NOW) for l in before]
        h.jw("ingest", "--source", "simplify:Repo", "--no-tracker", stdin=jsonl(seed))
        h.write("collectors/feed.py", SIMPLIFY_FEED)
        h.write("data/feed.json", json.dumps(after))
        h.jw("source", "add", "simplify:Repo", "--command", "python collectors/feed.py",
             "--filters", json.dumps(filter_set))
        code, body = h.json("sync", "run", "--full")
        new_ids = sorted(x["id"] for x in body["listings"])
        check(f"the digest surfaces exactly the listings the legacy engine did ({len(survivors)} of "
              f"{len(added)} new, filters {sorted(filter_set)}, watchlist {watchlist})",
              new_ids == sorted(s["id"] for s in survivors))
        check("and the digest lines are identical", lines_of(body["digest_text"] or "") == lines_of(legacy_text))

    for n, filter_set in enumerate((FILTER_SETS[1], FILTER_SETS[3])):
        source = {"repo": repo, "branch": branch, "listings_path": path, "filters": filter_set,
                  "known_ids": []}
        legacy._RAW_CACHE[(repo, branch, path)] = json.dumps(after)
        survivors, _ = legacy.process_source(
            source, set(), argparse.Namespace(raw_only=True, fixture=None), [])
        h = Home(tmp, f"baseline-{n}").setup()
        h.write("collectors/feed.py", SIMPLIFY_FEED)
        h.write("data/feed.json", json.dumps(after))
        h.jw("source", "add", "simplify:Repo", "--command", "python collectors/feed.py",
             "--filters", json.dumps(filter_set))
        code, body = h.json("sync", "run", "--full")
        check(f"a first run matches the legacy baseline seed ({len(survivors)} surfaced, "
              f"{len(source['known_ids'])} ids recorded)",
              sorted(x["id"] for x in body["listings"]) == sorted(s["id"] for s in survivors)
              and h.counts()["observed"] == len({l["id"] for l in after}))


def canonical(postings, crosswalk, events):
    ordered = sorted(postings, key=lambda p: min(
        (k, (v.get("external_id") or "")) for k, v in p["sources"].items()))
    names = {p["posting_id"]: f"P{n}" for n, p in enumerate(ordered)}
    return (
        sorted(({**p, "posting_id": names[p["posting_id"]]} for p in postings),
               key=lambda p: p["posting_id"]),
        {kind: {k: names[v] for k, v in crosswalk[kind].items()} for kind in crosswalk},
        [{**e, "posting_id": names[e["posting_id"]]} for e in events],
    )


def check_tracker_parity(tmp):
    def o(source, ext, company, title, **over):
        record = schema.normalize(obs(source, ext, company=company, title=title, **over), NOW)
        return record

    companies = [
        {"id": "zenith", "display_name": "Zenith", "aliases": {"*": ["Zenith"]}, "tier": None,
         "careers_url": None, "levels_url": None, "notes": ""},
        {"id": "orbit", "display_name": "Orbit Capital", "aliases": {"*": ["Orbit Capital"]},
         "tier": None, "careers_url": None, "levels_url": None, "notes": ""},
    ]
    t1, t2, t3 = NOW - 3000, NOW - 2000, NOW - 1000
    batches = [
        (t1, [o("s1", "z1", "Zenith", "Kernel Engineer Intern"),
              o("s1", "z2", "Zenith", "Compiler Intern"),
              o("s1", "o1", "Orbit Capital", "Quant Trader Intern"),
              o("s2", "x1", "Orbit Capital", "Quant Trader Intern")]),
        (t2, [o("s1", "z1", "Zenith", "Kernel Engineer Intern II"),
              o("s1", "z2", "Zenith", "Compiler Intern", state_raw={"active": False}),
              o("s2", "x1", "Orbit Capital", "Quant Trader Intern")]),
        (t3, [o("s1", "z2", "Zenith", "Compiler Intern"),
              o("s1", "z3", "Zenith", "New Role Intern", level="new-grad", terms=[]),
              o("s1", "o1", "Orbit Capital", "Quant Trader Intern",
                state_raw={"is_visible": False})]),
    ]

    counter = iter(range(10 ** 6))
    tracker = os.path.join(tmp, "parity-tracker")
    for when, batch in batches:
        reconcile.reconcile([dict(b) for b in batch], companies, tracker, when,
                            mint_id=lambda: f"legacy-{next(counter)}")

    con = db.connect(os.path.join(tmp, "parity.db"))
    db.init(con)
    for seq, c in enumerate(companies):
        con.execute(importer.COMPANY_INSERT, importer.company_row(seq, c))
    for when, batch in batches:
        ingest.apply(con, [dict(b) for b in batch], lambda s: dict(ingest.DEFAULT_CONFIG), [], when)
        con.commit()

    identical = True
    for company in companies:
        cid = company["id"]
        cdir = os.path.join(tracker, "companies", cid)
        with open(os.path.join(cdir, "postings.json"), encoding="utf-8") as fh:
            legacy_postings = json.load(fh)["postings"]
        with open(os.path.join(cdir, "crosswalk.json"), encoding="utf-8") as fh:
            legacy_crosswalk = json.load(fh)
        with open(os.path.join(cdir, "events.jsonl"), encoding="utf-8") as fh:
            legacy_events = [json.loads(l) for l in fh if l.strip()]
        ours = canonical(exporter.postings_document(con, cid)["postings"],
                         exporter.crosswalk_document(con, cid), exporter.event_records(con, cid))
        theirs = canonical(legacy_postings, legacy_crosswalk, legacy_events)
        identical = identical and json.dumps(ours, sort_keys=True) == json.dumps(theirs, sort_keys=True)
    check("the store's reconciliation produces exactly the postings, crosswalk and events the "
          "file-based reconciler does across updates, closes and reopens", identical)
    types = {e["type"] for e in exporter.event_records(con, "zenith")}
    check("and the batches covered opened, updated, closed and reopened",
          {"opened", "updated", "closed", "reopened"} <= types)


def main():
    tmp = tempfile.mkdtemp(prefix="jw-ingest-")
    try:
        check_schema(tmp)
        check_ingest(tmp)
        check_lifecycle(tmp)
        check_collectors(tmp)
        check_sync_lock(tmp)
        check_baseline_and_filters(tmp)
        check_registry(tmp)
        check_legacy_adoption(tmp)
        check_shared_namespace(tmp)
        check_simplify_collector(tmp)
        check_mcp(tmp)
        check_shims()
        legacy = load_legacy()
        check_filter_parity(legacy)
        check_digest_parity(tmp, legacy)
        check_tracker_parity(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish()


if __name__ == "__main__":
    sys.exit(main())
