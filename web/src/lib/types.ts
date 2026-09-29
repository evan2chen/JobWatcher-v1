export type Tier = "S" | "A" | "B" | "C";
export type Level = "intern" | "new-grad";
export type PostingState = "open" | "closed";

export const TIERS: Tier[] = ["S", "A", "B", "C"];
export const LEVELS: Level[] = ["intern", "new-grad"];

export type Company = {
  slug: string;
  display_name: string;
  tier: Tier | null;
  careers_url: string | null;
  levels_url: string | null;
  posting_count: number;
  open_count: number;
  last_updated: number;
};

export type RawPosting = {
  id: string;
  co: string;
  rk: string;
  lvl: Level | null;
  t: string;
  tm: string[];
  loc: string[];
  u: string | null;
  pa: number | null;
  fs: number | null;
  ls: number | null;
  ca: number | null;
  s: PostingState;
  cat: string;
  sp: string | null;
  deg: string[];
};

export type Posting = {
  id: string;
  companyId: string;
  roleKey: string;
  level: Level | null;
  title: string;
  terms: string[];
  locations: string[];
  applyUrl: string | null;
  postedAt: number | null;
  firstSeen: number | null;
  lastSeen: number | null;
  closedAt: number | null;
  state: PostingState;
  category: string;
  sponsorship: string | null;
  degrees: string[];

  companyName: string;
  tier: Tier | null;

  titleLower: string;
  searchText: string;
};

export type TrackerEvent = {
  at: number;
  posting_id: string;
  role_key: string;
  type: "opened" | "closed" | "reopened" | "updated";
  source: string;
  detail?: { changed?: string[] };
};

export function decodePosting(raw: RawPosting, company?: Company): Posting {
  const companyName = company?.display_name ?? raw.co;
  const titleLower = (raw.t || "").toLowerCase();
  return {
    id: raw.id,
    companyId: raw.co,
    roleKey: raw.rk,
    level: raw.lvl,
    title: raw.t,
    terms: raw.tm || [],
    locations: raw.loc || [],
    applyUrl: raw.u,
    postedAt: raw.pa,
    firstSeen: raw.fs,
    lastSeen: raw.ls,
    closedAt: raw.ca,
    state: raw.s,
    category: raw.cat || "",
    sponsorship: raw.sp,
    degrees: raw.deg || [],
    companyName,
    tier: company?.tier ?? null,
    titleLower,
    searchText: `${titleLower} ${companyName.toLowerCase()} ${(raw.loc || []).join(" ").toLowerCase()}`,
  };
}
