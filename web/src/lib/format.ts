import type { Tier } from "./types";

export const DAY = 86400;

export function fmtDate(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function relDays(ts: number | null | undefined): string {
  if (!ts) return "";
  const days = Math.floor(Date.now() / 1000 / DAY - ts / DAY);
  if (days <= 0) return "today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  const mo = Math.floor(days / 30);
  return `${mo} ${mo === 1 ? "month" : "months"} ago`;
}

export function daysSince(ts: number | null | undefined): number {
  if (!ts) return Infinity;
  return (Date.now() / 1000 - ts) / DAY;
}

const SEASON_ORDER: Record<string, number> = { Spring: 0, Summer: 1, Fall: 2, Winter: 3 };
const SEASON_RE = /^(Spring|Summer|Fall|Winter)\s+(\d{4})$/;

function termRank(term: string): [number, number] {
  if (term === "New Grad") return [1e9, 0];
  const m = SEASON_RE.exec(term || "");
  if (!m) return [1e8, 0];
  return [parseInt(m[2], 10), SEASON_ORDER[m[1]]];
}

export function cmpTerm(a: string, b: string): number {
  const ra = termRank(a);
  const rb = termRank(b);
  return ra[0] - rb[0] || ra[1] - rb[1];
}

export function tierClass(t: Tier | null | undefined): string {
  return t ? `tier-${t}` : "tier-none";
}

export function tierRank(t: Tier | null | undefined): number {
  const i = t ? ["S", "A", "B", "C"].indexOf(t) : -1;
  return i === -1 ? 99 : i;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
