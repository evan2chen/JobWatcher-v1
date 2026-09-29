import { tierRank } from "./format";
import { TIERS, type Posting } from "./types";
import type { StatusMap } from "./store";
import type { Profile } from "./profiles";

export type SortKey = "new" | "company" | "tier";
export type ViewKey = "postings" | "companies";
export type StateKey = "open" | "closed" | "all";
export type MarkKey = "all" | "unmarked" | "applied" | "skipped" | "interested";

export type Filters = {
  q: string;
  loc: string;
  state: StateKey;
  levels: string[];
  terms: string[];
  categories: string[];
  tiers: string[];
  sponsorships: string[];
  mark: MarkKey;
  sort: SortKey;
  view: ViewKey;
};

export const EMPTY_FILTERS: Filters = {
  q: "",
  loc: "",
  state: "open",
  levels: [],
  terms: [],
  categories: [],
  tiers: [],
  sponsorships: [],
  mark: "all",
  sort: "new",
  view: "postings",
};

const LIST_KEYS = ["levels", "terms", "categories", "tiers", "sponsorships"] as const;

export function hasActiveFilters(f: Filters): boolean {
  return (
    f.q !== "" ||
    f.loc !== "" ||
    f.state !== EMPTY_FILTERS.state ||
    f.mark !== "all" ||
    LIST_KEYS.some((k) => f[k].length > 0)
  );
}

const PARAM: Record<string, keyof Filters> = {
  q: "q",
  loc: "loc",
  state: "state",
  lvl: "levels",
  term: "terms",
  cat: "categories",
  tier: "tiers",
  sp: "sponsorships",
  mark: "mark",
  sort: "sort",
  view: "view",
};

export function filtersFromQuery(query: URLSearchParams): Filters {
  const f: Filters = { ...EMPTY_FILTERS, levels: [], terms: [], categories: [], tiers: [], sponsorships: [] };
  for (const [param, key] of Object.entries(PARAM)) {
    const raw = query.get(param);
    if (raw === null) continue;
    if (Array.isArray(f[key])) {
      (f[key] as string[]) = raw.split(",").filter(Boolean);
    } else {
      (f[key] as string) = raw;
    }
  }
  return f;
}

export function filtersToQuery(f: Filters): URLSearchParams {
  const q = new URLSearchParams();
  for (const [param, key] of Object.entries(PARAM)) {
    const value = f[key];
    if (Array.isArray(value)) {
      if (value.length) q.set(param, value.join(","));
    } else if (value && value !== EMPTY_FILTERS[key]) {
      q.set(param, value as string);
    }
  }
  return q;
}

export function filtersFromProfile(prof: Profile): Filters {
  const min = prof.minTier;
  return {
    ...EMPTY_FILTERS,
    categories: [...prof.categories],
    levels: [...prof.levels],
    terms: [...prof.terms],
    tiers: min ? TIERS.filter((t) => tierRank(t) <= tierRank(min)) : [],
  };
}

export function applyFilters(
  postings: Posting[],
  f: Filters,
  status: StatusMap,
  skip?: keyof Filters,
): Posting[] {
  const q = f.q.trim().toLowerCase();
  const loc = f.loc.trim().toLowerCase();

  return postings.filter((p) => {
    if (skip !== "q" && q && !p.searchText.includes(q)) return false;
    if (skip !== "loc" && loc && !p.locations.some((l) => l.toLowerCase().includes(loc))) return false;
    if (skip !== "state" && f.state !== "all" && p.state !== f.state) return false;
    if (skip !== "levels" && f.levels.length && (!p.level || !f.levels.includes(p.level))) return false;
    if (skip !== "terms" && f.terms.length && !p.terms.some((t) => f.terms.includes(t))) return false;
    if (skip !== "categories" && f.categories.length && !f.categories.includes(p.category)) return false;
    if (skip !== "tiers" && f.tiers.length && (!p.tier || !f.tiers.includes(p.tier))) return false;
    if (skip !== "sponsorships" && f.sponsorships.length &&
        (!p.sponsorship || !f.sponsorships.includes(p.sponsorship))) return false;

    if (skip !== "mark" && f.mark !== "all") {
      const s = status[p.id]?.status;
      if (f.mark === "unmarked" ? s !== undefined : s !== f.mark) return false;
    }
    return true;
  });
}

export function sortPostings(postings: Posting[], sort: SortKey): Posting[] {
  const out = [...postings];
  if (sort === "company") {
    out.sort((a, b) => a.companyName.localeCompare(b.companyName) || (b.postedAt ?? 0) - (a.postedAt ?? 0));
  } else if (sort === "tier") {
    out.sort(
      (a, b) =>
        tierRank(a.tier) - tierRank(b.tier) ||
        a.companyName.localeCompare(b.companyName) ||
        (b.postedAt ?? 0) - (a.postedAt ?? 0),
    );
  } else {
    out.sort((a, b) => (b.postedAt ?? 0) - (a.postedAt ?? 0) || a.companyName.localeCompare(b.companyName));
  }
  return out;
}

export function countBy(postings: Posting[], pick: (p: Posting) => string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const p of postings) {
    for (const v of pick(p)) {
      if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
    }
  }
  return counts;
}
