import { fmtDate, relDays } from "../lib/format";
import { companyHref } from "../lib/useHashRoute";
import { useStore, type StatusValue } from "../lib/store";
import type { Posting } from "../lib/types";
import { Chip, StateBadge, TierBadge } from "./Badges";

const ACTIONS: { value: StatusValue; label: string }[] = [
  { value: "applied", label: "Applied" },
  { value: "interested", label: "Interested" },
  { value: "skipped", label: "Skip" },
  { value: "closed", label: "Closed" },
];

export function PostingCard({ posting, reasons }: { posting: Posting; reasons?: string[] }) {
  const { status, setStatus } = useStore();
  const current = status[posting.id]?.status ?? null;

  const dates =
    posting.state === "open"
      ? `posted ${fmtDate(posting.postedAt)} · seen ${relDays(posting.lastSeen)}`
      : `closed ${fmtDate(posting.closedAt)}`;

  return (
    <article className={`posting-card${current ? ` is-${current}` : ""}`}>
      <div className="pc-head">
        <TierBadge tier={posting.tier} />
        <a className="pc-company" href={companyHref(posting.companyId)}>
          {posting.companyName}
        </a>
        <StateBadge state={posting.state} />
        <span className="spacer" />
        <span className="pc-dates muted small">{dates}</span>
      </div>

      <h3 className="pc-title">
        {posting.applyUrl ? (
          <a href={posting.applyUrl} target="_blank" rel="noopener">
            {posting.title} ↗
          </a>
        ) : (
          posting.title
        )}
      </h3>

      <div className="pc-meta">
        {posting.terms.map((t) => (
          <Chip key={t} tone="accent">
            {t}
          </Chip>
        ))}
        {posting.category ? <Chip tone="muted">{posting.category}</Chip> : null}
        <span className="pc-loc muted small">
          {posting.locations.length ? posting.locations.join(" · ") : "—"}
        </span>
      </div>

      {reasons?.length ? (
        <div className="pc-why">
          {reasons.map((r) => (
            <span key={r} className="why">
              {r}
            </span>
          ))}
        </div>
      ) : null}

      <div className="pc-actions">
        {ACTIONS.map((a) => (
          <button
            key={a.value}
            type="button"
            className={`pill${current === a.value ? " active" : ""}`}
            aria-pressed={current === a.value}
            onClick={() => setStatus(posting.id, current === a.value ? null : a.value)}
          >
            {a.label}
          </button>
        ))}
      </div>
    </article>
  );
}
