# routine/

The JobWatcher engine. `run.py` is standard-library only (no `pip install` needed),
so it runs unchanged in a fresh cloud Routine VM.

## What it does (per run)

For each source in `../sources.json`:

1. **Gate cheaply** — ask the GitHub commits API whether `listings.json` changed on
   `dev` since ~25h ago. If HEAD already equals the stored `last_sha`, skip.
2. **Baseline seed** (first run, `last_sha: null`) — record every current listing `id`
   into `known_ids`, set `last_sha` to HEAD, and surface only listings posted in the
   last 25h. So day one isn't a 3,000-item dump *and* isn't empty.
3. **Incremental** — pull the patch for each new commit and reconstruct the added
   listing objects (the file is pretty-printed, so a new listing is a clean block of
   `+` lines). Dedup on `id` against `known_ids`. If any patch is truncated, fall back
   to fetching the full file via `raw.githubusercontent.com` and taking the id set
   difference (bulletproof).
4. **Filter** survivors against the source's declarative `filters` (see below).
5. Append survivors to `../seen_listings.json` and update `known_ids` / `last_sha`.

Then, across all sources: if there are new survivors, POST a compact digest to Slack;
if there are none, stay silent. Long digests are split into multiple messages
(≤3,900 chars each, on line boundaries) so Slack's 40,000-char `text` limit never
clips the tail; multi-part posts carry a `(part i/n)` footer.

## Environment variables

| Var | Required | Purpose |
|-----|----------|---------|
| `SLACK_WEBHOOK_URL` | for digests | Slack incoming-webhook URL the digest is POSTed to. |
| `GITHUB_TOKEN` | optional | Only used by the non-`--raw-only` commits-API path (raises the rate limit 60→5000/hr). **The routine runs `--raw-only`, so it needs no token.** |
| `TRACKER_WARN_ON_ZERO` | optional | `1`/`true` logs a warning when a tracked company matches zero listings in a run (possible alias drift). Off by default. |

> Routine env vars are visible to anyone who can edit the environment — keep them minimal.

## Tests

Offline, dependency-free unit tests for the engine internals (patch extraction,
category normalization, the filter matrix, dedup, Slack rendering). No network:

```bash
python routine/test_run.py
```

## Running it manually

```bash
# Full offline-safe smoke test: no writes, no Slack, prints the Slack payload.
python routine/run.py --dry-run

# Diff the live file against a saved snapshot (deterministic, great for testing).
python routine/run.py --fixture /path/to/old_snapshot.json --dry-run

# Only one source.
python routine/run.py --source SimplifyJobs/New-Grad-Positions --dry-run

# Real run but don't post to Slack.
python routine/run.py --no-slack

# Skip the company posting-history tracker (digest only).
python routine/run.py --no-tracker
```

## Company posting tracker

After the digest, each run reconciles the full posting history of the companies in
`../tracker/companies.json` (independent of the digest filters) into per-company stores
under `../tracker/`, reusing the same raw download. It is **source-agnostic**: add a feed by
writing a collector that emits normalized Observations — the reconciler, storage, and the
`docs/` Pages viewer are unchanged. `reconcile.py`, `normalize.py` and `sources/simplify.py`
here are shims: they alias `jw/reconcile.py`, `jw/normalize.py` and `jw/collectors/simplify.py`,
and `run.py` takes its digest formatting and Slack post from `jw/digest.py` and `jw/notify.py`. See
`../docs/data-model.md` and `../docs/architecture.md`.

## Filters (`../sources.json`)

Each source has a declarative `filters` block. **Empty array = no restriction**
(permissive). Tighten by hand any time — no code change needed.

```json
"filters": {
  "categories": ["Software", "AI/ML/Data"],   // normalized; empty = all
  "title_keywords": ["engineer", "developer"], // substring match on title
  "locations": ["Remote", "MD", "DC"],         // substring match on locations
  "active_only": true,                          // drop closed roles
  "visible_only": true                          // drop hidden roles
}
```

Category values are normalized before matching (`Software Engineering` → `Software`,
`Quantitative Finance` → `Quant`, etc.), so you can use the short canonical names.

## Companies of interest (`../watchlist.json`)

A global, optional list of company-name substrings you never want to miss:

```json
["Jane Street", "Capital One", "SpaceX"]
```

A watchlisted company **bypasses** the per-source `categories` / `title_keywords` /
`locations` gate — the role is surfaced even if it's out of your usual criteria (it must
still be active + visible). Matches are **pinned** in a `⭐ Companies of interest` section
at the top of the Slack digest, and that section leads with an `@channel` ping so it's hard
to miss (plain digests stay quiet). Match is case-insensitive **exact** match, so `"meta"`
does **not** catch `"Metabolic"` — list each spelling a company might use as its own entry.
A missing/empty file = no watchlist (current behavior). See
[`../docs/data-model.md`](../docs/data-model.md) for the full schema.

## The Routine wrapper

The scheduled Routine fires twice daily (8am & 5pm PT), runs `python routine/run.py
--raw-only`, and commits its state to the **`claude/jobwatcher-data`** branch — it checks
that branch out first so state persists across the stateless VMs. The full prompt, the
branch-as-database rationale, env vars, and the network allowlist (`raw.githubusercontent.com`
+ `hooks.slack.com`; no GitHub token needed) live in
[`../docs/operations.md`](../docs/operations.md).
