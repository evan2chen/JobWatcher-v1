import time

from . import ids, output

POSTINGS_PAGE = 25
APPLICATIONS_PAGE = 25
COMPANIES_PAGE = 100
EVENTS_PAGE = 5
OPEN_POSTINGS_PAGE = 10


class Ctx:
    def __init__(self, con=None, full=False, now=None):
        self.con = con
        self.full = full
        self.now = int(now if now is not None else time.time())
        self._short = None

    def short(self, full_id):
        if self.full or not full_id:
            return full_id
        if self._short is None:
            self._short = ids.ShortIds(self.con)
        return self._short.short(full_id)

    def when(self, ts):
        return ts if self.full else output.age(ts, self.now)

    def text(self, value, limit=output.TEXT_LIMIT):
        return output.clip(value, limit, self.full)

    def block(self, value):
        return output.clip(value, output.BLOCK_LIMIT, self.full)


def _clean(d):
    return {k: v for k, v in d.items() if v is not None}


def dashboard(ctx, store_path, state, overview, newest):
    last_sync = state.get("last_sync")
    payload = {
        "store": output.display_path(store_path),
        "last_sync": ctx.when(int(last_sync)) if last_sync else "never",
        "postings": {
            "total": overview["postings_total"],
            "open": overview["postings_open"],
            f"new_{overview['window_days']}d": overview["postings_new"],
        },
        "companies": overview["companies"],
        "applications": overview["applications_by_status"] or "none",
    }
    if newest:
        payload["newest"] = postings_rows(ctx, newest, with_state=False)
    return payload


def hook_summary(overview):
    return {
        "postings": (f"{overview['postings_total']} total, {overview['postings_open']} open, "
                     f"{overview['postings_new']} new ({overview['window_days']}d)"),
        "applications": overview["applications_by_status"] or "none",
    }


def postings_rows(ctx, rows, with_state):
    out = []
    for r in rows:
        if ctx.full:
            item = {"id": r["posting_id"]}
            item.update({k: v for k, v in r.items() if k != "posting_id"})
        else:
            item = {"id": ctx.short(r["posting_id"]), "company": r["company"],
                    "title": r["title"],
                    "posted": ctx.when(r["posted_at"] or r["first_seen"])}
            if with_state:
                item["state"] = r["state"]
        out.append(item)
    return out


def postings_list(ctx, rows, total, open_only, filters_used):
    payload = {"count": len(rows), "total": total,
               "postings": postings_rows(ctx, rows, with_state=not open_only)}
    help_lines = []
    if rows:
        first = payload["postings"][0]["id"]
        help_lines.append(f"Run `jw postings show {first}` for details and history")
        help_lines.append(f"Run `jw status set {first} --status applied` to record an application")
    elif filters_used:
        hint = "Widen the search: drop a filter"
        if open_only:
            hint += " (--open hides closed postings)"
        help_lines.append(hint)
    else:
        help_lines.append("The store has no postings; run `jw sync run` to fetch some")
    if total > len(rows):
        help_lines.append(
            f"{total - len(rows)} more match; narrow with --company, --title or --since, "
            "or raise --limit")
    payload["help"] = help_lines
    return payload


def posting_detail(ctx, posting):
    application = posting["application"]
    if ctx.full:
        return {"id": posting["posting_id"],
                **{k: v for k, v in posting.items() if k != "posting_id"}}

    payload = _clean({
        "id": ctx.short(posting["posting_id"]),
        "company": posting["company"],
        "title": posting["title"],
        "level": posting["level"],
        "state": posting["state"],
        "posted": ctx.when(posting["posted_at"] or posting["first_seen"]),
        "apply_url": posting["apply_url"],
        "locations": output.join(posting["locations"]),
        "terms": output.join(posting["terms"]),
    })
    payload["application"] = _clean({
        "status": application["status"],
        "updated": ctx.when(application["status_at"]),
        "notes": ctx.text(application["notes"] or None),
    }) if application else "none"
    payload["sources"] = [
        {"source": s["source"], "state": s["state"], "seen": ctx.when(s["last_seen"])}
        for s in posting["sources"]
    ]
    events = posting["events"]
    shown = events[-EVENTS_PAGE:]
    payload["events"] = [
        {"at": ctx.when(e["at"]), "type": e["type"], "source": e["source"]} for e in shown
    ]
    if len(events) > len(shown):
        payload["events_total"] = len(events)
    payload["help"] = [
        f"Run `jw status set {payload['id']} --status applied` to record an application",
        f"Run `jw notes append {payload['id']} --text <note>` to add a note",
        f"Run `jw company show {posting['company_id']}` for the company",
    ]
    return payload


def companies_list(ctx, rows, limit):
    by_tier = {}
    for r in rows:
        key = r["tier"] or "none"
        by_tier[key] = by_tier.get(key, 0) + 1
    shown = rows[:limit] if limit else rows
    if ctx.full:
        items = [{"id": r["id"], "display_name": r["display_name"], "tier": r["tier"],
                  "careers_url": r["careers_url"], "levels_url": r["levels_url"],
                  "aliases": r["aliases"], "open": r["open_count"],
                  "total": r["posting_count"]} for r in shown]
    else:
        items = [{"id": r["id"], "tier": r["tier"], "open": r["open_count"],
                  "total": r["posting_count"]} for r in shown]
    payload = {
        "count": len(shown),
        "total": len(rows),
        "open_postings": sum(r["open_count"] for r in rows),
        "by_tier": by_tier,
        "companies": items,
    }
    help_lines = []
    if shown:
        help_lines.append(f"Run `jw company show {shown[0]['id']}` for a company's open postings")
    else:
        help_lines.append("No companies are tracked; run `jw company add <slug> --alias <name>`")
    if len(rows) > len(shown):
        help_lines.append(f"{len(rows) - len(shown)} more; raise --limit or use --limit 0")
    payload["help"] = help_lines
    return payload


def company_detail(ctx, company, open_rows, open_total):
    if ctx.full:
        return {**company,
                "open_postings": postings_rows(ctx, open_rows, with_state=True)}

    payload = _clean({
        "id": company["id"],
        "name": company["display_name"],
        "tier": company["tier"],
        "open": company["open_count"],
        "total": company["posting_count"],
        "careers_url": company["careers_url"] or None,
        "notes": ctx.text(company["notes"] or None),
    })
    payload["open_postings"] = [
        {"id": r["id"], "title": r["title"], "posted": r["posted"]}
        for r in postings_rows(ctx, open_rows, with_state=False)
    ]
    if open_total > len(open_rows):
        payload["open_postings_more"] = open_total - len(open_rows)
    payload["recent_events"] = [
        {"at": ctx.when(e["at"]), "type": e["type"],
         "posting": ctx.short(e["posting_id"]), "source": e["source"]}
        for e in company["recent_events"][:EVENTS_PAGE]
    ]
    help_lines = []
    if open_rows:
        help_lines.append(
            f"Run `jw postings show {payload['open_postings'][0]['id']}` for a posting")
    help_lines.append(
        f"Run `jw postings query --company {company['id']} --limit 0` for the full history")
    payload["help"] = help_lines
    return payload


def applications_list(ctx, rows, limit):
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    shown = rows[:limit] if limit else rows
    if ctx.full:
        items = shown
    else:
        items = [
            {"id": ctx.short(r["posting_id"] or r["listing_id"]), "company": r["company"],
             "title": r["title"], "status": r["status"]}
            for r in shown
        ]
    payload = {"count": len(shown), "total": len(rows),
               "by_status": dict(sorted(by_status.items())), "applications": items}
    help_lines = []
    if shown:
        first = items[0]["id"] if not ctx.full else (
            shown[0]["posting_id"] or shown[0]["listing_id"])
        help_lines.append(f"Run `jw status set {first} --status interviewing` to move one along")
        help_lines.append(f"Run `jw notes append {first} --text <note>` to add a note")
    else:
        help_lines.append("Nothing recorded yet; run `jw status set <id> --status applied`")
    if len(rows) > len(shown):
        help_lines.append(f"{len(rows) - len(shown)} more; narrow with --status or --company, "
                          "or raise --limit")
    payload["help"] = help_lines
    return payload


def application_result(ctx, joined, history, changed, created=None):
    payload = {"changed": changed}
    if created is not None:
        payload["created"] = created
    identifier = joined["posting_id"] or joined["listing_id"]
    if ctx.full:
        payload["application"] = {**joined, "history": history}
        return payload
    payload.update(_clean({
        "id": ctx.short(identifier),
        "company": joined["company"],
        "title": joined["title"],
        "status": joined["status"],
        "updated": ctx.when(joined["status_at"]),
        "notes": ctx.text(joined["notes"] or None),
    }))
    payload["help"] = [
        f"Run `jw applications list --status {joined['status']}` to see the rest",
        f"Run `jw notes append {payload['id']} --text <note>` to add a note",
    ]
    return payload


def application_preview(ctx, target, status=None, note=None):
    described = ids.describe(ctx.con, target["posting_id"], target["listing_id"])
    payload = {"dry_run": True}
    if ctx.full:
        payload["target"] = target
    else:
        payload["target"] = _clean({"id": ctx.short(described["id"]),
                                    "company": described["company"],
                                    "title": described["title"]})
    if status:
        payload["status"] = status
    if note:
        payload["note"] = ctx.text(note)
    return payload


def state_detail(ctx, state):
    def stamp(value):
        return ctx.when(int(value)) if value else None

    if ctx.full:
        return state
    counts = state["counts"]
    return _clean({
        "db": output.display_path(state["db"]),
        "schema_version": state["schema_version"],
        "last_sync": stamp(state["last_sync"]) or "never",
        "last_export": stamp(state["last_export"]),
        "last_push": stamp(state["last_push"]),
        "counts": {k: counts[k] for k in ("postings", "companies", "listings", "events",
                                          "applications")},
        "applications": state["applications_by_status"] or "none",
    })


def _listing_items(ctx, listings):
    if ctx.full:
        return listings
    shown = listings[:POSTINGS_PAGE]
    return [{"id": ctx.short(x["id"]), "company": x["company_name"], "title": x["title"]}
            for x in shown]


def _source_rows(ctx, rows):
    if ctx.full:
        return rows
    return [
        {"name": r["name"], "status": r["status"], "observations": r.get("observations"),
         "new": r.get("new"), "seconds": r["seconds"]}
        for r in rows
    ]


def sync_result(ctx, result):
    payload = {}
    if result["dry_run"]:
        payload["dry_run"] = True
    payload["new_listings"] = result["new_listings"]
    payload["watchlist_hits"] = result["watchlist_hits"]
    payload["sources"] = _source_rows(ctx, result["sources"])
    if result["by_source"]:
        payload["by_source"] = result["by_source"]

    failures = [{"name": r["name"], "error": ctx.text(r.get("error"), 200)}
                for r in result["sources"] if r.get("error")]
    if failures and not ctx.full:
        payload["failures"] = failures

    problems = [
        {"source": r["name"], "line": e.get("line"), "error": e["error"]}
        for r in result["sources"] for e in (r.get("errors") or []) + (r.get("collisions") or [])
    ]
    if problems:
        shown = problems if ctx.full else problems[:10]
        payload["errors"] = shown
        if len(problems) > len(shown):
            payload["errors_more"] = len(problems) - len(shown)

    listings = result["listings"]
    if listings:
        payload["listings"] = _listing_items(ctx, listings)
        if not ctx.full and len(listings) > POSTINGS_PAGE:
            payload["listings_more"] = len(listings) - POSTINGS_PAGE

    payload["opened"] = result["opened"]
    payload["unresolved"] = result["unresolved"]
    if result["unresolved"]:
        top = result["unresolved_top"]
        payload["unresolved_top"] = top if ctx.full else top[:5]
    if result["created_companies"]:
        payload["created_companies"] = len(result["created_companies"])
    if ctx.full:
        payload["digest_text"] = result["digest_text"]

    help_lines = []
    failed = next((r for r in result["sources"] if r["status"] not in ("ok", "partial")), None)
    if failed:
        help_lines.append(f"Run `jw source run {failed['name']} --dry-run` to see why it failed")
    if result["dry_run"]:
        help_lines.append("Run `jw sync run` to apply this")
    elif result["new_listings"]:
        help_lines.append("Run `jw slack post --digest-since 1d` to post the digest")
        if not ctx.full:
            help_lines.append("Run `jw sync run --full` to include the digest text")
    elif not failed:
        help_lines.append("Nothing new; run `jw postings query --open --since 7d` for recent postings")
    if problems:
        help_lines.append("Run `jw schema observation` for the exact format a collector must print")
    if result["unresolved"]:
        name = result["sources"][0]["name"]
        help_lines.append(
            f"Run `jw source update {name} --track-all true` to track every company, "
            "or `jw company add <slug> --alias <name>` to track one")
    payload["help"] = help_lines
    return payload


def digest_preview(ctx, result):
    payload = {"dry_run": True, "new_listings": result["new_listings"],
               "digest_text": ctx.block(result["digest_text"]) or "none"}
    failures = [{"name": r["name"], "error": ctx.text(r.get("error"), 200)}
                for r in result["sources"] if r.get("error")]
    if failures:
        payload["failures"] = failures
    payload["help"] = ["Run `jw sync run` to apply these"]
    return payload


def ingest_result(ctx, summary, batch, dry_run):
    payload = {}
    if dry_run:
        payload["dry_run"] = True
    payload.update({
        "observations": summary["observations"],
        "rejected": batch.rejected,
        "new": summary["new_observed"],
        "opened": summary["opened"],
        "updated": summary["updated"],
        "closed": summary["closed"],
        "reopened": summary["reopened"],
        "surfaced": len(summary["surfaced"]),
        "unresolved": summary["unresolved"],
    })
    if summary["unresolved"]:
        payload["unresolved_top"] = summary["unresolved_top"]
    if summary["created_companies"]:
        payload["created_companies"] = [c["id"] for c in summary["created_companies"]]
    problems = batch.errors + summary["collisions"]
    if problems:
        shown = problems if ctx.full else problems[:10]
        payload["errors"] = [{"line": e.get("line"), "error": e["error"]} for e in shown]
        if len(problems) > len(shown):
            payload["errors_more"] = len(problems) - len(shown)
    help_lines = []
    if dry_run:
        help_lines.append("Run the same command without --dry-run to apply it")
    if summary["unresolved"]:
        help_lines.append("Add --track-all to create companies from unmatched names, or run "
                          "`jw company add <slug> --alias <name>`")
    if problems:
        help_lines.append("Run `jw schema observation` for the exact format")
    if not dry_run and summary["surfaced"]:
        help_lines.append("Run `jw slack post --digest-since 1d` to post the digest")
    payload["help"] = help_lines
    return payload


def sources_list(ctx, rows):
    enabled = sum(1 for r in rows if r["enabled"])
    if ctx.full:
        items = rows
    else:
        items = [
            {"name": r["name"], "enabled": r["enabled"],
             "status": r["last_status"] or "never run",
             "ran": ctx.when(r["last_run_at"]),
             "observations": r["last_observations"], "new": r["last_new"]}
            for r in rows
        ]
    payload = {"count": len(rows), "enabled": enabled, "sources": items}
    if rows:
        payload["help"] = [f"Run `jw source run {rows[0]['name']} --dry-run` to test a source",
                           "Run `jw sync run` to run every enabled source"]
    else:
        payload["help"] = [
            "Run `jw source add --simplify SimplifyJobs/New-Grad-Positions` to add a source",
            "Run `jw source add <name> --command <cmd>` to register your own collector"]
    return payload


def source_detail(ctx, record, changed):
    payload = {"changed": changed, "name": record["name"],
               "command": " ".join(record["command"]), "enabled": record["enabled"],
               "track_all": record["track_all"]}
    if record["filters"]:
        payload["filters"] = record["filters"]
    if ctx.full:
        payload.update({k: record[k] for k in ("env", "seed_hours", "timeout_s",
                                               "max_output_mb", "id_namespace")})
    payload["help"] = [f"Run `jw source run {record['name']} --dry-run` to test it",
                       "Run `jw sync run` to fetch every enabled source"]
    return payload


def schema_fields(ctx, schema_doc, example, rules):
    if ctx.full:
        return {"schema": schema_doc, "example": example}
    required = set(schema_doc["required"])
    fields = []
    for name, prop in schema_doc["properties"].items():
        kind = prop["type"] if isinstance(prop["type"], str) else "|".join(prop["type"])
        fields.append({"name": name, "type": kind,
                       "required": "yes" if name in required else "no",
                       "description": prop.get("description", "")})
    return {"fields": fields, "example": example, "rules": rules,
            "help": ["Run `jw schema observation --full` for the JSON Schema",
                     "Run `jw ingest --dry-run --file <path>` to test a sample of your output",
                     "Run `jw source add <name> --command <cmd>` to register the collector"]}
