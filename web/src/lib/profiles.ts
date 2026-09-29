import { daysSince, tierRank } from "./format";
import type { Level, Posting, Tier } from "./types";

export type Profile = {
  id: string;
  name: string;
  include: string[];
  exclude: string[];
  categories: string[];
  levels: Level[];
  terms: string[];
  minTier: Tier | null;
};

export const PRESET_PROFILES: Profile[] = [
  {
    id: "swe",
    name: "Software Engineering",
    include: [
      "software", "engineer", "swe", "backend", "back end", "frontend", "front end",
      "full stack", "fullstack", "platform", "infrastructure", "distributed",
      "systems", "developer", "compiler", "security",
    ],
    exclude: ["sales", "recruit", "marketing", "mechanical", "civil", "chemical"],
    categories: ["Software"],
    levels: [],
    terms: [],
    minTier: null,
  },
  {
    id: "ml-research",
    name: "ML / AI Research",
    include: [
      "machine learning", "research", "scientist", "deep learning", "nlp",
      "natural language", "computer vision", "llm", "ai ", "artificial intelligence",
      "fellow", "model", "alignment",
    ],
    exclude: ["sales", "recruit", "marketing", "market research", "user research"],
    categories: ["AI/ML/Data"],
    levels: [],
    terms: [],
    minTier: null,
  },
  {
    id: "quant",
    name: "Quant / Trading",
    include: ["quant", "trading", "trader", "quantitative", "algorithmic", "strategist"],
    exclude: ["sales"],
    categories: ["Quant"],
    levels: [],
    terms: [],
    minTier: null,
  },
  {
    id: "hardware",
    name: "Hardware / Embedded",
    include: [
      "hardware", "embedded", "firmware", "fpga", "asic", "silicon", "electrical",
      "verification", "chip", "rtl", "physical design", "signal",
    ],
    exclude: ["sales", "recruit", "marketing"],
    categories: ["Hardware"],
    levels: [],
    terms: [],
    minTier: null,
  },
];

export function presetFor(id: string): Profile | undefined {
  return PRESET_PROFILES.find((p) => p.id === id);
}

function anyKeyword(haystack: string, needles: string[]): boolean {
  for (const n of needles) {
    const k = n.trim().toLowerCase();
    if (k && haystack.includes(k)) return true;
  }
  return false;
}

function hasOverlap(a: string[], b: string[]): boolean {
  for (const x of a) if (b.includes(x)) return true;
  return false;
}

export function matchesProfile(p: Posting, prof: Profile): boolean {
  const haystack = p.titleLower || p.roleKey.toLowerCase();
  if (anyKeyword(haystack, prof.exclude)) return false;
  if (prof.include.length && !anyKeyword(haystack, prof.include)) return false;
  if (prof.categories.length && !prof.categories.includes(p.category)) return false;
  if (prof.levels.length && (!p.level || !prof.levels.includes(p.level))) return false;
  if (prof.terms.length && !hasOverlap(p.terms, prof.terms)) return false;
  if (prof.minTier && tierRank(p.tier) > tierRank(prof.minTier)) return false;
  return true;
}

export type Ranked = { posting: Posting; score: number; reasons: string[] };

const TIER_POINTS: Record<Tier, number> = { S: 4, A: 3, B: 2, C: 1 };

export function rankPosting(p: Posting, prof: Profile): Ranked {
  const reasons: string[] = [];
  let score = 0;

  if (p.tier) {
    score += TIER_POINTS[p.tier];
    if (p.tier === "S" || p.tier === "A") reasons.push(`tier ${p.tier}`);
  }

  const age = daysSince(p.firstSeen);
  if (age <= 7) {
    score += 3;
    reasons.push("new this week");
  } else if (age <= 21) {
    score += 1;
  }

  const opening = p.titleLower.slice(0, 32);
  if (prof.include.length && anyKeyword(opening, prof.include)) {
    score += 2;
    reasons.push("strong title match");
  }

  if (p.sponsorship === "Offers Sponsorship") {
    score += 1;
    reasons.push("offers sponsorship");
  }

  return { posting: p, score, reasons };
}

export function rankAll(postings: Posting[], prof: Profile): Ranked[] {
  return postings
    .map((p) => rankPosting(p, prof))
    .sort(
      (a, b) =>
        b.score - a.score ||
        (b.posting.firstSeen ?? 0) - (a.posting.firstSeen ?? 0) ||
        a.posting.companyName.localeCompare(b.posting.companyName),
    );
}
