# Triage: deciding what matters after a sync

`jw sync run` surfaces everything a source's filters let through. Three tools narrow that
down further, all independent of each other:

**The watchlist** — companies you always want to see, regardless of filters:

```
jw watchlist add "acme"
jw watchlist list
```
A watchlist match is called out in the digest and bypasses a source's own filters.

**Tiers** — your own ranking of tracked companies, for browsing rather than filtering:

```
jw company add acme --tier A --alias "Acme Corp" --alias "ACME Inc"
jw company list
```
`--alias` matters more than `--tier` here: a company only accumulates posting history if
its upstream name (however a source spells it) resolves to a tracked company. List several
aliases for anything that appears under more than one spelling.

**Query filters** — for looking at the corpus itself, not the digest:

```
jw postings query --open --since 7d --category Software
jw postings query --company acme --title "intern"
```

For a first pass after any sync, `jw postings query --open --since 1d` and
`jw applications list --status interested` cover "what's new" and "what I still owe a
decision on."
