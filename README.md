# JobWatcher

Track every posting, and every application, in one local place. JobWatcher pulls job
listings from the sources you choose, follows each posting from open to closed, keeps your
own application status beside it, and gives you a fast local site and a CLI built for
coding agents to drive.

<p align="center">
  <img src="https://raw.githubusercontent.com/evan2chen/JobWatcher-v1/main/docs/screenshots/must-apply.png" alt="The must-apply list, ranked per profile" width="49%">
  <img src="https://raw.githubusercontent.com/evan2chen/JobWatcher-v1/main/docs/screenshots/catalog.png" alt="The catalog, with every tracked company grouped by tier" width="49%">
</p>

- **Any source is a collector.** A collector is any program that prints one JSON line per
  posting it currently sees. Two SimplifyJobs feeds ship built in, and a collector for a
  new site is a few lines. See `jw guide write-collector` or `docs/collectors.md`.
- **Postings have a lifecycle.** Opens, updates, closes and reopens are recorded events,
  and a posting closes only when its source says so, never just because it left a feed.
- **Your status stays yours.** One posting, one status (`interested`, `applied`,
  `interviewing`, `offer`, and more), set with `jw status set` and never changed by a sync.
- **Built for agents.** Every command prints TOON or JSON and ends with concrete next
  steps, and `jw guide` teaches an agent the whole workflow with no instructions from you.
- **Your data stays on your machine.** Everything lives in a local home directory,
  separate from the package.

## Get started

### Option 1: let your coding agent set it up

Paste this into Claude Code, Codex, Cursor, Gemini CLI or any agent that can run shell
commands:

```
Set up JobWatcher from https://github.com/evan2chen/JobWatcher-v1 for me. Install it,
create a home with the starter list, run the first sync, install its agent skills, and
then show me what is new.
```

The agent follows the steps in option 2, then uses `jw guide` to learn the rest.

### Option 2: install it yourself

```
pip install jobwatcher
jw init --starter --git
jw sync run --full
jw serve
```

- `jw init --starter --git` creates your home with a curated company list and two
  ready-to-run sources, and makes the home a git repository so `jw git snapshot` has
  somewhere to commit.
- `jw sync run --full` fetches every source, reconciles it into the store and prints a
  digest of what is new.
- `jw serve` opens the site at http://127.0.0.1:8099/.

Python 3.9 or newer is the only requirement. JobWatcher has no dependencies.

Your data lives in `JW_HOME` when set, and otherwise in your platform's data directory.
Set `JW_HOME` to a different folder to keep a separate home per search.

## Commands worth knowing

| Command | What it does |
|---------|--------------|
| `jw` | A dashboard: store health, counts, newest postings and next steps. |
| `jw serve` | The local site: a ranked must-apply list per profile and a searchable catalog. |
| `jw sync run` | Fetch every source and print what is new. Run it daily, or on a timer. |
| `jw postings query --open --since 7d` | Browse recent open postings. Filter by `--company`, `--title`, `--category`. |
| `jw postings show <id>` | One posting with its sources and full history. |
| `jw status set <id> --status applied` | Record where you are with a posting. |
| `jw company add` / `jw company list` | Track more companies. |
| `jw watchlist add "jane street"` | Always surface a company, whatever the filters say. |
| `jw digest preview` | What the next sync would surface, writing nothing. |
| `jw source add` | Register a new collector. |
| `jw git snapshot` | Commit your data for backup. |
| `jw doctor` | Check the home, store and sources. Changes nothing. |
| `jw guide` | Instructions for an agent, one topic per line. |

Every command accepts `--help`, and ids can be shortened to any unique prefix.

## The web app

`jw serve` runs a local site over your store. The **must-apply** list ranks open postings
for a profile such as software engineering, ML research, quant or hardware, and the
**catalog** searches and filters every posting. Marks you set in the site are saved to the
store, so they show up in the CLI too. With no backend at all, the same bundle works from
a static file server and keeps marks in the browser.

## Give it to an agent

```
jw skills install    # writes .agents/skills/jw-<topic>/SKILL.md for Claude Code, Codex,
                     # Cursor, Gemini CLI and GitHub Copilot to discover
jw hooks install     # a one-line "what's in the store" at the start of each
                     # Claude Code session in this project
jw mcp               # the same commands as MCP tools over stdio
```

## Notifications

`jw sync run` never posts anywhere on its own. It returns a digest, and `jw slack post` is
one example channel. `jw guide notify` covers wiring up your own.

## Security

Collectors run arbitrary code with your privileges, and the write API needs a token off
loopback. See `SECURITY.md`.

## Documentation

- `docs/self-hosting.md` - the CLI, the MCP wrapper, the service, and what is still proposed.
- `docs/data-model.md` - every JSON file's exact schema.
- `docs/collectors.md` - the Observation contract, in depth.
- `CONTRIBUTING.md` - running the gate, and where new behavior needs a new check.

## License

MIT - see `LICENSE`.
