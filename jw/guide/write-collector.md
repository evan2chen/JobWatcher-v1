# Writing a collector

A collector is any program that prints one JSON object per line to stdout, one line per
posting it currently sees. Run `jw schema observation` for the exact contract (every field,
which are required, and a worked example) — read that first; this is the workflow around it.

1. Write the script. It needs no arguments and no jw import: print observations to stdout,
   send anything else to stderr, and exit 0 on success or 3 when the upstream site is
   unreachable (any other exit code discards the whole run).

2. Test it against the store without registering it:

   ```
   your-script.py > sample.jsonl
   jw ingest --dry-run --file sample.jsonl
   ```

   This reconciles the sample the same way a real sync would, but writes nothing. Pass
   `--full` to see everything it did with the sample, and fix any rejected lines or
   unmatched companies before registering.

3. Register it:

   ```
   jw source add acme --command "python collectors/acme.py"
   ```

   `--filters` narrows what a sync surfaces (JSON: `categories`, `title_keywords`,
   `locations` — an empty filter is permissive). `--track-all` tracks every company the
   source lists, instead of only the ones in `tracker/companies.json`. `--id-namespace`
   only matters when two collectors list the same postings under the same ids (as both
   built-in Simplify sources do) — leave it out for anything else.

4. Run it on its own before trusting it in a full sync:

   ```
   jw source run acme --dry-run
   ```

5. Once it looks right:

   ```
   jw sync run
   ```

   runs every enabled, registered source together and prints the combined digest.

The one rule that catches people: emit every posting the source lists right now, on every
run. Never try to diff against what you emitted last time — `jw` does that dedup itself,
and a posting that disappears from your output stays open until you (or the source) say
otherwise via `state_raw`.
