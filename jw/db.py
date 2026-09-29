import json
import os
import sqlite3

from . import paths

SCHEMA_VERSION = 4

BASE_SCHEMA = """
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE sources (
  repo               TEXT PRIMARY KEY,
  seq                INTEGER NOT NULL,
  branch             TEXT NOT NULL,
  listings_path      TEXT NOT NULL,
  last_sha           TEXT,
  last_run_timestamp INTEGER,
  filters            TEXT NOT NULL
);

CREATE TABLE known_ids (
  repo       TEXT NOT NULL REFERENCES sources(repo) ON DELETE CASCADE,
  listing_id TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  PRIMARY KEY (repo, listing_id)
);

CREATE TABLE listings (
  id              TEXT PRIMARY KEY,
  seq             INTEGER NOT NULL,
  source_repo     TEXT NOT NULL,
  company_name    TEXT,
  title           TEXT,
  category        TEXT,
  locations       TEXT NOT NULL,
  url             TEXT,
  date_posted     INTEGER,
  date_first_seen INTEGER,
  status          TEXT NOT NULL,
  status_updated  INTEGER,
  notes           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX listings_company ON listings(company_name);

CREATE TABLE companies (
  id           TEXT PRIMARY KEY,
  seq          INTEGER NOT NULL,
  display_name TEXT NOT NULL,
  tier         TEXT,
  careers_url  TEXT,
  levels_url   TEXT,
  aliases      TEXT NOT NULL,
  notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE stores (
  company_id    TEXT PRIMARY KEY,
  has_postings  INTEGER NOT NULL DEFAULT 0,
  has_crosswalk INTEGER NOT NULL DEFAULT 0,
  has_events    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE postings (
  posting_id TEXT PRIMARY KEY,
  seq        INTEGER NOT NULL,
  company_id TEXT NOT NULL,
  role_key   TEXT,
  level      TEXT,
  title      TEXT,
  terms      TEXT NOT NULL,
  locations  TEXT NOT NULL,
  apply_url  TEXT,
  posted_at  INTEGER,
  first_seen INTEGER,
  last_seen  INTEGER,
  closed_at  INTEGER,
  state      TEXT NOT NULL,
  pay        TEXT,
  attributes TEXT NOT NULL
);
CREATE INDEX postings_company ON postings(company_id);
CREATE INDEX postings_state ON postings(state);

CREATE TABLE posting_sources (
  posting_id  TEXT NOT NULL REFERENCES postings(posting_id) ON DELETE CASCADE,
  source_key  TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  external_id TEXT,
  url         TEXT,
  state       TEXT,
  first_seen  INTEGER,
  last_seen   INTEGER,
  PRIMARY KEY (posting_id, source_key)
);

CREATE TABLE crosswalk (
  company_id TEXT NOT NULL,
  kind       TEXT NOT NULL,
  key        TEXT NOT NULL,
  posting_id TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  PRIMARY KEY (company_id, kind, key)
);

CREATE TABLE events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  at         INTEGER NOT NULL,
  posting_id TEXT NOT NULL,
  role_key   TEXT,
  type       TEXT NOT NULL,
  source     TEXT,
  detail     TEXT
);
CREATE INDEX events_company ON events(company_id, seq);
CREATE INDEX events_posting ON events(posting_id);
"""

MIGRATIONS = {
    2: """
CREATE TABLE applications (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  posting_id TEXT,
  listing_id TEXT,
  company_id TEXT,
  status     TEXT NOT NULL,
  status_at  INTEGER NOT NULL,
  notes      TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  CHECK (posting_id IS NOT NULL OR listing_id IS NOT NULL)
);
CREATE UNIQUE INDEX applications_posting ON applications(posting_id)
  WHERE posting_id IS NOT NULL;
CREATE UNIQUE INDEX applications_listing ON applications(listing_id)
  WHERE listing_id IS NOT NULL;
CREATE INDEX applications_status ON applications(status);

CREATE TABLE application_history (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  at             INTEGER NOT NULL,
  status         TEXT NOT NULL,
  note           TEXT
);
CREATE INDEX application_history_app ON application_history(application_id, at);
""",
    3: """
CREATE TABLE profiles (
  id         TEXT PRIMARY KEY,
  data       TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
""",
    4: """
CREATE TABLE collectors (
  name              TEXT PRIMARY KEY,
  seq               INTEGER NOT NULL,
  command           TEXT NOT NULL,
  filters           TEXT NOT NULL,
  env               TEXT NOT NULL,
  track_all         INTEGER NOT NULL DEFAULT 0,
  seed_hours        INTEGER NOT NULL DEFAULT 25,
  timeout_s         INTEGER NOT NULL DEFAULT 300,
  max_output_mb     INTEGER NOT NULL DEFAULT 64,
  enabled           INTEGER NOT NULL DEFAULT 1,
  id_namespace      TEXT NOT NULL DEFAULT '',
  created_at        INTEGER NOT NULL,
  last_run_at       INTEGER,
  last_status       TEXT,
  last_error        TEXT,
  last_observations INTEGER,
  last_new          INTEGER
);

CREATE TABLE observed (
  source      TEXT NOT NULL,
  external_id TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  PRIMARY KEY (source, external_id)
);
CREATE INDEX observed_external ON observed(external_id);
""",
}

SCHEMA = BASE_SCHEMA + "".join(MIGRATIONS[v] for v in sorted(MIGRATIONS))


class NoStore(FileNotFoundError):
    pass


def connect(path=None, create=True):
    target = path or db_path_for_connect()
    if not create and not os.path.exists(target):
        raise NoStore(f"no store at {target} - run `jw db import` to build one")
    if create:
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    con = sqlite3.connect(target)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def db_path_for_connect():
    return paths.db_path()


def init(con):
    if schema_version(con) is not None:
        return False
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    con.commit()
    return True


def migrate(con):
    current = schema_version(con)
    if current is None:
        raise RuntimeError("no schema in this database — run `jw db init` or `jw db import`")
    applied = []
    for version in sorted(MIGRATIONS):
        if version > current:
            con.executescript(MIGRATIONS[version])
            con.execute(
                "UPDATE meta SET value=? WHERE key='schema_version'", (str(version),)
            )
            applied.append(version)
    con.commit()
    return applied


def schema_version(con):
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if row is None:
        return None
    row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row["value"]) if row else None


def set_meta(con, key, value):
    con.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value) if not isinstance(value, str) else value),
    )


def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def reset(path=None):
    target = path or paths.db_path()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(target + suffix)
        except FileNotFoundError:
            pass
