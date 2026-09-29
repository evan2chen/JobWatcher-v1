import http.server
import json
import mimetypes
import os
import posixpath
import socketserver
import sys
import time
import urllib.parse

from . import applications, db, paths, prefs, query

TOKEN_ENV = "JW_API_TOKEN"
COOKIE = "jw_token"
LOOPBACK = ("127.0.0.1", "::1", "localhost")

TRACKER_SUFFIXES = (".json", ".jsonl")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "jw-serve/0.2"

    def log_message(self, fmt, *args):
        if self.server.verbose:
            sys.stderr.write(f"[jw] {self.address_string()} {fmt % args}\n")

    def _send(self, code, body=b"", content_type="application/json; charset=utf-8",
              extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, body, extra_headers=extra_headers)

    def _authorised(self, query_params):
        token = self.server.token
        if not token:
            return True, None
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer ") and header[7:].strip() == token:
            return True, None
        cookies = self.headers.get("Cookie", "")
        if any(c.strip() == f"{COOKIE}={token}" for c in cookies.split(";")):
            return True, None
        supplied = (query_params.get("token") or [None])[0]
        if supplied == token:
            return True, {"Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax"}
        return False, None

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        ok, cookie_header = self._authorised(params)
        if not ok:
            self._json(401, {"ok": False, "error": "unauthorised",
                             "hint": f"send Authorization: Bearer <{TOKEN_ENV}>"})
            return

        path = posixpath.normpath(urllib.parse.unquote(parsed.path))
        try:
            if path.startswith("/api/"):
                self._api(path, params, cookie_header)
            elif path == "/tracker" or path.startswith("/tracker/"):
                self._tracker(path, cookie_header)
            else:
                self._site(path, cookie_header)
        except BrokenPipeError:
            pass

    def _api(self, path, params, cookie_header):
        if path == "/api/health":
            self._json(200, {"ok": True, "service": "jw-serve",
                             "writes": True, "time": int(time.time())},
                       cookie_header)
        elif path == "/api/state":
            with self.server.store() as con:
                self._json(200, {"ok": True, "state": query.state_show(con)},
                           cookie_header)
        elif path == "/api/applications":
            with self.server.store() as con:
                rows = applications.list_applications(
                    con,
                    status=(params.get("status") or [None])[0],
                    company=(params.get("company") or [None])[0],
                    since=query.parse_since((params.get("since") or [None])[0]),
                )
            self._json(200, {"ok": True, "count": len(rows), "applications": rows},
                       cookie_header)
        elif path == "/api/profiles":
            with self.server.store() as con:
                self._json(200, {"ok": True, "overrides": prefs.get_profiles(con),
                                 "settings": prefs.get_settings(con)}, cookie_header)
        elif path == "/api/settings":
            with self.server.store() as con:
                self._json(200, {"ok": True, "settings": prefs.get_settings(con)},
                           cookie_header)
        else:
            self._json(404, {"ok": False, "error": f"no endpoint {path}"})

    def do_PUT(self):
        self._write("PUT")

    def do_DELETE(self):
        self._write("DELETE")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _write(self, verb):
        parsed = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        ok, cookie_header = self._authorised(params)
        if not ok:
            self._json(401, {"ok": False, "error": "unauthorised"})
            return

        path = posixpath.normpath(urllib.parse.unquote(parsed.path))
        parts = [p for p in path.split("/") if p]
        try:
            body = self._body()
        except ValueError:
            self._json(400, {"ok": False, "error": "body is not valid JSON"})
            return

        try:
            if parts[:2] == ["api", "applications"] and len(parts) == 3:
                self._write_application(verb, parts[2], body, cookie_header)
            elif parts[:2] == ["api", "profiles"] and len(parts) == 3:
                self._write_profile(verb, parts[2], body, cookie_header)
            elif parts[:2] == ["api", "settings"] and len(parts) == 3:
                self._write_setting(verb, parts[2], body, cookie_header)
            else:
                self._json(404, {"ok": False, "error": f"no {verb} endpoint {path}"})
        except applications.UnknownTarget as exc:
            self._json(404, {"ok": False, "error": str(exc)})
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except BrokenPipeError:
            pass

    def _write_application(self, verb, ident, body, cookie_header):
        with self.server.store() as con:
            if verb == "DELETE":
                removed = applications.clear(con, ident)
                self._json(200 if removed else 404,
                           {"ok": removed, "cleared": removed, "id": ident},
                           cookie_header)
                return
            status = body.get("status")
            note = body.get("note")
            if status is None and note:
                record, created = applications.append_note(con, ident, note)
                self._json(200, {"ok": True, "created": created,
                                 "application": record}, cookie_header)
                return
            if status is None:
                raise ValueError("status is required")
            record, changed = applications.set_status(con, ident, status, note=note)
            self._json(200, {"ok": True, "changed": changed, "application": record},
                       cookie_header)

    def _write_profile(self, verb, profile_id, body, cookie_header):
        with self.server.store() as con:
            if verb == "DELETE":
                dropped = prefs.delete_profile(con, profile_id)
                self._json(200, {"ok": True, "dropped": dropped, "id": profile_id},
                           cookie_header)
                return
            data = body.get("profile", body)
            self._json(200, {"ok": True, "id": profile_id,
                             "profile": prefs.save_profile(con, profile_id, data)},
                       cookie_header)

    def _write_setting(self, verb, key, body, cookie_header):
        with self.server.store() as con:
            if verb == "DELETE":
                con.execute("DELETE FROM settings WHERE key=?", (key,))
                con.commit()
                self._json(200, {"ok": True, "key": key}, cookie_header)
                return
            if "value" not in body:
                raise ValueError("value is required")
            self._json(200, {"ok": True, "key": key,
                             "value": prefs.set_setting(con, key, body["value"])},
                       cookie_header)

    def _tracker(self, path, cookie_header):
        rel = path[len("/tracker/"):] if path.startswith("/tracker/") else ""
        if not rel or not rel.endswith(TRACKER_SUFFIXES):
            self._json(404, {"ok": False, "error": "not found"})
            return
        self._file(os.path.join(self.server.tracker_dir, *rel.split("/")),
                   self.server.tracker_dir, cookie_header)

    def _site(self, path, cookie_header):
        rel = path.lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        target = os.path.join(self.server.site_dir, *rel.split("/"))
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        self._file(target, self.server.site_dir, cookie_header)

    def _file(self, target, base, cookie_header):
        real_base = os.path.realpath(base)
        real_target = os.path.realpath(target)
        if real_target != real_base and not real_target.startswith(real_base + os.sep):
            self._json(403, {"ok": False, "error": "forbidden"})
            return
        if not os.path.isfile(real_target):
            self._json(404, {"ok": False, "error": "not found"})
            return
        ctype = mimetypes.guess_type(real_target)[0] or "application/octet-stream"
        if real_target.endswith(".jsonl"):
            ctype = "text/plain; charset=utf-8"
        with open(real_target, "rb") as fh:
            self._send(200, fh.read(), ctype, cookie_header)


class Service(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, root, token=None, verbose=False, db_path=None):
        super().__init__(address, Handler)
        self.root = root
        self.site_dir = paths.site_dir(root)
        self.tracker_dir = os.path.join(root, "tracker")
        self.token = token
        self.verbose = verbose
        self.db_path = db_path

    def store(self):
        return _Store(self.db_path)


class _Store:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.con = db.connect(self.path, create=False)
        return self.con

    def __exit__(self, *exc):
        self.con.close()
        return False


def resolve_token(explicit=None):
    return explicit or os.environ.get(TOKEN_ENV) or None


def check_bind(bind, token):
    if bind in LOOPBACK or token:
        return None
    return (f"refusing to bind {bind} without a token — set {TOKEN_ENV} "
            f"(or pass --token), or bind 127.0.0.1")


def serve(port=8099, bind="127.0.0.1", root=None, token=None, verbose=False,
          db_path=None, ready=None):
    root = root or paths.home()
    service = Service((bind, port), root, token=token, verbose=verbose,
                      db_path=db_path or paths.db_path())
    if ready:
        ready(service)
    try:
        service.serve_forever()
    finally:
        service.server_close()
    return 0
