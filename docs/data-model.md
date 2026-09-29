# Data model

Exact schemas for every JSON file. The two committed files are the persistent state;
the upstream file is read-only input.

## `sources.json` (committed state + config)

A JSON array, one object per watched upstream repo. Generic by design so non-Simplify
sources can be added later.

```json
[
  {
    "repo": "SimplifyJobs/Summer2027-Internships",
    "branch": "dev",
    "listings_path": ".github/scripts/listings.json",
    "last_sha": null,
    "last_run_timestamp": null,
    "known_ids": [],
    "filters": {
      "categories": [],
      "title_keywords": [],
      "locations": [],
      "active_only": true,
      "visible_only": true
    }
  }
]
```

| Field | Type | Meaning |
|-------|------|---------|
| `repo` | string | `owner/name` of the upstream repo. |
| `branch` | string | Branch to read — **`dev`** for both Simplify repos. |
| `listings_path` | string | Path to the listings file in that repo. |
| `last_sha` | string \| null | Newest commit SHA processed by the commits-API path. Unused in `--raw-only` mode (stays `null`). |
| `last_run_timestamp` | int \| null | Unix seconds of the last successful run for this source. Metadata + first-run seed boundary; **not** the dedup mechanism (see architecture.md). |
| `known_ids` | string[] | Every listing `id` ever seen for this source. The compact dedup set (ids only, not full objects) and the authoritative dedup guard. Kept sorted. |
| `filters` | object | Declarative filter block, below. |

### `filters`

| Field | Type | Semantics |
|-------|------|-----------|
| `categories` | string[] | Match if the listing's normalized category is in this set. **Empty = permissive** (match all). Use canonical names: `Software`, `AI/ML/Data`, `Hardware`, `Quant`, `Product`. |
| `title_keywords` | string[] | Case-insensitive substring match against `title`. Empty = permissive. |
| `locations` | string[] | Case-insensitive substring match against the joined `locations`. Empty = permissive. |
| `active_only` | bool | Drop `active == false` listings. Default true, always enforced. |
| `visible_only` | bool | Drop `is_visible == false` listings. Default true, always enforced. |

## `watchlist.json` (committed config — companies of interest)

A flat JSON array of company-name substrings you always want to hear about. **Global**
(applies to every source) and **optional** — a missing, empty, or malformed file means
"no companies of interest," i.e. exactly the pre-watchlist behavior.

It is kept **in sync with the tracker's 100-company list** (`tracker/companies.json`):
the watchlist is the union of every alias across all tracked companies, so the digest
pins exactly the companies the tracker follows. When you add/remove a tracked company or
change its aliases, regenerate this file so the two stay aligned.

```json
["Jane Street", "Jane Street Capital", "Citadel", "Citadel Securities"]
```

| Aspect | Behavior |
|--------|----------|
| Match | Case-insensitive **exact** match against a listing's `company_name` (surrounding whitespace trimmed). Not substring — `"meta"` will **not** catch `"Metabolic"`. If a company can appear multiple ways, list each as its own entry (`"Meta"`, `"Meta Platforms"`, `"Facebook"`). |
| Bypass | A watchlist match **skips the `categories` / `title_keywords` / `locations` gate** — an out-of-category role at a company you care about is still surfaced. `active_only` / `visible_only` are **still enforced** (a dead listing helps nobody). |
| Highlight | Matches are pinned in a `⭐ Companies of interest` section at the top of the Slack digest (tagged with their source repo) and omitted from their per-source group, so they don't get buried. |
| Ping | When that section is non-empty, the digest leads with a Slack `@channel` ping (`<!channel>`) so watchlist hits are hard to miss. Regular (non-watchlist) digests stay quiet. |

Edit it by hand or conversationally ("add Stripe to my watchlist"). No code change needed.

## `seen_listings.json` (committed tracking store)

A JSON array of surfaced listings with application status. Starts as `[]`. New survivors
are appended; conversational status updates edit entries in place.

```json
{
  "id": "98b2d671-3f03-430e-b18c-e5ddb8ce5035",
  "source_repo": "SimplifyJobs/Summer2027-Internships",
  "company_name": "Capital One",
  "title": "Product Development Intern",
  "category": "Software",
  "locations": ["McLean, VA", "Plano, TX"],
  "url": "https://example.com/job/123",
  "date_posted": 1690430400,
  "date_first_seen": 1751856000,
  "status": "new",
  "status_updated": null,
  "notes": ""
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Upstream listing UUID. The dedup / lookup key. |
| `source_repo` | string | Which source it came from. |
| `company_name`, `title`, `locations`, `url` | | Display fields, copied from upstream. |
| `category` | string | **Normalized** category (see architecture.md). |
| `date_posted` | int | Upstream Unix timestamp (seconds). |
| `date_first_seen` | int | When our routine first surfaced it (Unix seconds). |
| `status` | enum | `new` \| `applied` \| `interviewing` \| `rejected` \| `offer` \| `skip` \| `closed`. `closed` means the user found the posting closed. |
| `status_updated` | int \| null | When status last changed (Unix seconds); null until first change. |
| `notes` | string | Free-text, user-supplied. |

### Conversational status updates

In a normal session, the user says what happened ("I applied to Capital One", "rejected
by Stripe", "interviewing with Databricks"). Claude finds matching entries by
`company_name` (disambiguating if several match), sets `status` + `status_updated`,
optionally appends to `notes`, and commits. No automation involved.

## Upstream `listings.json` (read-only input)

Owned by SimplifyJobs; we never write it and never commit it (~11 MB). One entry:

```json
{
  "source": "Simplify",
  "category": "Software",
  "company_name": "General Dynamics Mission Systems",
  "id": "7816c941-1cc9-457b-bf37-cdef34d20a8e",
  "title": "Intern Engineer",
  "active": false,
  "terms": ["Winter 2025"],
  "date_updated": 1762674554,
  "date_posted": 1762674554,
  "url": "https://careers-gdms.icims.com/jobs/68654/job",
  "locations": ["Annapolis Junction, MD"],
  "company_url": "https://simplify.jobs/c/General-Dynamics-Mission-Systems",
  "is_visible": true,
  "sponsorship": "Other",
  "degrees": []
}
```

Fields we rely on: `id` (dedup), `date_posted` (window), `active` / `is_visible`
(filtering), `category` (normalized filtering), and the display fields. `sponsorship`
(values include `Other`, `Offers Sponsorship`, `Does Not Offer Sponsorship`, `U.S.
Citizenship is Required`) and `degrees` are available but not currently used — candidates
for future filters. The file is **pretty-printed**, which is what makes per-commit patch
parsing reliable (see architecture.md). Note: there is **no compensation/pay field**
upstream — the tracker's `pay` is always null (reserved for a future source / manual edit).

# Company posting tracker (`tracker/`)

A second, additive store that tracks the **full posting history** of a curated company
list, independent of the digest filters, and feeds the GitHub Pages viewer (`docs/`). It is
**source-agnostic**: any feed is mapped to a normalized *Observation* by a collector (the
built-in Simplify one is `jw/collectors/simplify.py`), then `jw/reconcile.py` resolves it into
three layers — canonical entities, a crosswalk, and an append-only event history. Adding a
source touches only the collector. See `docs/architecture.md` for the reconciler design.

## `tracker/companies.json` (committed config — owned by `main`)

The curated companies. `aliases` is either a list (any source) or `{source_or_"*": [...]}`.
Multiple aliases per company guard against upstream spelling drift.

```json
{ "id": "meta", "display_name": "Meta", "tier": "A",
  "careers_url": "https://www.metacareers.com/jobs",
  "levels_url": "https://levels.fyi/companies/facebook",
  "aliases": { "*": ["Meta", "Meta Platforms", "Facebook"] }, "notes": "" }
```

The list is the **top 100 companies by levels.fyi elo unioned with the watchlist** (elo
itself is not stored — used only to select the 100 and band the tiers). Bytedance-style
duplicates collapse by slug; TikTok is the one watchlist company outside the top 100.

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | Slug; the canonical company id and its store directory name. |
| `tier` | string | `S` / `A` / `B` / `C` — drives UI grouping/sort. Banded by elo rank (S = top ~10, A = ~11–35, B = ~36–70, C = ~71–100; watchlist-only extras → `C`). |
| `careers_url` | string | Optional careers page link (empty when unknown). |
| `levels_url` | string \| null | levels.fyi company page; surfaced as a link in the viewer. `null` where the source had none (e.g. DeepMind, Renaissance, TikTok). |
| `aliases` | list \| object | Case-insensitive exact match on the raw upstream `company_name`; a suffix-stripped loose match is the fallback. |

## `tracker/companies/<slug>/postings.json` (routine-generated state)

Canonical postings, one per real advertisement (grain = a source's stable id). Written as
`{ "company_id": slug, "postings": [ ... ] }`.

```json
{ "posting_id": "<internal uuid>", "company_id": "meta",
  "role_key": "meta::intern::software-engineer", "level": "intern",
  "title": "Software Engineer Intern", "terms": ["Summer 2027"],
  "locations": ["Menlo Park, CA"], "apply_url": "https://...",
  "posted_at": 1783404634, "first_seen": 1785457945, "last_seen": 1785457945,
  "closed_at": null, "state": "open", "pay": null,
  "sources": { "simplify:Summer2027-Internships":
      { "external_id": "3c77…", "url": "…", "state": "active",
        "first_seen": 1785457945, "last_seen": 1785457945 } },
  "attributes": { "category": "Software", "sponsorship": "Other", "degrees": [] } }
```

| Field | Type | Notes |
|-------|------|-------|
| `posting_id` | string | Internal uuid; the durable canonical id. |
| `role_key` | string | Derived `company::level::title-slug` (rebuildable; groups postings into roles in the UI). |
| `terms` | string[] | Canonical `"<Season> <Year>"`; `["New Grad"]` when no season / new-grad level. |
| `state` | string | `open` if **any** source reports active, else `closed`. Closes **only** on a source's inactive/not-visible flag — a listing merely disappearing from a feed does **not** close it (`last_seen` just stops advancing). |
| `closed_at` | int \| null | Set when `state` transitions to closed; cleared on reopen. |
| `sources` | object | Per-source view (id, url, state, first/last seen). Multiple sources can back one posting. |
| `pay` / `attributes` | | `pay` reserved-null; `attributes` is a source-specific bag (no schema migration when a source adds fields). |

## `tracker/companies/<slug>/events.jsonl` (routine-generated history)

Append-only lifecycle **transitions** (JSON Lines — appends never rewrite the file, so
twice-daily commits rarely conflict). Powers the timeline. Only transitions are stored, not
every poll.

```json
{ "at": 1785457945, "posting_id": "…", "role_key": "meta::intern::software-engineer",
  "type": "opened", "source": "simplify:Summer2027-Internships" }
```

`type` ∈ `opened` (at `posted_at`) / `closed` / `reopened` / `updated` (with a
`detail.changed` diff of title/terms/locations/apply_url). Observed transitions are
timestamped at observation time.

## `tracker/companies/<slug>/crosswalk.json` (routine-generated index)

`{ "external": { "<source>|<external_id>": posting_id }, "natural": { "<natural-key>": posting_id } }`.
Resolution tries `external` first, then the normalized `natural` key (so the same real
posting seen from a second source without a shared id merges into one canonical posting).

## `tracker/index.json` (routine-generated manifest)

Landing-page manifest: `{ "generated_at": ts, "companies": [ { slug, display_name, tier,
careers_url, levels_url, posting_count, open_count, last_updated } ] }`.

## `tracker/all_postings.json` (routine-generated catalog aggregate)

The whole corpus in one file, so the Pages catalog can filter and rank every posting
without fetching 100 per-company files on each cold load. Written by
`build_all_postings()` in `jw/reconcile.py` immediately after the index.

`{ "generated_at": ts, "count": n, "postings": [ … ] }`, newest first
(`posted_at` desc, `posting_id` as the tiebreak so the file is byte-stable run to run).
Serialized **without whitespace** — it is ~1.2 MB and nobody reads it by hand.

Field names are abbreviated because the browser downloads the whole thing:

| Key | Source field | Key | Source field |
|-----|--------------|-----|--------------|
| `id` | `posting_id` | `pa` | `posted_at` |
| `co` | `company_id` | `fs` | `first_seen` |
| `rk` | `role_key` | `ls` | `last_seen` |
| `lvl` | `level` | `ca` | `closed_at` |
| `t` | `title` | `s` | `state` |
| `tm` | `terms` | `cat` | `attributes.category`, run through `canonical_category()` |
| `loc` | `locations` | `sp` | `attributes.sponsorship` |
| `u` | `apply_url` | `deg` | `attributes.degrees` |

`sources` and `crosswalk` are **dropped** — the UI has no use for them and they are the
bulk of the on-disk size. `pay` is dropped for the same reason (it is reserved-null).

Two properties matter when reasoning about this file:

- **It is fully derived.** Every run rebuilds it from the per-company `postings.json`
  stores, so unlike the rest of `tracker/` it never needs restoring from the data branch
  — a missing or stale file self-heals on the next run.
- **Its keys are mirrored in the web app** by `RawPosting`/`decodePosting` in
  `web/src/lib/types.ts`. Change one side and you must change the other.

## A home directory (`JW_HOME`)

A home holds one store and its JSON export. Nothing else in the repo or the installed package is
data. `jw init` creates one; `jw doctor` checks one.

```
<home>/
  jobwatcher.db            the working store (SQLite; not committed)
  watchlist.json           companies of interest
  collectors.json          the source registry            (only once a source is registered)
  observed.json            per-source dedup ids           (only once a source has run)
  sources.json             legacy Simplify sources        (only in homes that came from the Routine)
  seen_listings.json       surfaced listings and their status
  tracker/companies.json   tracked companies (config)
  tracker/companies/<slug>/{postings.json,crosswalk.json,events.jsonl}
  tracker/index.json, tracker/all_postings.json    derived read models the site fetches
  collectors/, data/       yours: collector scripts and whatever they read
```

A home is found from `JW_HOME`, then `JOBWATCHER_ROOT` (the old name), then a source checkout that
holds `sources.json` or `jobwatcher.db`, then the platform data directory. The store is the source
of truth; every JSON file above except `collectors/` and `data/` is regenerated from it by
`jw export site`, and `jw db import` rebuilds a store from them. `jw db verify` proves the two
agree byte for byte.

## `collectors.json` (exported source registry)

A JSON array, one object per registered collector, in registration order:

```json
[
  {
    "name": "simplify:New-Grad-Positions",
    "command": ["python", "-m", "jw.collectors.simplify", "SimplifyJobs/New-Grad-Positions"],
    "filters": {"categories": ["Software"]},
    "env": [],
    "track_all": false,
    "seed_hours": 25,
    "timeout_s": 300,
    "max_output_mb": 64,
    "enabled": true,
    "id_namespace": "simplify",
    "created_at": 1790000000
  }
]
```

`name` is also the `source` every Observation from that collector must carry. `filters` has the
same keys and semantics as `sources.json` (`categories`, `title_keywords`, `locations`,
`active_only`, `visible_only`; empty means permissive). A first `python` in `command` is the
interpreter running `jw`. Run history (`last_status`, `last_error` and so on) is host state kept
in the store only. `id_namespace` groups sources whose ids name the same listings; it is empty
(the source alone) unless set, and `simplify` for the built-in Simplify collectors.

## `observed.json` (exported dedup ids)

`{ "<source>": ["<external_id>", ...] }`, ids in the order they were first seen. It is the
generalisation of `known_ids`: an Observation whose `(source, external_id)` is listed here is not
new, so it never reaches the digest twice. A source with no ids here is on its first run and
surfaces only postings newer than `seed_hours`, so its first sync is not a full dump.

## Observation (what a collector prints)

The contract is defined once, in `jw/schema.py`, and printed by `jw schema observation` (`--full`
for the JSON Schema). `docs/collectors.md` explains how to write a collector against it.

## Schema versions

The store carries `meta.schema_version`; `jw db migrate` applies each pending step in order and
never skips one. The policy:

- A migration only adds tables, columns or indexes. It never rewrites or drops data.
- Any `jw` command other than `db migrate`, `db import` and `doctor` refuses a store older than the
  code (`SCHEMA_OUTDATED`, exit 2) and names the fix. It never migrates on its own.
- The JSON files above stay readable by every later version: new fields are added, none change
  meaning. A file with a field an older `jw` does not know is imported without it.
- Version history: 1 the base tables, 2 applications, 3 profiles and settings, 4 the source
  registry and per-source dedup ids.
