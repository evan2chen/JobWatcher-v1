# Core model and conventions

Three kinds of record, three commands to read them:

- `jw postings query` — the corpus of job postings a source has surfaced. A posting closes
  only when its source explicitly says so; it never closes just because a sync stops seeing
  it.
- `jw company list` / `jw company show <slug>` — companies you track, with their open
  postings and recent lifecycle events (opened, closed, reopened).
- `jw applications list` — your own status on a posting (`interested`, `applied`,
  `interviewing`, `rejected`, `offer`, `skipped`, `closed`). A status belongs here, never on
  a posting: many postings can share one application, and a posting can exist with no
  application at all.

Every command follows the same shape:

- Output is TOON by default (compact, cheap to read as an agent). Pass `--format json` or
  set `JW_FORMAT=json` for JSON instead.
- Lists are lean: a handful of columns, `count`/`total`, and an aggregate like `by_status`.
  Pass `--full` for every field exactly as stored, untruncated.
- Ids print as the shortest unique prefix. Any command that takes an id accepts a prefix of
  it — copy what a list just showed you.
- A response ends with `help[]`: concrete next commands built from what you just saw. Run
  one of them rather than guessing a command's shape.
- Bare `jw` (no arguments) is a dashboard: store health, postings and application counts,
  the newest postings, and next steps.
- Errors are one structured payload with `error`, `code`, and `help`. `NOT_FOUND` and
  `AMBIGUOUS` name what to try next; `AMBIGUOUS` lists the candidates a short id prefix
  matched.

Next: `jw guide track-applications` to record your own progress, or `jw guide triage` to
review what a sync just surfaced.
