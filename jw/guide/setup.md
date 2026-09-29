# Setup

Install the package, then create a home for it to keep its data in.

```
pip install jobwatcher
jw init --starter --git
```

`--starter` seeds a curated company list and the two SimplifyJobs sources, so there is
something to sync on the first run. `--git` makes the home a git repository so `jw git
snapshot` has somewhere to commit to. Both are optional; a bare `jw init` makes an empty
home.

The home lives in `JW_HOME` if that's set, otherwise the platform's data directory
(`%LOCALAPPDATA%\jobwatcher` on Windows, `~/Library/Application Support/jobwatcher` on
macOS, `$XDG_DATA_HOME/jobwatcher` or `~/.local/share/jobwatcher` on Linux). Point `JW_HOME`
at a different directory to run more than one home, for example one per employer search.

Run `jw doctor` any time to check the home: store schema version, whether sources are
registered, and whether the site's data files are current. It never changes anything.

Once the home exists, run:

```
jw sync run --full
```

This fetches every registered source, reconciles it into the store, and prints a digest
of what's new. Run it again later, or set up a timer (`docs/self-hosting.md` has scheduling
recipes) to run it automatically.

Next: `jw guide core` for the command conventions, or `jw guide write-collector` to add a
source beyond the two starter ones.
