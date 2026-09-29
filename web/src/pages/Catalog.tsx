import { useEffect, useMemo, useState } from "react";
import { CompanyCard } from "../components/CompanyCard";
import { FacetGroup, type FacetOption } from "../components/FacetPanel";
import { PostingCard } from "../components/PostingCard";
import { cmpTerm, plural, tierRank } from "../lib/format";
import {
  applyFilters,
  countBy,
  EMPTY_FILTERS,
  filtersFromProfile,
  filtersFromQuery,
  filtersToQuery,
  hasActiveFilters,
  sortPostings,
  type Filters,
  type MarkKey,
  type SortKey,
} from "../lib/filters";
import { useStore } from "../lib/store";
import { useFacetValues, type Data } from "../lib/data";
import { replaceHash } from "../lib/useHashRoute";
import { LEVELS, TIERS } from "../lib/types";

const PAGE = 60;

const MARKS: { value: MarkKey; label: string }[] = [
  { value: "all", label: "All" },
  { value: "unmarked", label: "Unmarked" },
  { value: "interested", label: "Interested" },
  { value: "applied", label: "Applied" },
  { value: "skipped", label: "Skipped" },
];

export function Catalog({ data, query }: { data: Data; query: URLSearchParams }) {
  const { status, activeProfile } = useStore();
  const [filters, setFilters] = useState<Filters>(() => filtersFromQuery(query));
  const [limit, setLimit] = useState(PAGE);
  const facets = useFacetValues(data.postings);

  useEffect(() => {
    const q = filtersToQuery(filters).toString();
    replaceHash(q ? `/catalog?${q}` : "/catalog");
  }, [filters]);

  const patch = (p: Partial<Filters>) => {
    setFilters((prev) => ({ ...prev, ...p }));
    setLimit(PAGE);
  };

  const toggle = (key: "levels" | "terms" | "categories" | "tiers" | "sponsorships", value: string) =>
    setFilters((prev) => {
      const cur = prev[key];
      return { ...prev, [key]: cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value] };
    });

  const matched = useMemo(
    () => applyFilters(data.postings, filters, status),
    [data.postings, filters, status],
  );
  const sorted = useMemo(() => sortPostings(matched, filters.sort), [matched, filters.sort]);

  const options = useMemo(() => {
    const of = (skip: keyof Filters) => applyFilters(data.postings, filters, status, skip);
    const build = (
      values: string[],
      counts: Map<string, number>,
      label?: (v: string) => string,
    ): FacetOption[] => values.map((v) => ({ value: v, label: label?.(v), count: counts.get(v) ?? 0 }));

    return {
      levels: build(LEVELS, countBy(of("levels"), (p) => (p.level ? [p.level] : []))),
      terms: build([...facets.terms].sort(cmpTerm), countBy(of("terms"), (p) => p.terms)),
      categories: build(facets.categories, countBy(of("categories"), (p) => [p.category])),
      tiers: build(TIERS, countBy(of("tiers"), (p) => (p.tier ? [p.tier] : [])), (t) => `Tier ${t}`),
      sponsorships: build(facets.sponsorships, countBy(of("sponsorships"), (p) => (p.sponsorship ? [p.sponsorship] : []))),
    };
  }, [data.postings, filters, status, facets]);

  const companies = useMemo(() => {
    const list = [...data.companies];
    list.sort(
      (a, b) =>
        tierRank(a.tier) - tierRank(b.tier) ||
        (b.open_count || 0) - (a.open_count || 0) ||
        a.display_name.localeCompare(b.display_name),
    );
    return list;
  }, [data.companies]);

  const byTier = useMemo(() => {
    const groups = new Map<string, typeof companies>();
    for (const c of companies) {
      const key = c.tier ?? "—";
      const bucket = groups.get(key);
      if (bucket) bucket.push(c);
      else groups.set(key, [c]);
    }
    return [...groups.entries()];
  }, [companies]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Catalog</h1>
          <p className="muted small">
            {data.postings.length.toLocaleString()} postings across{" "}
            {plural(data.companies.length, "company", "companies")}
          </p>
        </div>
        <div className="view-toggle" role="tablist" aria-label="Catalog view">
          {(["postings", "companies"] as const).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={filters.view === v}
              className={`pill${filters.view === v ? " active" : ""}`}
              onClick={() => patch({ view: v })}
            >
              {v === "postings" ? "Postings" : "Companies"}
            </button>
          ))}
        </div>
      </div>

      {filters.view === "companies" ? (
        byTier.map(([tier, list]) => (
          <section key={tier} className="tier-group">
            <div className="tier-heading">
              <span className={`tier-badge tier-${tier === "—" ? "none" : tier}`}>{tier}</span>
              <span className="muted small">{plural(list.length, "company", "companies")}</span>
            </div>
            <div className="card-grid">
              {list.map((c) => (
                <CompanyCard key={c.slug} company={c} />
              ))}
            </div>
          </section>
        ))
      ) : (
        <div className="catalog">
          <aside className="sidebar">
            <input
              className="search"
              type="search"
              value={filters.q}
              placeholder="Search titles, companies…"
              aria-label="Search postings"
              onChange={(e) => patch({ q: e.target.value })}
            />
            <input
              className="search"
              type="search"
              value={filters.loc}
              placeholder="Location contains…"
              aria-label="Filter by location"
              onChange={(e) => patch({ loc: e.target.value })}
            />

            <fieldset className="facet-group">
              <legend>Status</legend>
              <div className="seg">
                {(["open", "closed", "all"] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={`pill${filters.state === s ? " active" : ""}`}
                    onClick={() => patch({ state: s })}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </fieldset>

            <FacetGroup label="Level" options={options.levels} selected={filters.levels} onToggle={(v) => toggle("levels", v)} />
            <FacetGroup label="Term" options={options.terms} selected={filters.terms} onToggle={(v) => toggle("terms", v)} />
            <FacetGroup label="Category" options={options.categories} selected={filters.categories} onToggle={(v) => toggle("categories", v)} />
            <FacetGroup label="Company tier" options={options.tiers} selected={filters.tiers} onToggle={(v) => toggle("tiers", v)} />
            <FacetGroup label="Sponsorship" options={options.sponsorships} selected={filters.sponsorships} onToggle={(v) => toggle("sponsorships", v)} />

            <fieldset className="facet-group">
              <legend>My marks</legend>
              <div className="seg wrap">
                {MARKS.map((m) => (
                  <button
                    key={m.value}
                    type="button"
                    className={`pill${filters.mark === m.value ? " active" : ""}`}
                    onClick={() => patch({ mark: m.value })}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </fieldset>

            <div className="sidebar-actions">
              <button
                type="button"
                className="ghost-btn block"
                title={`Set the facets to match your ${activeProfile.name} profile`}
                onClick={() => {
                  setFilters(filtersFromProfile(activeProfile));
                  setLimit(PAGE);
                }}
              >
                Apply {activeProfile.name} profile
              </button>
              <button
                type="button"
                className="ghost-btn block"
                disabled={!hasActiveFilters(filters)}
                onClick={() => {
                  setFilters({ ...EMPTY_FILTERS, view: filters.view, sort: filters.sort });
                  setLimit(PAGE);
                }}
              >
                Clear filters
              </button>
            </div>
          </aside>

          <div className="results">
            <div className="results-head">
              <span className="muted small">{plural(sorted.length, "posting")}</span>
              <span className="spacer" />
              <label className="muted small">
                Sort{" "}
                <select
                  value={filters.sort}
                  onChange={(e) => patch({ sort: e.target.value as SortKey })}
                >
                  <option value="new">Newest</option>
                  <option value="company">Company A–Z</option>
                  <option value="tier">Company tier</option>
                </select>
              </label>
            </div>

            {sorted.length === 0 ? (
              <p className="empty">No postings match these filters.</p>
            ) : (
              <div className="posting-list">
                {sorted.slice(0, limit).map((p) => (
                  <PostingCard key={p.id} posting={p} />
                ))}
              </div>
            )}

            {sorted.length > limit ? (
              <button
                type="button"
                className="ghost-btn block"
                onClick={() => setLimit((n) => n + PAGE)}
              >
                Load {Math.min(PAGE, sorted.length - limit)} more of {sorted.length}
              </button>
            ) : null}
          </div>
        </div>
      )}
    </>
  );
}
