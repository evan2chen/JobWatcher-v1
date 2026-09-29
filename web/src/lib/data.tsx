import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchJSON } from "./fetchers";
import { useStore, type StatusMap } from "./store";
import { decodePosting, type Company, type Posting, type RawPosting } from "./types";

type IndexFile = { generated_at: number; companies: Company[] };
type CorpusFile = { generated_at: number; count: number; postings: RawPosting[] };

export type Data = {
  companies: Company[];
  byslug: Map<string, Company>;
  postings: Posting[];
  generatedAt: number;
};

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: Data };

const DataContext = createContext<State>({ status: "loading" });

export function DataProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchJSON<IndexFile>("tracker/index.json"),
      fetchJSON<CorpusFile>("tracker/all_postings.json"),
    ])
      .then(([index, corpus]) => {
        if (cancelled) return;
        const companies = index.companies || [];
        const byslug = new Map(companies.map((c) => [c.slug, c]));
        setState({
          status: "ready",
          data: {
            companies,
            byslug,
            postings: (corpus.postings || []).map((r) => decodePosting(r, byslug.get(r.co))),
            generatedAt: corpus.generated_at || index.generated_at || 0,
          },
        });
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ status: "error", message: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <DataContext.Provider value={state}>{children}</DataContext.Provider>;
}

function withUserClosures(data: Data, status: StatusMap): Data {
  const closedByCompany = new Map<string, number>();
  const postings = data.postings.map((p) => {
    const entry = status[p.id];
    if (entry?.status !== "closed" || p.state !== "open") return p;
    closedByCompany.set(p.companyId, (closedByCompany.get(p.companyId) ?? 0) + 1);
    return { ...p, state: "closed" as const, closedAt: entry.at };
  });
  if (closedByCompany.size === 0) return data;

  const companies = data.companies.map((c) => {
    const closed = closedByCompany.get(c.slug);
    return closed ? { ...c, open_count: Math.max(0, c.open_count - closed) } : c;
  });
  return { ...data, postings, companies, byslug: new Map(companies.map((c) => [c.slug, c])) };
}

export function useDataState(): State {
  const state = useContext(DataContext);
  const { status } = useStore();
  return useMemo<State>(
    () =>
      state.status === "ready"
        ? { status: "ready", data: withUserClosures(state.data, status) }
        : state,
    [state, status],
  );
}

export function useFacetValues(postings: Posting[]) {
  return useMemo(() => {
    const terms = new Set<string>();
    const categories = new Set<string>();
    const sponsorships = new Set<string>();
    for (const p of postings) {
      for (const t of p.terms) terms.add(t);
      if (p.category) categories.add(p.category);
      if (p.sponsorship) sponsorships.add(p.sponsorship);
    }
    return {
      terms: [...terms],
      categories: [...categories].sort(),
      sponsorships: [...sponsorships].sort(),
    };
  }, [postings]);
}
