# Writing a collector

A collector is any program that prints job postings as JSON lines on stdout. `jw` runs it, checks
every line, tracks the postings, and puts the new ones in the digest. Anything that can print
JSON works: Python, Node, a shell script around `curl`, a compiled binary.

## The contract

`jw schema observation` prints the fields, an example and the rules; `--full` prints the JSON
Schema. One line looks like this:

```json
{"source": "acme-careers", "external_id": "acme-careers:4711", "company_raw": "Acme Corp",
 "title_raw": "Software Engineer Intern", "level": "intern", "terms": ["Summer 2027"],
 "locations": ["New York, NY"], "url": "https://acme.example/careers/4711",
 "posted_at": 1790000000, "extra": {"category": "Software"}}
```

Four fields are required: `source`, `external_id`, `company_raw`, `title_raw`. The rules:

- Print one JSON object per line on stdout. Send logs and diagnostics to stderr.
- Set `source` to the name you register the collector under, on every line.
- Make `external_id` stable across runs and unique across all your sources. Prefix short numeric
  ids with the source name, and use the posting URL when the site has no id. Two sources that
  list the same jobs under the same ids (the two Simplify repos do) register with one
  `--id-namespace`, and a job both carry reaches the digest once; without it a reused id is
  rejected.
- Print every posting the source lists right now on every run. `jw` works out what is new. A
  posting that disappears from the feed stays open; set `state_raw.active` or
  `state_raw.is_visible` to `false` only when the source says the posting is closed.
- Use epoch seconds for `posted_at`, never milliseconds.
- Put anything else under `extra`. `category` (Software, AI/ML/Data, Hardware, Quant, Product),
  `sponsorship` and `degrees` feed the site filters and the digest filters.
- Exit 0 on success. Exit 3 when the site is unreachable so `jw sync run` reports
  `UPSTREAM_UNAVAILABLE` and the run can be retried. Any other exit discards the whole run.

## Try it

```
python collectors/acme.py | jw ingest --source acme-careers --dry-run    # check the lines
jw source add acme-careers --command "python collectors/acme.py"        # register it
jw source run acme-careers --dry-run                                     # run it, write nothing
jw sync run                                                              # run every source
```

`jw ingest` rejects a bad line with its line number and the field to fix, and still applies the
good lines; add `--strict` to apply nothing when any line is bad. Write collector scripts under
`<home>/collectors/` and use forward slashes in `--command`; it runs with the home as its working
directory.

## What `jw` does with the output

1. Every line is validated against the schema.
2. Each company name is matched to a tracked company by alias. Names that match nothing are counted
   and the most frequent are shown, never silently dropped. Pass `--track-all` to `jw source add`
   (or `jw source update NAME --track-all true`) to create a tracked company for each unmatched
   name, or `jw company add SLUG --alias NAME` to track one.
3. Tracked postings are reconciled into a history: opened, updated, closed and reopened events.
4. Postings whose `(source, external_id)` were never seen become digest candidates. They pass if
   they satisfy the source's filters (`--filters '{"categories": ["Software"]}'`) or the company is
   on the watchlist.
5. A source's first run has no history, so only postings newer than `--seed-hours` (25) are digest
   candidates. Everything is still tracked, so the next run starts from a clean baseline.
6. The store is exported, so the site and `jw git snapshot` see the new data.

`--track-all` suits sources that list up to a few hundred companies. On a whole Simplify repo it
creates about 3,900 companies and 20,000 postings, so a sync takes about 30 seconds and the home
grows to about 120 MB. For a feed that size, track the companies you care about instead.

## How a collector is run

- **Environment.** Only `PATH`, home and temp variables, locale, proxy and certificate variables
  are passed on, plus `JW_HOME`, `JW_SOURCE` (its name) and any variable named with
  `--env NAME`. Secrets such as `SLACK_WEBHOOK_URL` are not passed unless declared.
- **Limits.** `--timeout` seconds (300 by default) and `--max-output-mb` of stdout (64). Stdin is
  closed.
- **Failures** are recorded per source and shown by `jw source list` and `jw doctor`:

| Status | Meaning |
|---|---|
| `ok` | ran, every line accepted |
| `partial` | ran; some lines were rejected or reused another source's id, and the rest were applied |
| `failed` | exited non-zero or could not start |
| `upstream_unavailable` | exited 3 |
| `timeout` | did not exit within the timeout |
| `output_too_large` | printed more than the cap |
| `invalid` | printed lines, none valid |

A source that fails ingests nothing; the other sources in the same `jw sync run` still do.

## Built-in collectors

`jw source add --simplify OWNER/REPO` registers `python -m jw.collectors.simplify OWNER/REPO`,
which prints a SimplifyJobs listings repo as Observations. `jw init --starter` registers the two
Simplify repos the Routine watches. `jw source adopt-legacy` turns the entries in `sources.json`
into collectors and keeps their known ids, so the first sync after adopting them surfaces only what
the Routine had not yet seen.
