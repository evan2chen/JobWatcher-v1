# Notifying yourself

`jw sync run` never posts anywhere on its own — it only returns a digest. You decide
whether and where to send it.

Set the webhook once, on whatever host runs the sync:

```
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

Then, right after a sync:

```
jw sync run --full --format json
```

Read the `digest_text` field from that output. If it's `null`, nothing new was surfaced —
send nothing. If it has text, post exactly that:

```
jw slack post --text "<digest_text, verbatim>"
```

Posting this run's own digest, rather than `jw slack post --digest-since <span>`, is
deliberate: `--digest-since` is a time window, so calling it on every scheduled run would
re-post anything from the last window twice. `digest_text` is scoped to exactly what this
one sync found.

`jw slack post` is one example channel. Anything that can run a shell command and read
stdout can be a notifier: pipe `digest_text` to `ntfy`, a mail command, or a desktop
notification instead of `jw slack post`, using the same "skip if null" rule.
