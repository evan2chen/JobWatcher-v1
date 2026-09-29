import { useMemo, useState } from "react";
import { cmpTerm, fmtDate } from "../lib/format";
import type { Posting, TrackerEvent } from "../lib/types";

const CAP = 400;

export function Timeline({ postings, events }: { postings: Posting[]; events: TrackerEvent[] }) {
  const [term, setTerm] = useState("");
  const [type, setType] = useState("");

  const byId = useMemo(() => new Map(postings.map((p) => [p.id, p])), [postings]);

  const terms = useMemo(() => {
    const set = new Set<string>();
    for (const p of postings) for (const t of p.terms) set.add(t);
    return [...set].sort(cmpTerm);
  }, [postings]);

  const rows = useMemo(() => {
    return events
      .filter((e) => {
        if (type && e.type !== type) return false;
        if (term) {
          const p = byId.get(e.posting_id);
          if (!p || !p.terms.includes(term)) return false;
        }
        return true;
      })
      .sort((a, b) => (b.at || 0) - (a.at || 0));
  }, [events, type, term, byId]);

  return (
    <>
      <div className="tl-filters">
        <select value={term} onChange={(e) => setTerm(e.target.value)} aria-label="Filter by term">
          <option value="">All terms</option>
          {terms.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Filter by event type">
          <option value="">All events</option>
          <option value="opened">Opened</option>
          <option value="closed">Closed</option>
          <option value="reopened">Reopened</option>
          <option value="updated">Updated</option>
        </select>
      </div>

      <ul className="tl">
        {rows.length === 0 ? (
          <li className="muted small tl-empty">No events for this filter.</li>
        ) : (
          rows.slice(0, CAP).map((e, i) => {
            const p = byId.get(e.posting_id);
            const title =
              p?.title ?? e.role_key.split("::").slice(2).join(" ").replace(/-/g, " ");
            const detail =
              e.type === "updated" && e.detail?.changed
                ? `changed ${e.detail.changed.join(", ")}`
                : "";
            return (
              <li key={`${e.at}-${e.posting_id}-${e.type}-${i}`} className="tl-item">
                <div className="tl-when">{fmtDate(e.at)}</div>
                <div className={`tl-dot ${e.type}`} />
                <div className="tl-body">
                  <span className="tl-type">{e.type}</span> <span className="tl-title">{title}</span>
                  {detail ? <div className="tl-detail">{detail}</div> : null}
                </div>
              </li>
            );
          })
        )}
        {rows.length > CAP ? (
          <li className="muted small tl-empty">
            Showing latest {CAP} of {rows.length} events.
          </li>
        ) : null}
      </ul>
    </>
  );
}
