# Tracking your applications

Find the posting, then set a status on it:

```
jw postings query --company acme --title "software engineer"
jw status set <id> --status applied
```

`<id>` accepts a posting id, a listing id, or a short prefix of either — use whatever a
previous list just showed. `--status` is one of `interested`, `applied`, `interviewing`,
`rejected`, `offer`, `skipped`, `closed`. Setting it again updates the same record; there is
only ever one status per posting.

Add context without changing the status:

```
jw notes append <id> --text "recruiter call scheduled for Thursday"
```

Review everything you're tracking:

```
jw applications list
jw applications list --status interviewing
```

Add `--full` to either command for the untruncated record, including every note and the
full status history.

If a posting is closed in a way the feed itself never reports — you heard back informally,
the role was pulled — set `--status closed` yourself. That is the correct way to close a
posting from your side; it doesn't require or wait for the source to say so.
