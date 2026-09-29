# JobWatcher

Agent-oriented job tracking: a CLI (`jw`) that fetches postings from any source you point
it at, tracks their full lifecycle, and keeps your own application status alongside — plus
a local web app over the same data.

- **Any source is a collector.** A collector is any program that prints one JSON line per
  posting it currently sees. Two SimplifyJobs feeds ship built in; writing your own for a
  new site is a few lines. See `jw guide write-collector` or `docs/collectors.md`.
- **A posting's lifecycle is tracked, not just its existence.** Opens, updates, closes and
  reopens are all recorded events, source-agnostic — a posting closes only when a source
  explicitly says so, never just because it stopped appearing in a feed.
- **Your application status lives separately from the postings.** One posting, one status
  (`interested` → `applied` → `interviewing` → ...), set with `jw status set` and never
  touched by a sync.
- **Built for an agent to drive.** Every command is TOON or JSON, ends with concrete next
  steps (`help[]`), and `jw guide`/`jw skills install` teach an agent the whole workflow
  without you writing any instructions yourself.

## Install

```
pip install jobwatcher
jw init --starter --git
```

`--starter` seeds a curated company list and two ready-to-run sources; `--git` makes your
new home a git repository so `jw git snapshot` has somewhere to commit to. Data lives in a
home directory (`JW_HOME`, or your platform's data directory by default) — never in the
package.

## Quickstart

```
jw sync run --full     # fetch every registered source, reconcile, print the digest
jw                      # a dashboard: store health, counts, next steps
jw serve                # the site, on http://127.0.0.1:8099/
```

Then, for the full walkthrough:

```
jw guide                       # every topic, one line each
jw guide track-applications    # or any topic by name
```

## Give it to an agent

```
jw skills install    # writes .agents/skills/jw-<topic>/SKILL.md — Claude Code, Codex,
                      # Cursor, Gemini CLI and GitHub Copilot all discover these
jw hooks install      # a terse "what's in the store" line at the start of every
                      # Claude Code session in this project
```

## Notifications

`jw sync run` never posts anywhere on its own — it only returns a digest. `jw slack post`
is one example channel; `jw guide notify` covers wiring up your own.

## The web app

`jw serve` serves a local site over the same store: a ranked "must apply" list per profile,
and a searchable catalog of every posting. It works with no backend too — point a static
file server at a built checkout and it falls back to browser-only marks.

## Security

Collectors run arbitrary code with your privileges, and the write API needs a token off
loopback. See `SECURITY.md`.

## Documentation

- `docs/self-hosting.md` — the CLI, the MCP wrapper, the service, and what's still proposed.
- `docs/data-model.md` — every JSON file's exact schema.
- `docs/collectors.md` — the Observation contract, in depth.
- `CONTRIBUTING.md` — running the gate, and where new behavior needs a new check.

## License

MIT — see `LICENSE`.
