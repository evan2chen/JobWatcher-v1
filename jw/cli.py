import argparse
import os
import sys
import time
import traceback

from . import (agent_hooks, applications, config, db, digest, exporter, gitops, guide,
               home, ids, importer, ingest, notify, output, paths, query, registry,
               schema, skills, sync, views)
from .output import CliError

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_UPSTREAM = 3

NON_AGENT_COMMANDS = frozenset({"serve", "mcp"})

DEBUG_ENV = "JW_DEBUG"


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError("VALIDATION_ERROR", message, exit_code=EXIT_USAGE,
                       help=[f"{self.prog} --help"])


def _use_utf8():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        options = {"encoding": "utf-8", "errors": "replace"}
        if stream is not sys.stdin:
            options["newline"] = "\n"
        reconfigure(**options)


def _open(args):
    target = args.db or paths.db_path()
    con = db.connect(args.db, create=False)
    version = db.schema_version(con)
    if version is None:
        raise db.NoStore(f"{target} has no schema - run `jw db import` to build it")
    if version < db.SCHEMA_VERSION:
        raise CliError("SCHEMA_OUTDATED",
                       f"the store is schema v{version} and this jw needs v{db.SCHEMA_VERSION}",
                       exit_code=EXIT_USAGE, help=["Run `jw db migrate` to upgrade it"])
    return con


def _ctx(args, con=None):
    return views.Ctx(con, full=getattr(args, "full", False))


def cmd_dashboard(args):
    target = args.db or paths.db_path()
    if not os.path.exists(target):
        return {"store": output.display_path(target), "status": "missing",
                "help": _no_store_help()}
    con = db.connect(target, create=False)
    version = db.schema_version(con)
    if version is None:
        return {"store": output.display_path(target), "status": "empty",
                "help": _no_store_help()}
    if version < db.SCHEMA_VERSION:
        return {"store": output.display_path(target), "status": f"schema v{version} is outdated",
                "help": ["Run `jw db migrate` to upgrade it"]}
    ctx = views.Ctx(con)
    state = query.state_show(con, target)
    newest, _ = query.postings_search(con, open_only=True, limit=5)
    payload = views.dashboard(ctx, target, state, query.overview(con), newest)
    payload["help"] = [
        "Run `jw postings query --open --since 7d` to browse recent postings",
        "Run `jw applications list` to review your applications",
        "Run `jw sync run` to fetch new postings",
    ]
    return payload


def _no_store_help():
    return ["Run `jw db import` to build the store from the JSON state",
            "Run `jw db init` for an empty store"]


def cmd_db_init(args):
    con = db.connect(args.db)
    created = db.init(con)
    return {"db": output.display_path(args.db or paths.db_path()), "created": created,
            "schema_version": db.schema_version(con)}


def cmd_db_import(args):
    target = args.db or paths.db_path()
    if os.path.exists(target) and not args.force:
        existing = db.connect(target)
        populated = db.schema_version(existing) is not None
        existing.close()
        if populated:
            raise CliError("ALREADY_EXISTS", "store already exists", exit_code=EXIT_FAIL,
                           db=output.display_path(target),
                           help=["Pass --force to rebuild it from the JSON"])
    if args.force:
        db.reset(target)

    con = db.connect(target)
    db.init(con)
    counts = importer.import_all(con, args.root)
    return {"db": output.display_path(target),
            "root": output.display_path(args.root or paths.home()), "counts": counts}


def cmd_db_export(args):
    con = _open(args)
    root = args.root or paths.home()
    if args.dry_run:
        return {"dry_run": True, "root": output.display_path(root),
                "note": "no files written; re-run without --dry-run"}
    written = exporter.export_all(con, root)
    return {"root": output.display_path(root), "files_written": len(written)}


def cmd_db_verify(args):
    from . import verify
    result = verify.roundtrip(args.root)
    if not result["ok"]:
        mismatches = result["mismatches"]
        raise CliError("ROUNDTRIP_MISMATCH",
                       f"{len(mismatches)} file(s) did not round-trip",
                       exit_code=EXIT_FAIL, mismatches=mismatches[:10],
                       mismatches_total=len(mismatches))
    payload = {"files_compared": result["files_compared"], "mismatches": 0}
    if args.full:
        payload["counts"] = result["counts"]
    return payload


def cmd_db_migrate(args):
    con = db.connect(args.db, create=False)
    before = db.schema_version(con)
    if before is None:
        raise db.NoStore("no schema - run `jw db import` first")
    if args.dry_run:
        pending = [v for v in sorted(db.MIGRATIONS) if v > before]
        return {"dry_run": True, "schema_version": before, "pending": pending}
    applied = db.migrate(con)
    return {"from": before, "applied": applied, "schema_version": db.schema_version(con)}


def cmd_postings_query(args):
    con = _open(args)
    ctx = _ctx(args, con)
    rows, total = query.postings_search(
        con, company=args.company, open_only=args.open, since=args.since,
        title=args.title, category=args.category, limit=args.limit,
    )
    filters_used = any((args.company, args.since, args.title, args.category))
    return views.postings_list(ctx, rows, total, args.open, filters_used)


def cmd_postings_show(args):
    con = _open(args)
    posting_id = ids.expand_posting(con, args.posting_id)
    return views.posting_detail(_ctx(args, con), query.posting_show(con, posting_id))


def cmd_company_list(args):
    con = _open(args)
    return views.companies_list(_ctx(args, con), query.company_list(con), args.limit)


def cmd_company_show(args):
    con = _open(args)
    company = query.company_show(con, args.slug)
    if company is None:
        raise CliError("NOT_FOUND", f"no tracked company {args.slug!r}",
                       exit_code=EXIT_USAGE,
                       help=["Run `jw company list` to see tracked companies"])
    open_rows, open_total = query.postings_search(
        con, company_id=args.slug, open_only=True, limit=views.OPEN_POSTINGS_PAGE)
    return views.company_detail(_ctx(args, con), company, open_rows, open_total)


def cmd_applications_list(args):
    con = _open(args)
    rows = applications.list_applications(
        con, status=args.status, company=args.company,
        since=query.parse_since(args.since),
    )
    return views.applications_list(_ctx(args, con), rows, args.limit)


def cmd_watchlist_list(args):
    terms = config.watchlist_list(args.root)
    return {"count": len(terms), "terms": terms}


def cmd_state_show(args):
    con = _open(args)
    ctx = _ctx(args, con)
    return views.state_detail(ctx, query.state_show(con, args.db or paths.db_path()))


def _application_payload(args, con, record, changed, created=None):
    joined = applications.get(con, record["id"])
    return views.application_result(_ctx(args, con), joined, record["history"], changed,
                                    created)


def cmd_status_set(args):
    con = _open(args)
    if args.dry_run:
        target = applications.resolve(con, args.id)
        return views.application_preview(_ctx(args, con), target, status=args.status,
                                         note=args.note)
    record, changed = applications.set_status(con, args.id, args.status, note=args.note)
    return _application_payload(args, con, record, changed)


def cmd_notes_append(args):
    con = _open(args)
    if args.dry_run:
        target = applications.resolve(con, args.id)
        return views.application_preview(_ctx(args, con), target, note=args.text)
    record, created = applications.append_note(con, args.id, args.text)
    return _application_payload(args, con, record, True, created=created)


def _sync_failure(result, ctx):
    failed = [r for r in result["sources"] if r["status"] not in sync.OK_STATUSES]
    upstream = all(r["status"] == "upstream_unavailable" for r in failed)
    payload = views.sync_result(ctx, result)
    help_lines = payload.pop("help", [])
    raise CliError(
        "UPSTREAM_UNAVAILABLE" if upstream else "SYNC_FAILED",
        f"{len(failed)} of {len(result['sources'])} source(s) failed",
        exit_code=EXIT_UPSTREAM if upstream else EXIT_FAIL, help=help_lines, **payload)


def cmd_sync_run(args):
    con = _open(args)
    ctx = _ctx(args, con)
    result = sync.sync_run(con, source=args.source, no_tracker=args.no_tracker,
                           dry_run=args.dry_run, root=args.root)
    if result["failed"]:
        _sync_failure(result, ctx)
    return views.sync_result(ctx, result)


def cmd_digest_preview(args):
    con = _open(args)
    ctx = _ctx(args, con)
    result = sync.sync_run(con, source=args.source, no_tracker=True, dry_run=True)
    if result["failed"]:
        _sync_failure(result, ctx)
    return views.digest_preview(ctx, result)


def cmd_init(args):
    if args.home:
        os.environ[paths.HOME_ENV] = os.path.abspath(os.path.expanduser(args.home))
    root, origin = paths.resolve_home()
    result = home.init_home(root, db_file=args.db, starter=args.starter, git=args.git)
    payload = {
        "home": output.display_path(root),
        "resolved_from": origin,
        "db": output.display_path(result["db"]),
        "created": result["created"],
        "schema_version": result["schema_version"],
    }
    for key in ("starter", "git"):
        if key in result:
            payload[key] = result[key]
    payload["sources"] = result["sources"]
    help_lines = []
    if args.home:
        help_lines.append(
            f"Set {paths.HOME_ENV}={output.display_path(root)} so later commands use this home")
    if result["sources"]:
        help_lines.append("Run `jw sync run` to fetch postings")
    else:
        help_lines.append("Run `jw source add --simplify SimplifyJobs/New-Grad-Positions` "
                          "or `jw source add <name> --command <cmd>` to add a source")
    help_lines.append("Run `jw doctor` to check the setup")
    payload["help"] = help_lines
    return payload


def cmd_doctor(args):
    root, origin = paths.resolve_home()
    report = home.doctor(root, origin, args.db or paths.db_path())
    payload = {"healthy": report["healthy"], "checks": report["checks"]}
    help_lines = home.fixes(report["checks"])
    if not report["healthy"]:
        failing = sum(1 for c in report["checks"] if c["status"] == "fail")
        raise CliError("UNHEALTHY", f"{failing} check(s) failed", exit_code=EXIT_FAIL,
                       help=help_lines, **payload)
    payload["help"] = help_lines or ["Everything checks out; run `jw` for the dashboard"]
    return payload


RULES = (
    "Print one JSON object per line on stdout and send diagnostics to stderr.",
    "Exit 0 on success and 3 when the upstream site is unreachable; any other exit "
    "discards the whole run.",
    "Emit every posting the source lists right now on every run; jw dedupes, and a "
    "posting that disappears from the feed stays open.",
    "Timestamps are epoch seconds, never milliseconds.",
    "external_id must be unique across all sources.",
)


def cmd_schema_observation(args):
    return views.schema_fields(_ctx(args), schema.OBSERVATION, schema.EXAMPLE, list(RULES))


def _read_input(args):
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            return fh.read()
    if sys.stdin is None or sys.stdin.isatty():
        raise CliError("NO_INPUT", "no input: pipe Observation JSONL on stdin or pass --file",
                       exit_code=EXIT_USAGE, help=["Run `jw schema observation` for the format"])
    return sys.stdin.read()


def _ingest_config(registered, force_track_all):
    def config_for(source):
        found = registered.get(source)
        base = dict(ingest.DEFAULT_CONFIG)
        if found:
            base.update(filters=found["filters"], track_all=found["track_all"],
                        seed_hours=found["seed_hours"])
        if force_track_all:
            base["track_all"] = True
        return base
    return config_for


def cmd_ingest(args):
    con = _open(args)
    root = args.root or paths.home()
    text = _read_input(args)
    batch = ingest.parse_batch(text, source=args.source)
    first_errors = batch.errors[:ingest.MAX_ERRORS_SHOWN]
    if not batch.observations:
        if batch.errors:
            raise CliError("NO_VALID_OBSERVATIONS",
                           f"all {batch.rejected} line(s) were rejected", exit_code=EXIT_FAIL,
                           errors=first_errors,
                           help=["Run `jw schema observation` for the exact format"])
        raise CliError("NO_INPUT", "the input holds no observations", exit_code=EXIT_USAGE,
                       help=["Run `jw schema observation` for the format"])
    if args.strict and batch.errors:
        raise CliError("INVALID_INPUT",
                       f"{batch.rejected} line(s) were rejected and --strict is set",
                       exit_code=EXIT_FAIL, errors=first_errors,
                       help=["Fix the lines above, or drop --strict to ingest the valid ones"])

    registered = {c["name"]: c for c in registry.list_all(con)}
    watchlist = digest.normalize_watchlist(config.watchlist_list(root))
    now = int(time.time())
    try:
        summary = ingest.apply(con, batch.observations,
                               _ingest_config(registered, args.track_all), watchlist, now,
                               track_tracker=not args.no_tracker)
        if args.dry_run:
            con.rollback()
        else:
            if summary["created_companies"]:
                config.companies_append(summary["created_companies"], root)
            con.commit()
    except Exception:
        con.rollback()
        raise
    if not args.dry_run:
        sync.export_state(con, root, now)
    return views.ingest_result(_ctx(args, con), summary, batch, args.dry_run)


def _source_error(exc, exit_code=EXIT_USAGE):
    if exc.code == "ALREADY_EXISTS":
        exit_code = EXIT_FAIL
    return CliError(exc.code, str(exc), exit_code=exit_code, help=exc.help)


def _bool_flag(value):
    return None if value is None else value == "true"


def cmd_source_add(args):
    if bool(args.command) == bool(args.simplify):
        raise CliError("VALIDATION_ERROR", "pass exactly one of --command or --simplify",
                       exit_code=EXIT_USAGE,
                       help=["Example: `jw source add --simplify SimplifyJobs/New-Grad-Positions`"])
    con = _open(args)
    try:
        if args.simplify:
            name = args.name or registry.simplify_name(args.simplify)
            command = registry.simplify_command(args.simplify)
            namespace = args.id_namespace or registry.SIMPLIFY_NAMESPACE
        else:
            if not args.name:
                raise registry.SourceError("VALIDATION_ERROR",
                                           "a source name is required with --command")
            name, command = args.name, registry.parse_command(args.command)
            namespace = args.id_namespace or ""
        record, changed = registry.add(
            con, name, command, filters=registry.parse_filters(args.filters),
            env=args.env or [], track_all=args.track_all, seed_hours=args.seed_hours,
            timeout_s=args.timeout, max_output_mb=args.max_output_mb,
            enabled=not args.disabled, id_namespace=namespace)
    except registry.SourceError as exc:
        raise _source_error(exc)
    return views.source_detail(_ctx(args, con), record, changed)


def cmd_source_update(args):
    con = _open(args)
    try:
        record, changed = registry.update(
            con, args.name,
            command=registry.parse_command(args.command) if args.command else None,
            filters=registry.parse_filters(args.filters) if args.filters else None,
            env=args.env, track_all=_bool_flag(args.track_all), seed_hours=args.seed_hours,
            timeout_s=args.timeout, max_output_mb=args.max_output_mb,
            id_namespace=args.id_namespace)
    except registry.SourceError as exc:
        raise _source_error(exc)
    payload = views.source_detail(_ctx(args, con), record, bool(changed))
    payload["updated"] = changed
    return payload


def cmd_source_list(args):
    con = _open(args)
    return views.sources_list(_ctx(args, con), registry.list_all(con))


def cmd_source_remove(args):
    con = _open(args)
    try:
        registry.remove(con, args.name)
    except registry.SourceError as exc:
        raise _source_error(exc)
    return {"removed": args.name,
            "help": ["Postings already collected stay in the store",
                     "Run `jw source list` to see what remains"]}


def _toggle(args, enabled):
    con = _open(args)
    try:
        changed = registry.set_enabled(con, args.name, enabled)
    except registry.SourceError as exc:
        raise _source_error(exc)
    return {"name": args.name, "enabled": enabled, "changed": changed}


def cmd_source_enable(args):
    return _toggle(args, True)


def cmd_source_disable(args):
    return _toggle(args, False)


def cmd_source_run(args):
    con = _open(args)
    ctx = _ctx(args, con)
    try:
        result = sync.sync_run(con, source=args.name, no_tracker=args.no_tracker,
                               dry_run=args.dry_run, root=args.root)
    except registry.SourceError as exc:
        raise _source_error(exc)
    if result["failed"]:
        _sync_failure(result, ctx)
    return views.sync_result(ctx, result)


def cmd_source_adopt_legacy(args):
    con = _open(args)
    adopted = registry.adopt_legacy(con, dry_run=args.dry_run)
    payload = {"dry_run": args.dry_run, "adopted": len(adopted)}
    if adopted:
        payload["sources"] = adopted
        payload["help"] = ["Run `jw source list` to review them",
                           "Run `jw sync run` to fetch with the adopted sources"]
    else:
        payload["help"] = ["Nothing to adopt: every legacy source is already registered, "
                           "or the store has none"]
    return payload


def cmd_export_site(args):
    con = _open(args)
    root = args.root or paths.home()
    if args.dry_run:
        return {"dry_run": True, "root": output.display_path(root),
                "note": "would rewrite the state files and both read models"}
    written = exporter.export_all(con, root, derived=True)
    db.set_meta(con, "last_export", str(int(time.time())))
    con.commit()
    return {"root": output.display_path(root), "files_written": len(written)}


def cmd_slack_post(args):
    ctx = _ctx(args)
    text = args.text
    if args.digest_since:
        con = _open(args)
        digest = sync.digest_since(con, query.parse_since(args.digest_since))
        text = digest["digest_text"]
        if not text:
            return {"posted": False, "reason": "nothing new in that window",
                    "new_listings": 0}
    if not text:
        raise CliError("VALIDATION_ERROR", "nothing to post", exit_code=EXIT_USAGE,
                       help=["Pass --text <message> or --digest-since 1d"])
    try:
        result = notify.post(text, dry_run=args.dry_run)
    except notify.NotConfigured as exc:
        raise CliError("NOT_CONFIGURED", str(exc), exit_code=EXIT_FAIL,
                       help=[f"Export {notify.WEBHOOK_ENV} on the host, then retry"])
    if not result["ok"]:
        raise CliError("SLACK_FAILED", "Slack rejected the post", exit_code=EXIT_FAIL,
                       chunks=result["chunks"])
    if result.get("dry_run"):
        return {"dry_run": True, "chunks": result["chunks"], "chars": result["chars"],
                "text": ctx.block(result["text"])}
    return {"posted": True, "chunks": result["chunks"], "chars": result["chars"]}


def _package_version():
    try:
        from importlib.metadata import version
        return version("jobwatcher")
    except Exception:
        return "0.0.0"


def cmd_guide(args):
    if not args.topic:
        return {"topics": [{"name": n, "summary": guide.summary(n)} for n in guide.TOPIC_NAMES],
                "help": [f"Run `jw guide {guide.TOPIC_NAMES[0]}` to read one"]}
    if args.topic not in guide.TOPIC_NAMES:
        raise CliError("NOT_FOUND", f"no guide topic named {args.topic!r}", exit_code=EXIT_USAGE,
                       help=[f"Run `jw guide` to list topics: {', '.join(guide.TOPIC_NAMES)}"])
    return {"topic": args.topic, "text": guide.read(args.topic)}


def cmd_skills_install(args):
    root = args.root or os.getcwd()
    rows = skills.install(root, _package_version())
    return {"root": output.display_path(root), "skills": rows,
            "help": ["Run `jw skills list` to see every topic's status"]}


def cmd_skills_list(args):
    root = args.root or os.getcwd()
    return {"root": output.display_path(root), "skills": skills.list_installed(root)}


def cmd_skills_remove(args):
    root = args.root or os.getcwd()
    removed = skills.remove(root)
    return {"root": output.display_path(root), "removed": removed}


def cmd_hooks_install(args):
    root = args.root or os.getcwd()
    result = agent_hooks.install(root)
    return {"path": output.display_path(result["path"]), "action": result["action"],
            "help": ["Restart Claude Code, or run /hooks once, to pick up the new hook"]}


def cmd_hooks_remove(args):
    root = args.root or os.getcwd()
    result = agent_hooks.remove(root)
    return {"path": output.display_path(result["path"]), "action": result["action"]}


def cmd_hooks_summary(args):
    target = args.db or paths.db_path()
    if not os.path.exists(target):
        return {"status": "no store", "help": ["Run `jw init` to get started"]}
    con = db.connect(target, create=False)
    version = db.schema_version(con)
    if version is None:
        return {"status": "no store", "help": ["Run `jw init` to get started"]}
    if version < db.SCHEMA_VERSION:
        return {"status": f"schema v{version} is outdated",
                "help": ["Run `jw db migrate` to upgrade it"]}
    payload = views.hook_summary(query.overview(con))
    payload["help"] = ["Run `jw` for the full dashboard, or `jw guide` for topic instructions"]
    return payload


def cmd_serve(args):
    from . import service

    token = service.resolve_token(args.token)
    refusal = service.check_bind(args.bind, token)
    if refusal:
        raise CliError("VALIDATION_ERROR", refusal, exit_code=EXIT_USAGE,
                       help=[f"Pass --token <secret> or set ${service.TOKEN_ENV}"])

    root = args.root or paths.home()
    url = f"http://{args.bind}:{args.port}/"
    output.emit({"url": url, "root": output.display_path(root), "auth": bool(token),
                 "writes": True},
                output.resolve_format(args.format))
    try:
        service.serve(port=args.port, bind=args.bind, root=root, token=token,
                      verbose=args.verbose, db_path=args.db)
    except KeyboardInterrupt:
        pass
    return None


def cmd_mcp(args):
    from . import mcp_server

    mcp_server.Server().serve_forever()
    return None


def cmd_git_snapshot(args):
    ctx = _ctx(args)
    con = db.connect(args.db) if os.path.exists(args.db or paths.db_path()) else None
    result = gitops.snapshot(con, message=args.message, push=args.push,
                             dry_run=args.dry_run)
    files = result.pop("files", [])
    if not ctx.full:
        result["files"] = files[:10]
        if len(files) > 10:
            result["files_more"] = len(files) - 10
    else:
        result["files"] = files
    ok = result.pop("ok")
    if not ok:
        raise CliError("GIT_FAILED", "the snapshot did not complete", exit_code=EXIT_FAIL,
                       **result)
    return result


def cmd_watchlist_add(args):
    return {"dry_run": args.dry_run,
            **config.watchlist_add(args.term, args.root, dry_run=args.dry_run)}


def cmd_watchlist_remove(args):
    return {"dry_run": args.dry_run,
            **config.watchlist_remove(args.term, args.root, dry_run=args.dry_run)}


def _refresh_companies(args):
    target = args.db or paths.db_path()
    if not os.path.exists(target):
        return None
    con = db.connect(target)
    if db.schema_version(con) is None:
        return None
    return config.refresh_companies_table(con, args.root)


def cmd_company_add(args):
    result = config.company_add(
        args.slug, display_name=args.display_name, aliases=args.alias, tier=args.tier,
        careers_url=args.careers_url, levels_url=args.levels_url, root=args.root,
        dry_run=args.dry_run,
    )
    if result.get("changed") and not args.dry_run:
        result["companies_in_store"] = _refresh_companies(args)
    return {"dry_run": args.dry_run, **result}


def cmd_company_remove(args):
    result = config.company_remove(args.slug, root=args.root, dry_run=args.dry_run)
    if result.get("changed") and not args.dry_run:
        result["companies_in_store"] = _refresh_companies(args)
    return {"dry_run": args.dry_run, **result}


def service_token_env():
    from . import service
    return service.TOKEN_ENV


def _add_dry_run(p):
    p.add_argument("--dry-run", action="store_true",
                   help="report what would change, write nothing")
    return p


def _add_root(p):
    p.add_argument("--root", help="repo root to read/write (default: this repo)")
    return p


def _add_project_root(p):
    p.add_argument("--root", help="project directory to install into (default: this directory)")
    return p


def _add_full(p):
    p.add_argument("--full", action="store_true",
                   help="every field, untruncated, exactly as stored")
    return p


def _leaves(parser):
    actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not actions:
        yield parser
        return
    for child in actions[0].choices.values():
        yield from _leaves(child)


def build_parser():
    parser = Parser(prog="jw", description="Job postings and applications, for agents and people")
    parser.add_argument("--db",
                        help="database path (default: $JOBWATCHER_DB or ./jobwatcher.db)")
    parser.add_argument("--format", choices=output.FORMATS,
                        help=f"toon (default) or json; ${output.FORMAT_ENV} sets the default")
    sub = parser.add_subparsers(dest="group", parser_class=Parser)

    p = sub.add_parser("init", help="create a home: store, config, and optional starter sources")
    p.add_argument("--home", help="directory to use (default: $JW_HOME or the platform data dir)")
    p.add_argument("--starter", action="store_true",
                   help="add a starter company list and the Simplify sources")
    p.add_argument("--git", action="store_true", help="make the home a git repository for backups")
    p.set_defaults(func=cmd_init)

    sub.add_parser("doctor", help="check the home, store, sources and site").set_defaults(
        func=cmd_doctor)

    scsub = sub.add_parser("schema", help="the data contracts").add_subparsers(
        dest="command", required=True)
    _add_full(scsub.add_parser("observation", help="the record a collector prints, one per line")
              ).set_defaults(func=cmd_schema_observation)

    p = _add_full(_add_dry_run(_add_root(sub.add_parser(
        "ingest", help="load Observation JSONL from stdin or a file"))))
    p.add_argument("--source", help="require every line to name this source")
    p.add_argument("--file", help="read this file instead of stdin")
    p.add_argument("--track-all", action="store_true",
                   help="create a tracked company for every unmatched name")
    p.add_argument("--strict", action="store_true",
                   help="apply nothing if any line is invalid")
    p.add_argument("--no-tracker", action="store_true", help="only surface, skip the posting history")
    p.set_defaults(func=cmd_ingest)

    srcsub = sub.add_parser("source", help="the collectors that feed the store").add_subparsers(
        dest="command", required=True)
    p = _add_full(srcsub.add_parser("add", help="register a collector"))
    p.add_argument("name", nargs="?", help="unique name; defaults to the Simplify repo id")
    p.add_argument("--command", help="what to run, e.g. \"python collectors/acme.py\"")
    p.add_argument("--simplify", metavar="OWNER/REPO",
                   help="the built-in collector for a SimplifyJobs listings repo")
    p.add_argument("--filters", help="JSON: categories, title_keywords, locations")
    p.add_argument("--track-all", action="store_true",
                   help="track every company this source lists")
    p.add_argument("--seed-hours", type=int, default=25,
                   help="on the first run, surface only postings this recent (default 25)")
    p.add_argument("--timeout", type=int, default=300, help="seconds before it is killed")
    p.add_argument("--max-output-mb", type=int, default=64, help="stdout cap in MB")
    p.add_argument("--env", action="append", help="repeatable; environment variable to pass through")
    p.add_argument("--disabled", action="store_true", help="register without running it in syncs")
    p.add_argument("--id-namespace", help="sources sharing a namespace share listing ids "
                                          "(default: this source alone; --simplify uses simplify)")
    p.set_defaults(func=cmd_source_add)
    p = _add_full(srcsub.add_parser("update", help="change a registered collector"))
    p.add_argument("name")
    p.add_argument("--command")
    p.add_argument("--filters", help="JSON: categories, title_keywords, locations")
    p.add_argument("--track-all", choices=("true", "false"))
    p.add_argument("--seed-hours", type=int)
    p.add_argument("--timeout", type=int)
    p.add_argument("--max-output-mb", type=int)
    p.add_argument("--env", action="append", help="repeatable; replaces the pass-through list")
    p.add_argument("--id-namespace", help="sources sharing a namespace share listing ids")
    p.set_defaults(func=cmd_source_update)
    _add_full(srcsub.add_parser("list", help="registered collectors and their last run")
              ).set_defaults(func=cmd_source_list)
    p = srcsub.add_parser("remove", help="unregister a collector; collected postings stay")
    p.add_argument("name")
    p.set_defaults(func=cmd_source_remove)
    p = srcsub.add_parser("enable", help="include a collector in syncs")
    p.add_argument("name")
    p.set_defaults(func=cmd_source_enable)
    p = srcsub.add_parser("disable", help="leave a collector out of syncs")
    p.add_argument("name")
    p.set_defaults(func=cmd_source_disable)
    p = _add_full(_add_dry_run(_add_root(srcsub.add_parser(
        "run", help="run one collector and ingest its output"))))
    p.add_argument("name")
    p.add_argument("--no-tracker", action="store_true", help="only surface, skip the posting history")
    p.set_defaults(func=cmd_source_run)
    _add_dry_run(srcsub.add_parser(
        "adopt-legacy", help="turn sources.json entries into collectors and keep their known ids")
    ).set_defaults(func=cmd_source_adopt_legacy)

    dbsub = sub.add_parser("db", help="the SQLite working store").add_subparsers(
        dest="command", required=True)
    dbsub.add_parser("init", help="create an empty store").set_defaults(func=cmd_db_init)
    p = _add_root(dbsub.add_parser("import", help="load the committed JSON into the store"))
    p.add_argument("--force", action="store_true", help="replace an existing database")
    p.set_defaults(func=cmd_db_import)
    _add_dry_run(_add_root(dbsub.add_parser("export", help="write the store back out as JSON"))
                 ).set_defaults(func=cmd_db_export)
    _add_full(_add_root(dbsub.add_parser("verify", help="round-trip the JSON and diff"))
              ).set_defaults(func=cmd_db_verify)
    _add_dry_run(dbsub.add_parser("migrate", help="apply pending schema migrations")
                 ).set_defaults(func=cmd_db_migrate)

    psub = sub.add_parser("postings", help="the tracked posting corpus").add_subparsers(
        dest="command", required=True)
    p = _add_full(psub.add_parser("query", help="postings matching filters"))
    p.add_argument("--company", help="company slug, or part of a display name")
    p.add_argument("--open", action="store_true", help="only currently-open postings")
    p.add_argument("--since", help="unix timestamp or a span like 7d / 12h / 2w")
    p.add_argument("--title", help="substring of the title")
    p.add_argument("--category", help="Software, AI/ML/Data, Quant, Hardware, Product")
    p.add_argument("--limit", type=int, default=views.POSTINGS_PAGE,
                   help=f"rows to return, 0 for all (default {views.POSTINGS_PAGE})")
    p.set_defaults(func=cmd_postings_query)
    p = _add_full(psub.add_parser("show", help="one posting, with sources and history"))
    p.add_argument("posting_id", help="a posting id or a unique prefix of one")
    p.set_defaults(func=cmd_postings_show)

    csub = sub.add_parser("company", help="tracked companies").add_subparsers(
        dest="command", required=True)
    p = _add_full(csub.add_parser("list", help="every tracked company"))
    p.add_argument("--limit", type=int, default=views.COMPANIES_PAGE,
                   help=f"rows to return, 0 for all (default {views.COMPANIES_PAGE})")
    p.set_defaults(func=cmd_company_list)
    p = _add_full(csub.add_parser("show", help="one company with open postings and events"))
    p.add_argument("slug")
    p.set_defaults(func=cmd_company_show)
    p = _add_dry_run(_add_root(csub.add_parser("add", help="track a company")))
    p.add_argument("slug")
    p.add_argument("--display-name")
    p.add_argument("--alias", action="append", help="repeatable; upstream name variants")
    p.add_argument("--tier", help="S, A, B ...")
    p.add_argument("--careers-url")
    p.add_argument("--levels-url")
    p.set_defaults(func=cmd_company_add)
    p = _add_dry_run(_add_root(csub.add_parser("remove", help="stop tracking a company")))
    p.add_argument("slug")
    p.set_defaults(func=cmd_company_remove)

    asub = sub.add_parser("applications", help="your application records").add_subparsers(
        dest="command", required=True)
    p = _add_full(asub.add_parser("list", help="records, newest change first"))
    p.add_argument("--status", choices=applications.STATUSES)
    p.add_argument("--company")
    p.add_argument("--since", help="unix timestamp or a span like 7d")
    p.add_argument("--limit", type=int, default=views.APPLICATIONS_PAGE,
                   help=f"rows to return, 0 for all (default {views.APPLICATIONS_PAGE})")
    p.set_defaults(func=cmd_applications_list)

    ssub = sub.add_parser("status", help="set an application status").add_subparsers(
        dest="command", required=True)
    p = _add_full(_add_dry_run(ssub.add_parser("set", help="upsert a record")))
    p.add_argument("id", help="a posting id or listing id, or a unique prefix of either")
    p.add_argument("--status", required=True, choices=applications.STATUSES)
    p.add_argument("--note", help="appended to the record's notes and its history")
    p.set_defaults(func=cmd_status_set)

    nsub = sub.add_parser("notes", help="notes on an application").add_subparsers(
        dest="command", required=True)
    p = _add_full(_add_dry_run(nsub.add_parser("append", help="add a note, leaving status alone")))
    p.add_argument("id", help="a posting id or listing id, or a unique prefix of either")
    p.add_argument("--text", required=True)
    p.set_defaults(func=cmd_notes_append)

    wsub = sub.add_parser("watchlist", help="companies of interest").add_subparsers(
        dest="command", required=True)
    _add_root(wsub.add_parser("list", help="current terms")).set_defaults(
        func=cmd_watchlist_list)
    p = _add_dry_run(_add_root(wsub.add_parser("add", help="add a term")))
    p.add_argument("term")
    p.set_defaults(func=cmd_watchlist_add)
    p = _add_dry_run(_add_root(wsub.add_parser("remove", help="remove a term")))
    p.add_argument("term")
    p.set_defaults(func=cmd_watchlist_remove)

    sysub = sub.add_parser("sync", help="run the pipeline").add_subparsers(
        dest="command", required=True)
    p = _add_full(_add_dry_run(_add_root(sysub.add_parser(
        "run", help="fetch, filter, reconcile, export; returns the digest, posts nothing"))))
    p.add_argument("--source", help="only this upstream repo (owner/name)")
    p.add_argument("--no-tracker", action="store_true", help="skip the company tracker")
    p.set_defaults(func=cmd_sync_run)

    dsub = sub.add_parser("digest", help="the digest").add_subparsers(
        dest="command", required=True)
    p = _add_full(dsub.add_parser("preview", help="what a sync would surface, writing nothing"))
    p.add_argument("--source")
    p.set_defaults(func=cmd_digest_preview)

    esub = sub.add_parser("export", help="write files the site reads").add_subparsers(
        dest="command", required=True)
    _add_dry_run(_add_root(esub.add_parser(
        "site", help="state files plus index.json and all_postings.json"))
    ).set_defaults(func=cmd_export_site)

    slsub = sub.add_parser("slack", help="notifications").add_subparsers(
        dest="command", required=True)
    p = _add_full(_add_dry_run(slsub.add_parser("post", help="post a message")))
    p.add_argument("--text")
    p.add_argument("--digest-since", help="build the digest from listings seen since then")
    p.set_defaults(func=cmd_slack_post)

    gsub = sub.add_parser("git", help="backup to the remote").add_subparsers(
        dest="command", required=True)
    p = _add_full(_add_dry_run(gsub.add_parser("snapshot", help="commit the state files")))
    p.add_argument("--push", action="store_true", help="also push the current branch")
    p.add_argument("--message", help="commit message")
    p.set_defaults(func=cmd_git_snapshot)

    gdsub = sub.add_parser("guide", help="instructions for an agent, topic by topic")
    gdsub.add_argument("topic", nargs="?", help="omit to list every topic")
    gdsub.set_defaults(func=cmd_guide)

    sksub = sub.add_parser("skills", help="install jw's guide as agent skills").add_subparsers(
        dest="command", required=True)
    _add_project_root(sksub.add_parser(
        "install", help="write .agents/skills/jw-<topic>/SKILL.md for every topic")
    ).set_defaults(func=cmd_skills_install)
    _add_project_root(sksub.add_parser("list", help="which topics are installed here")
                      ).set_defaults(func=cmd_skills_list)
    _add_project_root(sksub.add_parser("remove", help="remove the skills jw installed")
                      ).set_defaults(func=cmd_skills_remove)

    hksub = sub.add_parser(
        "hooks", help="a Claude Code session-start summary"
    ).add_subparsers(dest="command", required=True)
    _add_project_root(hksub.add_parser(
        "install", help="register the session-start summary in .claude/settings.json")
    ).set_defaults(func=cmd_hooks_install)
    _add_project_root(hksub.add_parser("remove", help="unregister it")
                      ).set_defaults(func=cmd_hooks_remove)
    hksub.add_parser("summary", help="the terse status line the hook prints"
                     ).set_defaults(func=cmd_hooks_summary)

    p = sub.add_parser("serve", help="serve the site and API (blocks)")
    _add_root(p)
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--bind", default="127.0.0.1",
                   help="127.0.0.1 by default; any other address needs a token")
    p.add_argument("--token", help=f"shared secret (default: ${service_token_env()})")
    p.add_argument("--verbose", action="store_true", help="log every request")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("mcp", help="expose the tools over MCP on stdio (blocks)")
    p.set_defaults(func=cmd_mcp)

    stsub = sub.add_parser("state", help="store health").add_subparsers(
        dest="command", required=True)
    _add_full(stsub.add_parser("show", help="counts, timestamps, schema version")
              ).set_defaults(func=cmd_state_show)

    for leaf in _leaves(parser):
        if leaf is not parser:
            leaf.add_argument("--format", choices=output.FORMATS, default=argparse.SUPPRESS,
                              help=argparse.SUPPRESS)
            leaf.set_defaults(usage_prog=leaf.prog)
    return parser


def _format_from_argv(argv):
    for index, arg in enumerate(argv):
        if arg == "--format" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--format="):
            return arg.split("=", 1)[1]
    return None


def _translate(exc):
    if isinstance(exc, CliError):
        return exc
    if isinstance(exc, registry.SourceError):
        return _source_error(exc)
    if isinstance(exc, sync.Busy):
        return CliError(exc.code, str(exc), exit_code=EXIT_UPSTREAM, help=exc.help)
    if isinstance(exc, gitops.NotARepo):
        return CliError("NOT_A_REPO", str(exc), exit_code=EXIT_USAGE,
                        help=["Run `jw init --git` to make this home a git repository"])
    if isinstance(exc, ids.AmbiguousTarget):
        return CliError("AMBIGUOUS", str(exc), exit_code=EXIT_USAGE,
                        candidates=exc.candidates,
                        help=["Repeat the command with a longer id prefix"])
    if isinstance(exc, ids.UnknownTarget):
        return CliError("NOT_FOUND", str(exc), exit_code=EXIT_USAGE,
                        help=["Run `jw postings query --title <text>` to find an id"])
    if isinstance(exc, db.NoStore):
        return CliError("NO_STORE", str(exc), exit_code=EXIT_USAGE, help=_no_store_help())
    if isinstance(exc, FileNotFoundError):
        return CliError("NOT_FOUND", str(exc), exit_code=EXIT_USAGE)
    if isinstance(exc, ValueError):
        return CliError("VALIDATION_ERROR", str(exc), exit_code=EXIT_USAGE)
    return CliError("INTERNAL", f"{type(exc).__name__}: {exc}", exit_code=EXIT_FAIL)


def main(argv=None):
    _use_utf8()
    argv = sys.argv[1:] if argv is None else list(argv)
    fmt = output.DEFAULT_FORMAT
    try:
        fmt = output.resolve_format(_format_from_argv(argv))
        args, extras = build_parser().parse_known_args(argv)
        if extras:
            scope = getattr(args, "usage_prog", "jw")
            raise CliError("VALIDATION_ERROR", f"unknown argument for {scope}: {extras[0]}",
                           exit_code=EXIT_USAGE, help=[f"{scope} --help"])
        for name, default in (("root", None), ("dry_run", False), ("db", None),
                              ("full", False), ("format", None)):
            if not hasattr(args, name):
                setattr(args, name, default)
        fmt = output.resolve_format(args.format)
        payload = cmd_dashboard(args) if args.group is None else args.func(args)
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:
        if os.environ.get(DEBUG_ENV):
            traceback.print_exc()
        error = _translate(exc)
        output.emit(error.payload(), fmt)
        return error.exit_code
    if payload is not None:
        try:
            output.emit(payload, fmt)
        except BrokenPipeError:
            pass
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
