
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jw import (applications, config, db, exporter, importer, mcp_server,  # noqa: E402
                paths, prefs, query, service, verify)
from tests.fixture import build_tree, dump, write  # noqa: E402

FAILED = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        FAILED.append(label)


def check_tools(con, src, tmp):
    row = con.execute(
        "SELECT * FROM applications WHERE listing_id='a'").fetchone()
    check("adopts an existing seen_listings status as an application",
          row is not None and row["status"] == "applied")
    check("adoption keeps the original timestamp and notes",
          row is not None and row["status_at"] == 9 and row["notes"] == "phone screen")

    by_posting = applications.resolve(con, "p2")
    check("resolving a posting_id finds its listing", by_posting["listing_id"] == "b")
    by_listing = applications.resolve(con, "b")
    check("resolving a listing id finds its posting", by_listing["posting_id"] == "p2")
    check("resolving a posting with no listing leaves it null",
          applications.resolve(con, "p1")["listing_id"] is None)
    try:
        applications.resolve(con, "nope")
        check("unknown id raises UnknownTarget", False)
    except applications.UnknownTarget:
        check("unknown id raises UnknownTarget", True)

    rec, changed = applications.set_status(con, "p2", "applied", note="sent", now=100)
    check("marking a posting creates a record", changed and rec["status"] == "applied")
    check("marking a posting fills in the linked listing", rec["listing_id"] == "b")
    rec, changed = applications.set_status(con, "p2", "applied", now=200)
    check("re-setting the same status changes nothing", changed is False)
    check("and records no second history entry", len(rec["history"]) == 1)
    rec, changed = applications.set_status(con, "b", "interviewing", now=300)
    check("the listing id reaches the same record",
          changed and rec["posting_id"] == "p2" and rec["id"] == 1 + 1)
    check("a real transition is appended to history", len(rec["history"]) == 2)
    try:
        applications.set_status(con, "p2", "banana")
        check("an invalid status is rejected", False)
    except ValueError:
        check("an invalid status is rejected", True)

    rec, created = applications.append_note(con, "p1", "closes Friday", now=400)
    check("a note on an unmarked posting creates it at interested",
          created and rec["status"] == "interested")
    rec, created = applications.append_note(con, "p1", "recruiter replied", now=500)
    check("a second note appends rather than replaces",
          "closes Friday" in rec["notes"] and "recruiter replied" in rec["notes"])
    check("noting does not change status", rec["status"] == "interested")

    applications.set_status(con, "p1", "skipped", now=600)
    check("clearing removes the record", applications.clear(con, "p1") is True)
    check("and takes its history with it",
          con.execute("SELECT COUNT(*) AS n FROM application_history h "
                      "LEFT JOIN applications a ON a.id = h.application_id "
                      "WHERE a.id IS NULL").fetchone()["n"] == 0)
    check("clearing something unmarked is not an error",
          applications.clear(con, "p1") is False)
    applications.append_note(con, "p1", "closes Friday", now=400)
    applications.append_note(con, "p1", "recruiter replied", now=500)

    out2 = os.path.join(tmp, "out2")
    exporter.export_all(con, out2)
    seen = {e["id"]: e for e in
            json.load(open(os.path.join(out2, "seen_listings.json"), encoding="utf-8"))}
    check("application status reaches seen_listings.json in its own vocabulary",
          seen["b"]["status"] == "interviewing")
    check("and carries the timestamp with it", seen["b"]["status_updated"] == 300)
    check("a listing with no application keeps its stored status",
          seen["a"]["status"] == "applied")

    before = con.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
    importer.import_all(con, src, replace=True)
    after = con.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
    check("a replace-import does not touch application records", before == after)
    check("and does not re-adopt what it already adopted",
          con.execute("SELECT COUNT(*) AS n FROM applications WHERE listing_id='a'"
                      ).fetchone()["n"] == 1)
    check("but does refresh the file-backed tables",
          con.execute("SELECT COUNT(*) AS n FROM listings").fetchone()["n"] == 2)

    rows = query.postings_query(con, company="alpha")
    check("postings query finds a company's postings", len(rows) == 2)
    check("postings query respects --open",
          [r["posting_id"] for r in query.postings_query(con, open_only=True)] == ["p2"])
    check("postings query respects --title",
          len(query.postings_query(con, title="b")) == 1)
    check("postings query respects --limit",
          len(query.postings_query(con, limit=1)) == 1)
    check("postings query filters on the category inside attributes",
          len(query.postings_query(con, category="Software")) == 1)
    shown = query.posting_show(con, "p2")
    check("posting show carries sources, events and the application",
          shown["sources"] and shown["events"] and shown["application"] is not None)
    check("posting show returns None for an unknown id",
          query.posting_show(con, "nope") is None)
    check("company list counts postings",
          [c["posting_count"] for c in query.company_list(con) if c["id"] == "alpha"] == [2])
    check("company show returns open counts",
          query.company_show(con, "alpha")["open_count"] == 1)
    check("company show returns None when untracked",
          query.company_show(con, "nope") is None)
    check("applications list filters by status",
          len(applications.list_applications(con, status="interviewing")) == 1)
    check("state show reports the schema version",
          query.state_show(con)["schema_version"] == db.SCHEMA_VERSION)

    check("parse_since reads a span", query.parse_since("7d", now=1000000) == 1000000 - 604800)
    check("parse_since reads a timestamp", query.parse_since("1700000000") == 1700000000)
    check("parse_since passes None through", query.parse_since(None) is None)
    try:
        query.parse_since("soon")
        check("parse_since rejects nonsense", False)
    except ValueError:
        check("parse_since rejects nonsense", True)

    wl = os.path.join(src, "watchlist.json")
    write(wl, json.dumps(["Alpha", "Beta"], indent=2) + "\n")
    check("watchlist add is case-insensitive",
          config.watchlist_add("alpha", src)["changed"] is False)
    check("watchlist add appends a new term",
          config.watchlist_add("Gamma", src)["changed"] is True)
    check("watchlist add really wrote it", "Gamma" in config.watchlist_list(src))
    check("watchlist remove drops it", config.watchlist_remove("gamma", src)["changed"])
    check("watchlist remove reports a miss",
          config.watchlist_remove("nope", src)["changed"] is False)
    check("watchlist dry-run writes nothing",
          config.watchlist_add("Delta", src, dry_run=True)["changed"] is True
          and "Delta" not in config.watchlist_list(src))
    check("company add is idempotent on an already-tracked slug",
          config.company_add("alpha", root=src)["changed"] is False)
    check("company add extends aliases instead of duplicating",
          config.company_add("alpha", aliases=["Alpha Corp"], root=src)["changed"] is True)
    check("company remove keeps the posting history",
          config.company_remove("alpha", root=src)["store_kept"] is True)


def check_user_closed():
    tmp = tempfile.mkdtemp(prefix="jw-closed-")
    try:
        src = os.path.join(tmp, "repo")
        build_tree(src)
        con = db.connect(os.path.join(tmp, "c.db"))
        db.init(con)
        importer.import_all(con, src)

        def open_ids():
            return [r["posting_id"] for r in query.postings_query(con, open_only=True)]

        def alpha_open():
            return [c["open_count"] for c in query.company_list(con) if c["id"] == "alpha"][0]

        check("a posting the feed reports open starts open",
              open_ids() == ["p2"] and alpha_open() == 1)

        rec, changed = applications.set_status(con, "p2", "closed", note="page says closed",
                                               now=100)
        check("closed is an application status", changed and rec["status"] == "closed")
        check("a closed mark removes the posting from --open", open_ids() == [])
        check("a closed mark shows as the posting's state",
              query.postings_query(con, company="alpha")[0]["state"] == "closed")
        check("posting show reports it closed and carries the record",
              query.posting_show(con, "p2")["state"] == "closed"
              and query.posting_show(con, "p2")["application"]["status"] == "closed")
        check("a closed mark lowers the company's open count",
              alpha_open() == 0 and query.company_show(con, "alpha")["open_count"] == 0)
        check("the tracker's own state is left alone",
              con.execute("SELECT state FROM postings WHERE posting_id='p2'"
                          ).fetchone()["state"] == "open")

        applications.set_status(con, "p2", "applied", now=200)
        check("moving to another status reopens it for queries", open_ids() == ["p2"])
        applications.set_status(con, "b", "closed", now=300)
        check("the listing id reaches the same posting",
              open_ids() == [] and applications.find(
                  con, applications.resolve(con, "p2"))["status"] == "closed")
        check("clearing the mark reopens it",
              applications.clear(con, "p2") and open_ids() == ["p2"] and alpha_open() == 1)

        seen_path = os.path.join(src, "seen_listings.json")
        seen = json.load(open(seen_path, encoding="utf-8"))
        for entry in seen:
            if entry["id"] == "b":
                entry.update(status="closed", status_updated=50, notes="role filled")
        dump(seen_path, seen)
        con2 = db.connect(os.path.join(tmp, "legacy.db"))
        db.init(con2)
        importer.import_all(con2, src)
        row = con2.execute("SELECT * FROM applications WHERE listing_id='b'").fetchone()
        check("a closed listing in seen_listings.json is adopted as closed",
              row is not None and row["status"] == "closed" and row["posting_id"] is None)
        check("a record linked only by listing still closes its posting",
              [r["posting_id"] for r in query.postings_query(con2, open_only=True)] == [])

        out = os.path.join(tmp, "out")
        exporter.export_all(con2, out)
        exported = {e["id"]: e for e in
                    json.load(open(os.path.join(out, "seen_listings.json"), encoding="utf-8"))}
        check("closed survives the export in the legacy vocabulary",
              exported["b"]["status"] == "closed" and exported["b"]["status_updated"] == 50)
        con2.close()
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_prefs():
    tmp = tempfile.mkdtemp(prefix="jw-prefs-")
    try:
        con = db.connect(os.path.join(tmp, "p.db"))
        db.init(con)
        check("no overrides to begin with", prefs.get_profiles(con) == {})

        profile = {"id": "swe", "name": "Mine", "include": ["rust"], "exclude": [],
                   "categories": ["Software"], "levels": [], "terms": [], "minTier": None}
        prefs.save_profile(con, "swe", profile, now=10)
        check("a saved override comes back whole",
              prefs.get_profiles(con)["swe"] == profile)
        profile2 = dict(profile, name="Mine v2")
        prefs.save_profile(con, "swe", profile2, now=20)
        check("saving again replaces rather than duplicates",
              prefs.get_profiles(con) == {"swe": profile2})
        check("the store does not interpret a profile",
              prefs.save_profile(con, "odd", {"anything": [1, 2, {"x": None}]},
                                 now=30)["anything"][2] == {"x": None})
        try:
            prefs.save_profile(con, "bad", ["not", "an", "object"])
            check("a non-object profile is rejected", False)
        except ValueError:
            check("a non-object profile is rejected", True)
        check("deleting an override reports it", prefs.delete_profile(con, "swe") is True)
        check("deleting a missing override is not an error",
              prefs.delete_profile(con, "swe") is False)

        prefs.set_setting(con, prefs.ACTIVE_PROFILE, "quant", now=40)
        check("a setting round-trips",
              prefs.get_settings(con)[prefs.ACTIVE_PROFILE] == "quant")
        prefs.set_setting(con, prefs.ACTIVE_PROFILE, "ml", now=50)
        check("a setting is replaced, not appended",
              prefs.get_settings(con) == {prefs.ACTIVE_PROFILE: "ml"})
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_write_api():
    tmp = tempfile.mkdtemp(prefix="jw-write-")
    try:
        root = os.path.join(tmp, "repo")
        build_tree(root)
        write(os.path.join(root, "docs", "index.html"), "<title>x</title>")
        dbpath = os.path.join(tmp, "w.db")
        con = db.connect(dbpath)
        db.init(con)
        importer.import_all(con, root)
        con.close()

        svc = service.Service(("127.0.0.1", 0), root, token=None, db_path=dbpath)
        port = svc.server_address[1]
        threading.Thread(target=svc.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def call(method, path, payload=None):
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            req = urllib.request.Request(base + path, data=data, method=method)
            if data:
                req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8")
                try:
                    return exc.code, json.loads(body)
                except ValueError:
                    return exc.code, {}

        try:
            code, body = call("PUT", "/api/applications/p2",
                              {"status": "applied", "note": "from the phone"})
            check("PUT sets a status", code == 200 and
                  body["application"]["status"] == "applied")
            check("and links the listing through the crosswalk",
                  body["application"]["listing_id"] == "b")
            check("and keeps the note", body["application"]["notes"] == "from the phone")

            code, body = call("PUT", "/api/applications/p2", {"status": "applied"})
            check("re-PUTting the same status is idempotent", body["changed"] is False)

            code, body = call("GET", "/api/applications")
            check("the record is readable straight back", body["count"] == 2)

            code, body = call("PUT", "/api/applications/b", {"status": "interviewing"})
            check("the listing id reaches the same record",
                  body["application"]["posting_id"] == "p2")

            code, body = call("PUT", "/api/applications/p1", {"note": "no status yet"})
            check("a note with no status creates the record at interested",
                  body["application"]["status"] == "interested")

            code, body = call("PUT", "/api/applications/nosuch", {"status": "applied"})
            check("an unknown posting is a 404", code == 404)
            code, body = call("PUT", "/api/applications/p2", {})
            check("a PUT with neither status nor note is a 400", code == 400)
            code, body = call("PUT", "/api/applications/p2", {"status": "banana"})
            check("an invalid status is a 400", code == 400)

            code, body = call("DELETE", "/api/applications/p2")
            check("DELETE clears the mark", code == 200 and body["cleared"] is True)
            code, body = call("DELETE", "/api/applications/p2")
            check("DELETE on an unmarked posting is a 404", code == 404)

            profile = {"id": "swe", "name": "Mine", "include": [], "exclude": [],
                       "categories": [], "levels": [], "terms": [], "minTier": None}
            code, body = call("PUT", "/api/profiles/swe", {"profile": profile})
            check("PUT saves a profile override", code == 200)
            code, body = call("GET", "/api/profiles")
            check("GET returns the overrides", body["overrides"]["swe"] == profile)
            code, body = call("PUT", "/api/settings/active_profile", {"value": "quant"})
            check("PUT saves a setting", code == 200)
            code, body = call("GET", "/api/profiles")
            check("settings ride along with the profiles payload",
                  body["settings"]["active_profile"] == "quant")
            code, body = call("DELETE", "/api/profiles/swe")
            check("DELETE drops the override", body["dropped"] is True)
            code, body = call("PUT", "/api/settings/active_profile", {})
            check("a setting with no value is a 400", code == 400)

            code, body = call("PUT", "/api/nope/x", {"a": 1})
            check("an unknown write endpoint is a 404", code == 404)

            call("PUT", "/api/applications/p2", {"status": "interviewing"})
            con = db.connect(dbpath, create=False)
            rows = applications.list_applications(con)
            check("writes made over HTTP are visible to the CLI", len(rows) == 3)
            exporter.export_all(con, root)
            con.close()
            seen = {e["id"]: e for e in json.load(
                open(os.path.join(root, "seen_listings.json"), encoding="utf-8"))}
            check("and reach seen_listings.json in the legacy vocabulary",
                  seen["b"]["status"] == "interviewing")
        finally:
            svc.shutdown()
            svc.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_write_api_auth():
    tmp = tempfile.mkdtemp(prefix="jw-wauth-")
    try:
        root = os.path.join(tmp, "repo")
        build_tree(root)
        dbpath = os.path.join(tmp, "wa.db")
        con = db.connect(dbpath)
        db.init(con)
        importer.import_all(con, root)
        con.close()

        svc = service.Service(("127.0.0.1", 0), root, token="s3cret", db_path=dbpath)
        port = svc.server_address[1]
        threading.Thread(target=svc.serve_forever, daemon=True).start()

        def put(headers=None):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/applications/p2",
                data=json.dumps({"status": "applied"}).encode("utf-8"),
                method="PUT", headers=headers or {})
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status
            except urllib.error.HTTPError as exc:
                return exc.code

        try:
            check("an unauthenticated write is a 401", put() == 401)
            check("a token lets the write through",
                  put({"Authorization": "Bearer s3cret"}) == 200)
            con = db.connect(dbpath, create=False)
            check("the rejected attempt wrote nothing of its own",
                  con.execute("SELECT COUNT(*) AS n FROM applications "
                              "WHERE posting_id='p2'").fetchone()["n"] == 1)
            con.close()
        finally:
            svc.shutdown()
            svc.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_migration():
    tmp = tempfile.mkdtemp(prefix="jw-migrate-")
    try:
        path = os.path.join(tmp, "old.db")
        con = db.connect(path)
        con.executescript(db.BASE_SCHEMA)
        con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
        con.commit()
        check("a v1 store reports version 1", db.schema_version(con) == 1)
        applied = db.migrate(con)
        check("migrate applies every pending version", applied == [2, 3, 4])
        check("migrate lands on the current version",
              db.schema_version(con) == db.SCHEMA_VERSION)
        check("applications exists after migrating",
              con.execute("SELECT name FROM sqlite_master WHERE name='applications'"
                          ).fetchone() is not None)
        check("so do profiles and settings",
              con.execute("SELECT COUNT(*) AS n FROM sqlite_master "
                          "WHERE name IN ('profiles','settings')").fetchone()["n"] == 2)
        check("migrate is idempotent", db.migrate(con) == [])
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_cli_contract():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp = tempfile.mkdtemp(prefix="jw-cli-")
    try:
        dbpath = os.path.join(tmp, "cli.db")
        env = dict(os.environ, JOBWATCHER_DB=dbpath, JW_FORMAT="json")

        def run(*args):
            return subprocess.run([sys.executable, "-m", "jw", *args], cwd=repo,
                                  capture_output=True, text=True, encoding="utf-8", env=env)

        proc = run("--db", dbpath, "db", "init")
        check("db init exits 0", proc.returncode == 0)
        payload = json.loads(proc.stdout)
        check("stdout is JSON and nothing else", payload["created"] is True)
        check("prose goes to stderr, not stdout", "[jw]" not in proc.stdout)

        proc = run("--db", dbpath, "status", "set", "nosuch", "--status", "applied")
        check("an unknown target exits 2 (bad argument, not a crash)",
              proc.returncode == 2)
        check("and still emits a structured error",
              json.loads(proc.stdout)["code"] == "NOT_FOUND")

        proc = run("--db", dbpath, "status", "set", "x", "--status", "banana")
        check("an invalid status is rejected by the parser", proc.returncode == 2)

        missing = os.path.join(tmp, "missing.db")
        proc = run("--db", missing, "state", "show")
        check("a read against a missing store exits 2", proc.returncode == 2)
        check("and says how to fix it",
              "run `jw db import`" in json.loads(proc.stdout)["error"])
        check("and creates no file", not os.path.exists(missing))

        stub = os.path.join(tmp, "stub.db")
        open(stub, "wb").close()
        proc = run("--db", stub, "db", "import", "--root", tmp)
        check("import works over an empty stub", proc.returncode == 0)
        proc = run("--db", stub, "db", "import", "--root", tmp)
        check("but refuses a populated store without --force", proc.returncode == 1)
        check("naming the store, not the file",
              json.loads(proc.stdout)["error"] == "store already exists")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_mcp():
    tools = mcp_server.tool_definitions()
    names = {t["name"] for t in tools}
    check("every subcommand becomes a tool", len(tools) == 42)
    check("blocking commands are not exposed",
          not any(n.startswith(("jw_serve", "jw_mcp")) for n in names))
    check("tool names are namespaced", "jw_company_show" in names)

    by_name = {t["name"]: t for t in tools}
    schema = by_name["jw_status_set"]["inputSchema"]
    check("a positional becomes a required argument", "id" in schema["required"])
    check("a required flag is required too", "status" in schema["required"])
    check("choices become an enum",
          schema["properties"]["status"]["enum"] == list(applications.STATUSES))
    check("store_true becomes a boolean",
          schema["properties"]["dry_run"]["type"] == "boolean")
    check("an int flag becomes an integer",
          by_name["jw_postings_query"]["inputSchema"]["properties"]["limit"]["type"]
          == "integer")
    check("a repeatable flag becomes an array",
          by_name["jw_company_add"]["inputSchema"]["properties"]["alias"]["type"]
          == "array")
    check("the wire payload carries no internals",
          all(not k.startswith("_") for k in mcp_server._public(by_name["jw_state_show"])))

    argv = mcp_server.build_argv(
        by_name["jw_status_set"],
        {"id": "abc", "status": "applied", "note": "hi", "dry_run": True},
    )
    check("arguments rebuild the command line",
          argv == ["status", "set", "abc", "--dry-run", "--status", "applied",
                   "--note", "hi"])
    check("a false boolean adds no flag",
          "--dry-run" not in mcp_server.build_argv(
              by_name["jw_status_set"], {"id": "a", "status": "applied",
                                         "dry_run": False}))
    check("a repeatable flag repeats",
          mcp_server.build_argv(by_name["jw_company_add"],
                                {"slug": "x", "alias": ["A", "B"]})
          == ["company", "add", "x", "--alias", "A", "--alias", "B"])
    check("absent arguments are omitted",
          mcp_server.build_argv(by_name["jw_company_show"], {"slug": "x"})
          == ["company", "show", "x"])

    calls = []

    def runner(argv):
        calls.append(argv)
        return 0, '{"ok": true}', ""

    out = io.StringIO()
    server = mcp_server.Server(stdin=io.StringIO(), stdout=out, runner=runner)

    def rpc(msg):
        out.seek(0), out.truncate()
        server.handle(msg)
        raw = out.getvalue().strip()
        return json.loads(raw) if raw else None

    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05"}})
    check("initialize echoes the client's protocol version",
          r["result"]["protocolVersion"] == "2024-11-05")
    check("initialize advertises tools",
          "tools" in r["result"]["capabilities"])
    check("a notification gets no reply",
          rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None)
    r = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    check("tools/list returns the tools", len(r["result"]["tools"]) == 42)
    r = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "jw_company_show", "arguments": {"slug": "citadel"}}})
    check("tools/call shells out to the CLI", calls == [["company", "show", "citadel"]])
    check("and passes its JSON straight through",
          json.loads(r["result"]["content"][0]["text"])["ok"] is True)
    check("a successful call is not an error", r["result"]["isError"] is False)
    r = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "jw_nope", "arguments": {}}})
    check("an unknown tool is a protocol error", r["error"]["code"] == -32600)
    r = rpc({"jsonrpc": "2.0", "id": 5, "method": "wat"})
    check("an unknown method says so", r["error"]["code"] == -32601)
    r = rpc({"jsonrpc": "2.0", "id": 6, "method": "resources/list"})
    check("probed-for capabilities answer empty rather than erroring",
          r["result"]["resources"] == [])

    server.runner = lambda argv: (1, '{"ok": false}', "boom")
    r = rpc({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
             "params": {"name": "jw_state_show", "arguments": {}}})
    check("a failing command comes back as isError", r["result"]["isError"] is True)


def check_service():
    check("loopback needs no token", service.check_bind("127.0.0.1", None) is None)
    check("a non-loopback bind without a token is refused",
          service.check_bind("0.0.0.0", None) is not None)
    check("a non-loopback bind with a token is allowed",
          service.check_bind("0.0.0.0", "secret") is None)

    tmp = tempfile.mkdtemp(prefix="jw-serve-")
    try:
        root = os.path.join(tmp, "repo")
        build_tree(root)
        os.makedirs(os.path.join(root, "docs", "assets"), exist_ok=True)
        write(os.path.join(root, "docs", "index.html"), "<title>JobWatcher</title>")
        write(os.path.join(root, "docs", "assets", "app.js"), "console.log(1)")
        write(os.path.join(root, "tracker", "index.json"), '{"companies": []}')
        write(os.path.join(root, "secret.json"), '{"private": true}')

        dbpath = os.path.join(tmp, "svc.db")
        con = db.connect(dbpath)
        db.init(con)
        importer.import_all(con, root)
        con.close()

        started = []
        svc = service.Service(("127.0.0.1", 0), root, token=None, db_path=dbpath)
        port = svc.server_address[1]
        thread = threading.Thread(target=svc.serve_forever, daemon=True)
        thread.start()
        started.append(svc)
        base = f"http://127.0.0.1:{port}"

        def get(path, headers=None):
            req = urllib.request.Request(base + path, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, resp.read().decode("utf-8"), resp.headers
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8"), exc.headers

        try:
            code, body, _ = get("/")
            check("serves the built site at the root",
                  code == 200 and "JobWatcher" in body)
            check("serves the bundle", get("/assets/app.js")[0] == 200)
            code, body, headers = get("/tracker/index.json")
            check("serves the tracker JSON the app fetches", code == 200)
            check("as JSON", "application/json" in headers["Content-Type"])
            check("serves events.jsonl",
                  get("/tracker/companies/alpha/events.jsonl")[0] == 200)
            code, body, _ = get("/api/health")
            check("health reports that writes are available",
                  json.loads(body)["writes"] is True)
            code, body, _ = get("/api/state")
            check("state comes from the store",
                  json.loads(body)["state"]["counts"]["listings"] == 2)
            code, body, _ = get("/api/applications")
            check("applications are readable over HTTP",
                  code == 200 and json.loads(body)["ok"] is True)

            check("the repo root is not served", get("/secret.json")[0] == 404)
            check("seen_listings.json is not served",
                  get("/seen_listings.json")[0] == 404)
            check("traversal out of tracker/ is refused",
                  get("/tracker/%2e%2e/secret.json")[0] in (403, 404))
            check("an unknown endpoint 404s as JSON",
                  get("/api/nope")[0] == 404)
            check("no-store on responses",
                  get("/api/health")[2]["Cache-Control"] == "no-store")
        finally:
            svc.shutdown()
            svc.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_service_auth():
    tmp = tempfile.mkdtemp(prefix="jw-auth-")
    try:
        root = os.path.join(tmp, "repo")
        build_tree(root)
        write(os.path.join(root, "docs", "index.html"), "<title>x</title>")
        dbpath = os.path.join(tmp, "a.db")
        con = db.connect(dbpath)
        db.init(con)
        con.close()

        svc = service.Service(("127.0.0.1", 0), root, token="s3cret", db_path=dbpath)
        port = svc.server_address[1]
        threading.Thread(target=svc.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def get(path, headers=None):
            req = urllib.request.Request(base + path, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, resp.headers
            except urllib.error.HTTPError as exc:
                return exc.code, exc.headers

        try:
            check("no credentials is a 401", get("/api/health")[0] == 401)
            check("a wrong bearer is a 401",
                  get("/api/health", {"Authorization": "Bearer nope"})[0] == 401)
            check("the right bearer is let through",
                  get("/api/health", {"Authorization": "Bearer s3cret"})[0] == 200)
            code, headers = get("/api/health?token=s3cret")
            check("a token in the query works", code == 200)
            check("and hands back a cookie so the page's own fetches carry it",
                  "jw_token=s3cret" in (headers.get("Set-Cookie") or ""))
            check("the cookie alone is accepted",
                  get("/api/health", {"Cookie": "jw_token=s3cret"})[0] == 200)
            check("even the site itself is behind the token",
                  get("/")[0] == 401)
        finally:
            svc.shutdown()
            svc.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tmp = tempfile.mkdtemp(prefix="jw-test-")
    try:
        src = os.path.join(tmp, "repo")
        build_tree(src)

        con = db.connect(os.path.join(tmp, "t.db"))
        db.init(con)
        check("init reports the schema version", db.schema_version(con) == db.SCHEMA_VERSION)
        check("init is idempotent", db.init(con) is False)

        counts = importer.import_all(con, src)
        check("imports both listings", counts["listings"] == 2)
        check("imports every known id", counts["known_ids"] == 3)
        check("imports the collector registry", counts["collectors"] == 1)
        check("imports every observed id", counts["observed"] == 5)
        check("imports postings", counts["postings"] == 2)
        check("imports events including the detail row", counts["events"] == 2)
        check("records a store per company dir", counts["stores"] == 2)

        out = os.path.join(tmp, "out")
        exporter.export_all(con, out)

        for rel in ("sources.json", "seen_listings.json", "collectors.json", "observed.json",
                    os.path.join("tracker", "companies.json"),
                    os.path.join("tracker", "companies", "alpha", "postings.json"),
                    os.path.join("tracker", "companies", "alpha", "crosswalk.json"),
                    os.path.join("tracker", "companies", "alpha", "events.jsonl"),
                    os.path.join("tracker", "companies", "beta", "postings.json")):
            with open(os.path.join(src, rel), "rb") as fh:
                want = fh.read()
            with open(os.path.join(out, rel), "rb") as fh:
                got = fh.read()
            check(f"round-trips {rel.replace(os.sep, '/')} byte for byte", want == got)

        check("does not invent an events.jsonl for a company with none",
              not os.path.exists(os.path.join(out, "tracker", "companies", "beta",
                                              "events.jsonl")))
        check("does not create a store dir for an untracked company",
              not os.path.exists(os.path.join(out, "tracker", "companies", "gamma")))

        exported = json.load(open(os.path.join(out, "sources.json"), encoding="utf-8"))
        check("preserves known_ids order", exported[0]["known_ids"] == ["zzz", "aaa", "mmm"])
        xw = json.load(open(os.path.join(out, "tracker", "companies", "alpha",
                                         "crosswalk.json"), encoding="utf-8"))
        check("preserves crosswalk insertion order",
              list(xw["external"]) == ["simplify:R|b", "simplify:R|e1"])
        posts = json.load(open(os.path.join(out, "tracker", "companies", "alpha",
                                            "postings.json"), encoding="utf-8"))["postings"]
        check("preserves posting file order", [p["posting_id"] for p in posts] == ["p2", "p1"])
        check("keeps pay null rather than dropping it", posts[0]["pay"] is None)

        events = [json.loads(l) for l in
                  open(os.path.join(out, "tracker", "companies", "alpha", "events.jsonl"),
                       encoding="utf-8") if l.strip()]
        check("omits detail when absent", "detail" not in events[0])
        check("keeps detail last when present", list(events[1])[-1] == "detail")
        check_tools(con, src, tmp)
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    check_migration()
    check_cli_contract()
    check_mcp()
    check_service()
    check_service_auth()
    check_user_closed()
    check_prefs()
    check_write_api()
    check_write_api_auth()

    if os.path.isfile(paths.sources_path()):
        result = verify.roundtrip()
        check(f"real repo round-trips ({result['files_compared']} files)", result["ok"])
        if not result["ok"]:
            for m in result["mismatches"][:10]:
                print("   ", m)
    else:
        print("SKIP real-repo round-trip (no sources.json here)")

    print()
    if FAILED:
        print(f"{len(FAILED)} CHECK(S) FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
