# Self-hosted agent, tool layer, and remote UI

> **Status: phases 1-5 built, 6-7 proposed.** The store, the full `jw` CLI, the MCP wrapper
> and the service — reads and writes — exist and are tested (`python jw/test_jw.py`). `jw`
> has zero third-party dependencies, so it runs unchanged wherever you point a scheduler at
> it — a systemd timer, Task Scheduler, cron, or an agent harness's own scheduling. What
> remains is remote access and a documented self-hosted deployment, both of which wait on
> choosing a host — see `architecture.md`.
>
> The tools also stand on their own now: `jw` installs as a package, keeps its data in a home
> directory (`JW_HOME`, see `data-model.md`), and takes postings from any collector that prints
> Observations (`collectors.md`). `sync run` no longer goes through `routine/run.py`.

## What was decided

| Decision | Choice |
|---|---|
| Host | VPS or an always-on laptop — deliberately not settled; the design is host-agnostic Linux |
| Tool interface | CLI subcommands with JSON in/out, plus a thin MCP wrapper. Harness-agnostic |
| Live state | SQLite working store; the site keeps reading generated JSON exports |
| GitHub's role | Backup and history, pushed automatically to `main`; the host disk is primary |
| UI writes | Yes — status set on your phone syncs to every device |
| Remote access | Compared below; Tailscale recommended |
| Notifications | The agent owns them. The engine returns a digest and posts nothing |
| Profiles | Server-side, so the desktop and the phone rank identically |
| Dev and deploy | Development stays on Windows; the host deploys by `git pull` |
| Dependencies | Allowed in `jw/`, the service, and the wrapper. `routine/` stays stdlib-only until phase 7 |

Any MCP-speaking harness attaches the tools and decides *when* things run — Claude Code, or
whatever you point at them. Nothing in this design is specific to one harness. It does not build
a routine; it builds the tools a harness calls, and the service the UI talks to.

## Target shape

```
      +------------------------------------------ host (VPS or laptop) --+
      |                                                                  |
agent |  harness --MCP--> jw-mcp --subprocess--> jw <cmd>  (the CLI)     |
      |                                            |                    |
      |                                             v                    |
      |                                     +---------------+            |
      |                                     | jobwatcher.db |  (SQLite)  |
      |                                     +-------+-------+            |
      |                                             | export             |
      |                                             v                    |
phone-+-- Tailscale --> jw-serve --> static site + /api --> JSON exports |
      |                                                                  |
      |                       git push (backup) ------> GitHub           |
      +------------------------------------------------------------------+
```

Three deliverables, in dependency order: the **CLI**, the **MCP wrapper** over it, and the
**service** that serves the site and the write API.

## 1. The tool layer

### Contract

Every tool is a subcommand of one binary, `jw`, and obeys the same rules:

- **One stream, in TOON.** Everything a command has to say goes to stdout as
  [TOON](https://github.com/toon-format/toon), a compact encoding of the same data that costs
  far fewer tokens than JSON (`jw/toon.py`, verified against the reference encoder). Pass
  `--format json` or set `JW_FORMAT=json` for compact JSON. stderr stays empty; UTF-8 is forced
  on all three streams, so titles survive a Windows pipe.
- **Lists are lean by default.** Three or four columns, 25 rows, with `count`, `total` and any
  useful aggregate (`by_status`, `by_tier`, open counts) so the agent needs no second call.
  `--limit 0` returns every row; `--full` returns every field exactly as stored (epoch
  timestamps, full ids, untruncated text). Long text is clipped with `... [+N chars]`.
- **Empty is explicit.** `count: 0` and `postings: []`, never silence.
- **Ids are prefixes.** Lists show the shortest unique prefix (at least 8 characters) and every
  command that takes an id accepts one. An ambiguous prefix is an `AMBIGUOUS` error that lists
  the candidates.
- **Every response ends with `help[]`**: runnable next steps built from the ids in that output.
  `jw/test_cli.py` parses each suggested command against the real parser.
- **Bare `jw` is a dashboard**: store health, postings and application counts, the newest
  postings, and next steps. Help stays behind `--help`.
- **Errors are one structured payload**: `error`, `code` (`NOT_FOUND`, `AMBIGUOUS`,
  `VALIDATION_ERROR`, `NO_STORE`, `UPSTREAM_UNAVAILABLE`, ...) and `help`. Unknown flags are
  rejected with exit 2 and the command's `--help` as the hint.
- **Exit codes are meaningful.** `0` success, `1` a real failure the agent should report,
  `2` bad arguments, `3` retry later, not a bug (upstream unavailable, or another
  `jw sync run` already holds the advisory lock — `BUSY` in the payload's `code`). A harness
  should be able to branch on the exit code alone, without parsing text.
- **`--dry-run` on everything that writes**, returning the same shape it would have
  written, with `dry_run: true`. This is how a harness previews a destructive action.
- **Idempotent where the domain allows.** Setting a status twice is one outcome, not two
  events. Running the sync twice in a minute is a no-op the second time.
- **No prompting, no interactive input, ever.** A tool that blocks on stdin hangs the agent.

Dependencies are allowed here. The stdlib-only rule was never a preference — it existed
because routine VMs have no `pip`. That constraint dies with the cloud Routine at phase 7,
so until then `routine/run.py` and the `jw/` modules it imports (`reconcile`, `normalize`,
`digest`, `notify`, `collectors`) must stay importable on a bare interpreter, while the rest
of `jw/` is free. Phase 1 happens to need nothing: `sqlite3`
is in the standard library.

### The tools

**Store** — `jw db …`, the store's own lifecycle:

| Tool | Arguments | Effect |
|---|---|---|
| `jw db init` | | create an empty store |
| `jw db import` | `--root --force` | load the committed JSON into it |
| `jw db export` | `--root --dry-run` | write the state files back out |
| `jw db verify` | `--root` | round-trip the JSON and diff — the phase-1 gate |
| `jw db migrate` | `--dry-run` | apply pending schema migrations; what makes "deploy is `git pull`" true |

**Read** — safe, no writes, cheap enough to call freely:

| Tool | Arguments | Returns |
|---|---|---|
| `jw postings query` | `--company --open --since --title --category --limit` | matching postings, slim shape (`--since` takes `7d` / `12h` / `2w` as well as a timestamp) |
| `jw postings show` | `<posting_id>` | one posting with its full event history |
| `jw company show` | `<slug>` | company record, open/closed counts, recent events |
| `jw company list` | | every tracked company, with posting and open counts |
| `jw watchlist list` | | the current watchlist terms |
| `jw applications list` | `--status --company --since` | your application records |
| `jw digest preview` | `--source` | what a sync *would* surface, without writing or posting |
| `jw state show` | | counts, last sync, last export, last push, schema version |

**Write** — each names exactly what it changed:

| Tool | Arguments | Effect |
|---|---|---|
| `jw init` | `--home --starter --git` | create a home: store, config, read models, optionally the starter companies and Simplify sources |
| `jw doctor` | | check the home, store, sources, site and backup; exit 1 when something is broken |
| `jw schema observation` | `--full` | the record a collector prints: fields, example, rules, or the JSON Schema |
| `jw ingest` | `--source --file --dry-run --track-all --strict --no-tracker` | load Observation JSONL from stdin or a file: validate, reconcile, surface, export |
| `jw source add/update/list/remove/enable/disable/run` | `<name> --command --simplify --filters --track-all --timeout --env` | register and run collectors |
| `jw source adopt-legacy` | `--dry-run` | turn `sources.json` entries into collectors, keeping their known ids |
| `jw sync run` | `--source --no-tracker` | run every enabled collector, reconcile, export — and **return** the digest, posting nothing |
| `jw status set` | `<posting_id or listing_id> --status --note` | upsert an application record |
| `jw notes append` | `<posting_id> --text` | append to notes without touching status |
| `jw export site` | `--force` | rebuild `index.json`, `all_postings.json`, `events.jsonl`, `seen_listings.json` |
| `jw slack post` | `--text` or `--digest-since` | post to the webhook |
| `jw git snapshot` | `--push --message` | commit state and push to the backup remote |
| `jw watchlist add/remove` | `<term>` | edit config |
| `jw company add/remove` | `<slug> --alias --tier` | edit the tracked-company list |

`jw sync run` is deliberately one tool, not four. The stages share a single upstream download
(~11 MB) and a consistent view of it; letting a harness interleave them invites a half-applied
run. Sub-stages stay reachable via flags for debugging.

**How `sync run` works.** Each enabled collector runs as a subprocess with a timeout, an output cap
and an allowlisted environment. Its lines are validated, reconciled into the store by the same
`jw/reconcile.py` the cloud Routine uses, screened against the source's `observed` ids, and the
new ones that pass the source's filters or the watchlist become the digest. The store is then
exported. The Routine's engine (`routine/run.py`) is untouched: it still works on the JSON files,
and the parity checks in `jw/test_ingest.py` hold the two to the same digest and the same tracker
state until it is retired. The digest is a query over the `listings` the run wrote, not over
events, because events exist only for tracked companies and the digest also covers the rest.

**Notifications belong to the agent, not the engine.** `jw sync run` returns the digest in its
JSON result and posts nothing; the agent decides whether that is worth a Slack message, a push
notification, or silence, and sends it with `jw slack post` or its own integration. This is a
real change from today, where `run.py` posts the digest itself. It is worth making: notification
policy is judgment, which is exactly the part an agent is for, and it takes the webhook out of
the sync path, so a Slack outage can no longer colour an otherwise successful run.

### The MCP wrapper

`jw-mcp` is a thin MCP server: it enumerates the CLI's subcommands as tools, converts their
flags into a JSON schema, subprocesses them, and returns stdout. It holds **no logic** — if it
does, the CLI has stopped being the real interface.

Why both layers rather than MCP alone:

- The CLI is testable with `subprocess.run` and no harness in the loop, in the same offline
  style as `routine/test_run.py`.
- Cron, a systemd timer, or you at a terminal can drive the exact same surface the agent uses,
  so a bug reproduces identically in both.
- MCP SDKs are a dependency. Confining them to the wrapper keeps the engine stdlib-only, and
  keeps you free to swap harnesses without touching the tools.

**Not every subcommand is an agent tool.** `jw serve` and `jw mcp` block until killed, so the
first agent to call one hangs its own session waiting for a result that never comes. The CLI
names them in `NON_AGENT_COMMANDS`; the wrapper must enumerate around that set rather than
exposing every subcommand it finds.

Discovery is plain MCP over stdio: the harness spawns the server, calls `tools/list`, and gets
the subcommands back as tool definitions. Attaching it to Claude Code is one entry:

```
claude mcp add jw -- jw mcp
```

Any other MCP-speaking harness reads the same server. Nothing about the tools assumes a
particular harness, which is the point of keeping the CLI as the real interface.

**Built in phase 3**, as `jw mcp` rather than a separate `jw-mcp` binary — one thing to install
and version. Two decisions worth keeping:

- **The tools are derived, not declared.** The wrapper walks the CLI's own argparse tree and
  converts each subcommand's flags into a JSON schema: positionals become required arguments,
  `choices` become enums, `store_true` becomes a boolean, a repeatable flag becomes an array. A
  new subcommand becomes an agent tool with no work, and a tool's arguments cannot drift from
  the flags the CLI accepts.
- **The protocol is spoken directly rather than through an SDK.** It is JSON-RPC 2.0 over
  stdio and the surface an agent needs is four methods, so hand-rolling it keeps
  `pip install -e .` dependency-free and keeps the wrapper testable offline by the same harness
  as everything else. If it ever needs more of the spec, swapping in the SDK is one file.

## 2. State: SQLite, with JSON as an export

`sqlite3` ships with Python, so this does **not** break the stdlib-only rule.

Tables, sketched: `postings`, `events` (append-only, mirroring `events.jsonl`), `crosswalk`,
`listings` (today's `seen_listings.json` rows), `applications` (below), `companies`,
`source_state` (`last_sha`, `known_ids`), `runs` (one row per sync: what changed, how long).

What SQLite buys, concretely: your phone marking a job "applied" at 9:07 while a sync rewrites
the corpus cannot corrupt anything. WAL mode plus a busy timeout lets the CLI and the service
hold the database open at once, so no single-writer daemon is needed.

What it costs: state stops being hand-readable and git-diffable, which is a genuine loss —
today you can read a diff and see exactly what a run did. Mitigations: `events.jsonl` stays
append-only and exported every run, and `jw export site` regenerates the JSON files verbatim,
so the committed history stays as legible as it is now.

**Migration is round-trip verified before anything else lands.** Import the JSON, export it
back, diff the result against the originals, require equality modulo key order. That test is
the gate.

## 3. The status model — the real design problem

The write path is not a field copy. The two stores that would need to agree today do not:

| | `seen_listings.json` | UI (`localStorage`) |
|---|---|---|
| Keyed by | Simplify listing UUID | tracker `posting_id` |
| Vocabulary | `new applied interviewing rejected offer skip closed` | `applied interested skipped closed` |
| Covers | whatever the digest filters surfaced | all postings for the 100 tracked companies |

Neither set contains the other. The tracker is filter-independent, so the catalog holds
postings no digest ever surfaced — there is no row to update. Conversely `seen_listings.json`
holds listings from companies the tracker does not track.

**Recommendation: make the application record its own entity**, rather than bolting a status
column onto either store.

```
applications
  id            (own key)
  posting_id    -> tracker posting, nullable
  listing_id    -> simplify listing, nullable    (at least one is set)
  company_id
  status        interested | applied | interviewing | rejected | offer | skipped | closed
  status_at     when it last changed
  notes         free text
  history       append-only status transitions
```

Consequences, stated plainly:

- The union vocabulary supersedes both. `skip` and `skipped` merge; `new` disappears — the
  absence of a record *is* "new", which is what it always meant.
- `seen_listings.json` becomes an **export** of this table joined to listings, so the
  conversational flow ("I applied to Capital One") and its git history keep working unchanged.
- Marking a catalog posting that was never in a digest creates a record with `listing_id` null.
  When a later digest surfaces a matching listing, the crosswalk links it in.
- Existing `jw-status` localStorage entries import on first login, keyed by `posting_id`, so
  nothing already marked is lost.
- `closed` is the user's own finding that a posting is gone, for the case where the feed has
  not caught up. It overrides the tracker's state for reads: `jw postings query --open`,
  `jw postings show` and the company open counts treat a posting with a `closed` record as
  closed, and so does the site. The tracker's own `state`, `closed_at` and events stay
  feed-derived, and clearing the record (or setting another status) makes the posting read as
  the feed says again.
- **Built in phase 2.** `posting_sources.external_id` *is* the Simplify listing id, so the link
  between the two id spaces is real rather than invented: marking a posting finds its listing and
  vice versa, and a record created before its other half exists gains the link on the next touch.
  Statuses already sitting in `seen_listings.json` from the conversational flow are adopted as
  application records on import — losslessly, which the round-trip gate proves.

The alternative — one status field on `listings`, with the UI resolving `posting_id` to
`listing_id` through the crosswalk on every write — is less code now and a dead end the first
time you mark something the digest never surfaced.

## 4. The service and the write API

One process, `jw-serve`: serves the built site, the JSON exports, and a small API.

```
GET    /                                 the built site (docs/ output)
GET    /tracker/...                      exports, unchanged shapes
GET    /api/all_postings.json
GET    /api/company/<slug>/events.jsonl
GET    /api/applications                 your records (replaces the localStorage read)
PUT    /api/applications/<posting_id>    {status, note}
DELETE /api/applications/<posting_id>
GET    /api/profiles                     presets plus your edits
PUT    /api/profiles/<id>                save an edited profile
DELETE /api/profiles/<id>                drop the override, restore the preset
GET    /api/state                        last sync, counts — for a staleness banner
```

**Built in phases 4-5.** `jw serve` runs the site, its data and the write API in one process,
replacing the static-server-plus-worktree dance in `scripts/serve.*`:

```
jw serve                      # http://127.0.0.1:8099/
jw serve --bind 0.0.0.0 --token <secret>
```

Three things worth knowing about it:

- **The site needs no rebuild to work there.** The app fetches `../tracker/...` relative to
  itself; served from `/`, the browser clamps that to `/tracker/...`, which is what the service
  mounts. Same trick as the Vite dev middleware.
- **Only `docs/` and `tracker/` are reachable.** The old static server exposed the whole repo
  root — `seen_listings.json` and `sources.json` included — which was survivable only because
  it was bound to loopback. Those now 404.
- **It refuses to bind a non-loopback address without a token.** A private network is not an
  authorization model; anything on your tailnet would otherwise read your application history.
  A token may arrive as `Authorization: Bearer`, as `?token=`, or as the cookie the service
  hands back after a successful query-param auth, so the page's own fetches carry it.

Web-app changes came in as designed and stayed confined to `store.tsx` plus a new `api.ts`:
`setStatus` is an API call with an optimistic local update, `localStorage` demotes to a cache,
and `config.ts` gained an API base. Profiles and the active-profile choice moved server-side, so
a profile tuned on the desktop is the one the phone ranks with. Marks made before there was a
server are handed to it on first contact, once, guarded by a flag so a later visit against an
empty database cannot resurrect them.

Four decisions worth keeping:

- **The API is optional.** The app probes `./api/health` once and runs in one of two modes.
  Served statically it behaves exactly as it did before phase 5, and the footer says whether
  marks are syncing or staying in that browser. That is what lets the same bundle work from the
  service, a worktree, or the dev server.
- **Writes roll back when they fail.** The optimistic update is reverted and the error surfaced,
  because a click that silently failed to save is worse than one that visibly did not take.
- **Per-device things stay per-device.** The theme and the last-visit stamp describe the
  browser; syncing the latter would make your phone claim you had seen what you saw on the
  desktop.
- **The page speaks the full vocabulary.** It offers three buttons but renders all six statuses,
  because `interviewing` and `rejected` arrive from the conversational flow and dropping them
  would make the page lie.

Auth: a signed session cookie from a single shared secret, or a bearer token in a header. Even
behind Tailscale the API needs auth — a private network is not an authorization model, and
anything on your tailnet could otherwise read your application history. TLS comes from the
access layer below, not from this process.

## 5. Remote access — the comparison

All three assume the service binds loopback and is never port-forwarded directly.

### Tailscale — recommended

A WireGuard mesh between your own devices. `tailscale serve` puts HTTPS in front of the local
service with a real certificate, on a name only your tailnet resolves.

- **Exposure:** nothing is reachable from the public internet. No inbound ports; NAT traversal
  is automatic, so it works from a coffee shop or LTE with no router configuration.
- **Auth:** device-level, through your existing identity provider. Revoking a lost phone is one
  click in the admin console.
- **Cost:** free at this scale.
- **Against it:** every device you browse from needs the client installed and logged in. You
  cannot hand someone a link. If the coordination server is down, new connections fail
  (existing ones survive).
- **Effort:** install on host and phone, then `tailscale serve https / http://127.0.0.1:8099`.

### Cloudflare Tunnel + Access

An outbound-only tunnel from the host to Cloudflare, with a real hostname, gated by Access
policies (email OTP or SSO).

- **Exposure:** no inbound ports either, but the hostname exists publicly and is protected by a
  login rather than by unreachability. A policy misconfiguration is a real exposure, where
  Tailscale's failure mode is "unreachable".
- **Auth:** Access, in front of the app. Works in any browser with no client software — the
  reason to pick it.
- **Cost:** free tier covers this.
- **Against it:** your traffic, including application history, terminates at Cloudflare, who
  can see it. More moving parts (tunnel daemon, DNS, Access policies), each an outage source.

### Public port + reverse proxy

Caddy or nginx with Let's Encrypt and password auth, port-forwarded.

- **Exposure:** an open port on the public internet, found by scanners within hours. Every
  vulnerability in the proxy, the app, and the auth layer is yours to patch, promptly.
- **Auth:** whatever you build, including rate limiting, lockout, and credential hygiene.
- **For it:** no third party, works from any device, full control.
- **Against it:** the only option with a bad worst case. Not worth it for a single-user app.

**Recommendation: Tailscale.** If the no-client-software requirement ever becomes real, add
Cloudflare Access alongside it rather than replacing it. Tailscale Funnel can expose a single
path publicly if you later want to share one page.

## 6. GitHub's role after the move

The host disk is primary. `jw git snapshot --push` commits state and pushes on a cadence you
choose — after every sync, or daily.

- State goes to `main`. The `claude/`-prefix restriction disappears once you hold the
  credentials, and one branch is the simpler mental model. It costs roughly 250 KB/run of churn
  in your history, which is the accepted trade — `git log -- routine/` still reads cleanly, and
  the data branch's whole reason for existing was a restriction that no longer applies.
- No branch-overlay dance is needed at all: the host has one checkout, and code updates are
  `git pull`.
- Use a deploy key or a fine-grained PAT scoped to this repo, not an account-wide token.

## 7. Development and deployment

Development stays on Windows; the host deploys by `git pull`. Nothing in the design depends on
that split, but two implementation rules keep it true: no OS-specific paths in the engine — the
database location comes from config or an environment variable, never a hardcoded path — and
nothing that assumes a particular filesystem case sensitivity. `routine/test_run.py` already
runs identically on both, and the CLI must too.

The host holds one checkout on `main`. A deploy is `git pull`, then `jw db migrate` when the
schema has moved.

The CLI installs as a console entry point: `pip install .` (or `pip install -e .` while
developing) puts `jw` on PATH on either OS. The wheel bundles the built site and the starter
data, so `jw init` then `jw serve` work with no checkout. Data lives in the home (`JW_HOME`), never
next to the code; a checkout that holds `sources.json` or `jobwatcher.db` is treated as its own
home so an existing setup keeps working.

## 8. Scheduling

Not the agent's job, and not this design's either — the harness decides when. What the host
provides is a timer (systemd, or Task Scheduler on Windows) that invokes the harness or
`jw sync run` directly. Both paths call the same tool, which is the point of the CLI layer.

## 9. Migration path

Each phase is independently useful and independently revertible. Nothing is deleted until the
phase after it proves out.

| Phase | What lands | Proof it worked |
|---|---|---|
| 1 | SQLite schema + import/export — **done** | round-trip clean across 252 files |
| 2 | `jw` CLI over the existing engine — **done** | 83 offline checks; a no-op sync leaves every state file byte-identical |
| 3 | `jw mcp` wrapper — **done** | a real client initializes, lists 23 tools, and calls one |
| 4 | `jw serve`, read-only — **done** | the site and its data load from the service; the repo root does not |
| 5 | Write API + UI wiring — **done** | a PUT over HTTP is visible to the CLI and reaches `seen_listings.json` |
| 6 | Tailscale, timer, auto-push | a full day runs unattended |
| 7 | Retire the cloud Routine | two consecutive clean days on the host first |

## 10. Invariants

**Kept:** dedup and reconcile on `id`, never display fields. Empty filter array = permissive.
A posting closes only on an explicit inactive flag. Source-agnostic tracker storage.

**Retired, deliberately:**

- *"This repo IS the database."* The host is; the repo becomes backup and audit trail.
- *"A static site has no write path back to the repo."* It has one now, through the service.
  `architecture.md` needs rewriting when phase 5 lands, not before.
- *Routine VMs are stateless.* No longer true, which is what removes the overlay complexity.
- *Stdlib-only everywhere.* Now scoped to `routine/`, and only until phase 7 — see § 1.

## 11. Still open

Nothing blocking. Two implementation choices to settle alongside the code they affect:

1. **Where the API secret lives** — an environment file read at startup, or a row in the
   database. Leaning the env file at `0600`, so a database backup never carries a credential.
2. **How much digest formatting stays in the engine.** `build_slack_message()` currently owns
   the layout, including the 40k-character split. The engine should keep producing structured
   digest data either way; whether it also keeps producing Slack-shaped text, or hands the agent
   raw data to write its own message, is worth deciding once an agent is actually in the loop.
