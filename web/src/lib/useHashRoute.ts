import { useEffect, useMemo, useState } from "react";

export type Route =
  | { name: "landing" }
  | { name: "catalog"; query: URLSearchParams }
  | { name: "company"; slug: string };

function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, "") || "/";
  const qi = raw.indexOf("?");
  const path = qi === -1 ? raw : raw.slice(0, qi);
  const search = qi === -1 ? "" : raw.slice(qi + 1);

  const company = /^\/company\/(.+)$/.exec(path);
  if (company) return { name: "company", slug: decodeURIComponent(company[1]) };
  if (path === "/catalog") return { name: "catalog", query: new URLSearchParams(search) };
  return { name: "landing" };
}

export function useHashRoute(): Route {
  const [hash, setHash] = useState(() => location.hash);

  useEffect(() => {
    const onChange = () => setHash(location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return useMemo(() => parseHash(hash), [hash]);
}

export function replaceHash(next: string): void {
  const url = `${location.pathname}${location.search}#${next}`;
  history.replaceState(null, "", url);
}

export function catalogHref(query?: URLSearchParams): string {
  const q = query?.toString();
  return q ? `#/catalog?${q}` : "#/catalog";
}

export function companyHref(slug: string): string {
  return `#/company/${encodeURIComponent(slug)}`;
}
