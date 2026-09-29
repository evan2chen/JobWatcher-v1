import json
import os
import urllib.error
import urllib.request

from . import digest

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
USER_AGENT = "JobWatcher/1.0 (+https://github.com/evan2chen/JobWatcher-v1)"


class NotConfigured(RuntimeError):
    pass


def post_chunk(webhook, text):
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return True, None
    except urllib.error.URLError as exc:
        return False, str(exc)


def post(text, dry_run=False):
    if not text or not text.strip():
        raise ValueError("nothing to post")
    webhook = os.environ.get(WEBHOOK_ENV)
    if not webhook:
        raise NotConfigured(
            f"{WEBHOOK_ENV} is not set - export it on the host before posting"
        )

    chunks = digest.split_slack_message(text)
    if dry_run:
        return {"ok": True, "dry_run": True, "chunks": len(chunks),
                "chars": len(text), "text": text}
    total = len(chunks)
    errors = []
    for index, chunk in enumerate(chunks, 1):
        body = f"{chunk}\n_(part {index}/{total})_" if total > 1 else chunk
        ok, error = post_chunk(webhook, body)
        if not ok:
            errors.append(error)
    return {"ok": not errors, "chunks": total, "chars": len(text), "errors": errors}
