# Contributing

## Setup

```
pip install -e .
cd web && npm install && cd ..   # only if you're touching web/
```

## Before you open a PR

Run the gate:

```
python scripts/check.py
```

It runs every suite in ascending cost order and stops at the first failure. Pass
`--no-browser` to skip the Playwright suite when you haven't touched `web/`.

Touching one area specifically? Its own suite is faster to iterate on:

| Area | Suite |
|---|---|
| The engine (`routine/`) | `python routine/test_run.py` |
| The store and CLI (`jw/`) | `python jw/test_jw.py` |
| CLI output (`jw/cli.py`, `jw/views.py`) | `python jw/test_cli.py` |
| Home, packaging, `jw init`/`jw doctor` | `python jw/test_home.py` (needs network, builds a real wheel) |
| Collectors, ingestion, the Observation contract | `python jw/test_ingest.py` |
| The web app | `cd web && npm run typecheck && npm run smoke` |

Add a check when you add behavior — never make the gate pass by weakening a check.

## Conventions

- **`jw/reconcile.py`, `normalize.py`, `digest.py`, `notify.py`, `jw/collectors/`, and
  `routine/` stay stdlib-only.** No third-party imports there; other code under `jw/` may
  take dependencies freely. See `docs/self-hosting.md`.
- **Command output is built in `jw/views.py`, never in `jw/cli.py`.** A command returns a
  payload dict; `jw/output.py` encodes it as TOON or JSON.
- **A new source is a collector** (`jw source add`, `jw/collectors/`), never a branch in
  `jw/ingest.py`. See `docs/collectors.md`.
- Write comments and documentation as positive instructions — what to do, not what to
  avoid.

## Reporting a bug or requesting a feature

Open an issue. For a security issue, see `SECURITY.md` instead.
