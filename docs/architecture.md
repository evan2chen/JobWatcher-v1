# Architecture

How JobWatcher detects new listings and turns them into a digest. All logic lives in
`routine/run.py`; this document explains the *why* so future changes don't have to
reverse-engineer it.

## The core problem

Two upstream repos (`SimplifyJobs/Summer2027-Internships`,
`SimplifyJobs/New-Grad-Positions`) each hold a ~11 MB `listings.json` on their `dev`
branch, updated by a bot roughly every 30 minutes. We want the *newly added* listings
each day, filtered to the user's criteria, without re-downloading 11 MB every run and
without ever missing or double-counting a listing.

The ground truth for "new" is the listing **`id`** — a stable UUID. Everything reconciles
on `id`.

## Verified upstream facts

Confirmed by inspecting live data (not just trusting the original handoff):

- Default branch is **`dev`**; source file is **`.github/scripts/listings.json`**.
- The file is **pretty-printed** (multi-line, indented), *not* minified. This matters:
  a newly-inserted listing is a contiguous run of added lines forming a complete
  `{ ... }` block, so unified-diff patches parse cleanly into whole objects.
- The live schema carries fields the original handoff omitted — notably **`category`**
  (plus `sponsorship`, `degrees`). See `data-model.md`.
- `category` values are inconsistent (`Software` vs `Software Engineering`, `Quant` vs
  `Quantitative Finance`, etc.) and are normalized before use — see `CATEGORY_CANON` in
  `run.py`.
- Volume at time of writing: ~15k/~17k total entries, ~1.3k/~2.0k active.

## Per-source algorithm

For each source in `sources.json`, `process_source()` does:

1. **Gate cheaply.** `list_recent_commits()` asks the GitHub commits API which commits
   touched `listings.json` on `dev` in the last `LOOKBACK_HOURS` (25h — a deliberate
   >24h overlap; dedup on `id` makes overlap harmless). If the newest commit SHA equals
   the stored `last_sha`, nothing changed — skip. This is the only step that hits the
   commits API, and its responses are tiny.

2. **Baseline seed (first run, `last_sha is null`).** Fetch the full file once via
   `raw.githubusercontent.com`, record *every* current `id` into `known_ids`, set
   `last_sha` to HEAD, and surface only listings with `date_posted` within the lookback
   window. This avoids a multi-thousand-item dump on day one while still showing
   something recent.

3. **Incremental (have `last_sha`).** Collect the commits between `last_sha` and HEAD.
   For each, `added_objects_from_commits()` pulls the commit's patch for the listings
   file and `objects_from_added_lines()` reconstructs whole listing objects from the
   `+` lines (works because the file is pretty-printed — see below). Candidates are
   deduped against `known_ids`.

4. **Fallback.** If any commit's patch is missing or truncated (GitHub omits patches for
   very large diffs), `process_source()` fetches the full file via raw and
   `new_objects_from_full_file()` computes `current_ids − known_ids`. This is
   bulletproof (pure set difference) and is also the only path exercisable in a
   scope-restricted Claude session, since raw works when the API doesn't.

5. **Filter, record, mutate state** in `_finalize()`: run each candidate through
   `passes_filters()`, convert survivors with `to_seen_entry()`, add ids to `known_ids`,
   set `last_sha = HEAD`. A global `seen_ids` set (built from `seen_listings.json`)
   guards against re-surfacing across sources or prior runs.

After all sources: if there are survivors, build a compact Slack message
(`build_slack_message()`) and POST it (`post_slack()`); if none, stay **silent**. Then
write `sources.json` and `seen_listings.json` back (unless `--dry-run`).

Slack silently truncates a message's `text` field at 40,000 chars (and recommends
staying under 4,000), so `post_slack()` doesn't post the digest as one blob — it runs
the text through `split_slack_message()`, which breaks it into parts of ≤3,900 chars
**on line boundaries** (a listing is never cut mid-line), and posts them in sequence.
When there's more than one part each is tagged with a `(part i/n)` footer. A heavy run
(a big backfill surfacing hundreds of listings) therefore posts a few messages instead
of a single clipped one.

`_finalize()` also stamps `source["last_run_timestamp"] = now` on every successful source
run (see below).

## Raw-only mode (`--raw-only`) — the production path

The commits-API flow above is elegant but **cannot run in the deployed routine**:
`api.github.com` requests to the SimplifyJobs repos are **scope-blocked by Anthropic's
GitHub proxy** ("not enabled for this session"), in interactive sessions *and* routine VMs
alike, and no token bypasses it. `raw.githubusercontent.com`, however, is allowlisted and
works.

So the routine runs `python routine/run.py --raw-only`, which for each source:

1. Fetches the full file via `fetch_full_listings_raw()` (no auth needed).
2. `select_raw_candidates()` picks candidates — a pure, unit-tested function:
   - **Seed** (`known_ids` empty): record *every* id, surface only those posted within the
     25h window.
   - **Incremental**: surface every listing whose `id` isn't in `known_ids` — an
     authoritative id-diff that also catches listings Simplify **backfills with an older
     `date_posted`** (a purely timestamp-windowed selector would miss those).
3. `_finalize()` filters, records survivors, updates `known_ids` and `last_run_timestamp`.

This never touches `last_sha` or the commits API. Because upstream commits every ~30 min,
the commits-API gate would essentially never short-circuit anyway, so raw-only loses
nothing in practice — it just fetches ~11 MB per source per run (negligible for a
twice-daily job).

**Auto-fallback:** even in the default mode, if `list_recent_commits()` raises the
scope-block 403 (detected by `_is_scope_block()`), `process_source()` degrades to the
raw-only path instead of skipping the source. The routine still passes `--raw-only`
explicitly for predictability, but the default mode is robust too.

### `last_run_timestamp` and why `known_ids` stays authoritative

`sources.json` carries a `last_run_timestamp` per source, updated on every successful run.
It records when a source was last processed and bounds the first-run seed window, and it
makes the system legible under schedule changes. It is deliberately **not** used as the
dedup mechanism: selecting "new" purely by `date_posted > last_run` would miss backfilled
listings and would violate the repo's core **dedup-on-`id`** invariant. So `known_ids`
remains the correctness guarantee (no misses, no double-sends regardless of run timing);
`last_run_timestamp` is complementary metadata.

## Why patch-parsing over full-file diffing

Full-file diffing (fetch 11 MB, set-difference the ids) is dead simple and bulletproof —
and it's the fallback. But doing it every run is wasteful when the commits API can tell
us cheaply whether anything changed and each ~30-min commit carries only a handful of new
listings. So the primary path is: cheap gate → small per-commit patches → whole objects
for free (pretty-printed file). The full-file path is reserved for first-run seeding and
patch-truncation fallback.

## The patch → object extractor

`objects_from_added_lines()` is the one non-obvious piece. It:

1. Keeps only `+` lines (dropping the `+`), skipping `+++` file headers.
2. Scans the concatenated added text tracking brace depth **while respecting string
   literals** (so a `{` or `}` inside a URL or title doesn't break balancing).
3. Emits each top-level balanced `{ ... }` that `json.loads` accepts and that has an
   `id`.

Consequence: a *wholly-added* listing (the common case — a new posting) reconstructs
perfectly. A *modified* existing listing (e.g. one field flipped) won't brace-balance
into a full object and is skipped — correctly, because its `id` is already in
`known_ids`. If parsing is ever ambiguous, the id-set-difference fallback is the
backstop.

## Filtering semantics

`passes_filters()` applies, per source:

- `active_only` / `visible_only` — always enforced (default true); drop closed/hidden.
- `categories` / `title_keywords` / `locations` — enforced **only if the array is
  non-empty**. Empty array = permissive (match everything). Category is normalized
  before comparison; keywords and locations are case-insensitive substring matches.

This "empty = permissive" rule is deliberate: the user starts with everything and narrows
by hand-editing `sources.json`, with no risk of an unset filter silently dropping all
listings.

## Company posting tracker (source-agnostic layer)

Separate from the digest, the tracker maintains the **full posting history** of a curated
company list (`tracker/companies.json`), independent of the digest filters, and feeds the
Pages site. Its guiding principle: **storage is modelled on the domain, not on any
source.** Three layers (schemas in `data-model.md`):

1. **Canonical** — Companies, derived Roles, Postings. Source-independent; what the UI reads.
2. **Crosswalk** — `(source, external_id)` and a normalized natural-key → `posting_id`. All
   source-specific identity lives here, so a second source describing the same real posting
   merges into one canonical posting (with two entries in its `sources` map).
3. **History** — append-only lifecycle *transition* events (`events.jsonl`). Transitions
   only (not every poll) keep the twice-daily-cloned repo small.

**Ingestion contract.** Each source is a collector: a program that prints normalized
*Observations* as JSON lines (`jw schema observation`, `docs/collectors.md`). The built-in
Simplify adapter lives in `jw/collectors/simplify.py`. `jw/reconcile.py` consumes
Observations from any collector identically, whether `jw ingest` feeds it into the store or the
cloud Routine feeds it files (`routine/reconcile.py` is a shim for the same module): resolve company (aliases) → resolve posting
(external id, else natural key, else mint) → merge lifecycle → emit events → update
crosswalk. Adding a job board is one collector; storage, reconciler, and site are unchanged.
`jw/normalize.py` holds the deterministic normalizers both `role_key` and the natural
key depend on (so grouping is rebuildable if the heuristic improves).

**Lifecycle rules.** A posting closes **only** on an explicit source inactive/not-visible
flag — disappearing from a feed freezes `last_seen`, it does not close (a disappearance is
not informative). Canonical `state` is open if *any* source reports active. A new source id
is a **new posting** (its own `opened`); `reopened` fires only when the same posting goes
active again. It reuses the digest's cached raw download, so it adds no network cost.

## Presentation layer (`tracker/all_postings.json` + `web/`)

The canonical stores are shaped for *writing*: one directory per company, so a run touches
only the companies that changed and `events.jsonl` can be appended to. The site needs the
opposite shape — every posting at once, to search and rank across all 100 companies. Rather
than distort the storage model to suit the UI (or make the browser issue 100 requests), the
reconciler emits **one derived read model**, `tracker/all_postings.json`, at the end of each
run: the whole corpus, slimmed to the fields the UI uses, with short keys. It is a cache, not
state — it is rebuilt wholesale every run and self-heals if lost.

The app in `web/` is a React SPA built with Vite into `docs/`, served locally with `jw serve`
and reading its JSON from the same origin. Its two pages sit on either side of that corpus:

- **Landing** applies a *profile* — keyword include/exclude over the title, ANDed with facet
  constraints — to the open postings and ranks the survivors into a must-apply list. Presets
  live in `web/src/lib/profiles.ts`; user edits are saved as per-preset overrides in
  `localStorage`, so a preset added in a later release still appears for existing users.
- **Catalog** is the same corpus with search, faceting, and the ported company grid and
  per-company history.

Application status **used to be `localStorage` only**, because a static site had no write
path back to the repo. Phase 5 of `docs/self-hosting.md` built one: `jw serve` exposes a small
API, and a status set on any device lands in the SQLite store, from which `seen_listings.json`
is exported in its original vocabulary. The conversational flow is unchanged — it still edits
that file, and those edits are adopted as application records on the next import.

The app still runs without the API. Served by a plain static server, it probes once, finds
nothing answering, and falls back to exactly the old behaviour: `localStorage`, per browser,
with a footer that says so. That fallback is why the bundle can be served from a worktree, a
dev server, or the service without three code paths.

One thing deliberately stayed per-device: the theme and the last-visit stamp. Those describe
the browser, not you — syncing the last-visit stamp would make your phone claim you had
already seen postings you only saw on the desktop.

## Design invariants (don't break these)

- **stdlib-only** — runs in a fresh routine VM with no `pip` (engine *and* tracker).
- **Reconcile on `id`**, never on display fields.
- **Empty filter array = permissive**, not "match nothing."
- **Silent on empty digest** — no Slack message when nothing new survives.
- **The repo is the only state** — persist by committing JSON, nothing else.
- **Tracker storage is source-agnostic** — never reshape `tracker/` schemas around one
  source; add an adapter instead. Tracker close/reopen semantics above are load-bearing.

## Testing

`routine/test_run.py` covers every pure function above offline (no network); `jw/test_ingest.py`
covers the live fixture flow and the API-path caveat.
