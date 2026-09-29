import { tierClass } from "../lib/format";
import type { PostingState, Tier } from "../lib/types";

export function TierBadge({ tier }: { tier: Tier | null }) {
  return <span className={`tier-badge ${tierClass(tier)}`}>{tier ?? "—"}</span>;
}

export function StateBadge({ state }: { state: PostingState }) {
  return <span className={`badge ${state === "open" ? "open" : "closed"}`}>{state}</span>;
}

export function Chip({ children, tone }: { children: React.ReactNode; tone?: "accent" | "muted" }) {
  return <span className={`chip${tone ? ` chip-${tone}` : ""}`}>{children}</span>;
}
