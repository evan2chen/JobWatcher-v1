import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { decodePosting, type Company, type RawPosting } from "../src/lib/types";
import { PRESET_PROFILES, matchesProfile, rankAll } from "../src/lib/profiles";
import { EMPTY_FILTERS, applyFilters, filtersFromProfile, filtersToQuery, filtersFromQuery } from "../src/lib/filters";

const repo = join(process.cwd(), "..");
const scratch = mkdtempSync(join(tmpdir(), "jw-smoke-"));
const { root } = JSON.parse(
  execFileSync("python", [join(repo, "tests", "fixture.py"), "--tree-only", join(scratch, "repo")], {
    cwd: repo,
    encoding: "utf-8",
  }),
) as { root: string };
process.on("exit", () => rmSync(scratch, { recursive: true, force: true }));
const read = <T>(p: string): T => JSON.parse(readFileSync(join(root, p), "utf-8")) as T;

const index = read<{ companies: Company[] }>("tracker/index.json");
const corpus = read<{ count: number; postings: RawPosting[] }>("tracker/all_postings.json");

const byslug = new Map(index.companies.map((c) => [c.slug, c]));
const postings = corpus.postings.map((r) => decodePosting(r, byslug.get(r.co)));
const open = postings.filter((p) => p.state === "open");

let failures = 0;
const check = (label: string, ok: boolean, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"} ${label}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures++;
};

console.log(`corpus: ${postings.length} postings, ${open.length} open, ${index.companies.length} companies\n`);

check("every posting joined to a tracked company", postings.every((p) => p.tier !== null));
check("aggregate count matches array length", corpus.count === corpus.postings.length);

for (const prof of PRESET_PROFILES) {
  const matched = open.filter((p) => matchesProfile(p, prof));
  const ranked = rankAll(matched, prof);
  const top = ranked[0];
  check(
    `profile "${prof.name}" matches open roles`,
    matched.length > 0,
    `${matched.length} of ${open.length} open`,
  );
  check(
    `profile "${prof.name}" ranks highest-first`,
    ranked.every((r, i) => i === 0 || ranked[i - 1].score >= r.score),
    top ? `top: [${top.score}] ${top.posting.companyName} — ${top.posting.title}` : "",
  );
  check(
    `profile "${prof.name}" honours its exclude list`,
    !matched.some((p) => prof.exclude.some((x) => p.titleLower.includes(x))),
  );
}

for (const prof of PRESET_PROFILES) {
  const seeded = applyFilters(postings, filtersFromProfile(prof), {});
  const matched = open.filter((p) => matchesProfile(p, prof));
  check(
    `catalog seeded from "${prof.name}" is a superset of its matches`,
    matched.every((m) => seeded.some((s) => s.id === m.id)),
    `${seeded.length} vs ${matched.length}`,
  );
}

check(
  "default catalog filters show only open postings",
  applyFilters(postings, EMPTY_FILTERS, {}).length === open.length,
);

const roundTrip = { ...EMPTY_FILTERS, q: "machine learning", categories: ["Software", "Quant"], state: "all" as const };
check(
  "filters survive a URL round trip",
  JSON.stringify(filtersFromQuery(filtersToQuery(roundTrip))) === JSON.stringify(roundTrip),
  filtersToQuery(roundTrip).toString(),
);

const searched = applyFilters(postings, { ...EMPTY_FILTERS, q: "quantitative" }, {});
check("free-text search finds something", searched.length > 0, `${searched.length} hits`);

const marked = { [open[0].id]: { status: "applied" as const, at: 0 } };
check(
  "the applied mark filters a posting out of 'unmarked'",
  !applyFilters(postings, { ...EMPTY_FILTERS, mark: "unmarked" }, marked).some((p) => p.id === open[0].id),
);

console.log();
if (failures) {
  console.log(`${failures} CHECK(S) FAILED`);
  process.exit(1);
}
console.log("ALL CHECKS PASSED");
