import { useEffect, useMemo, useState } from "react";
import { StateBadge, TierBadge } from "../components/Badges";
import { Timeline } from "../components/Timeline";
import { fetchJSONL } from "../lib/fetchers";
import { cmpTerm, fmtDate, plural, relDays } from "../lib/format";
import type { Data } from "../lib/data";
import { useStore } from "../lib/store";
import type { Posting, TrackerEvent } from "../lib/types";

function roleTitle(roleKey: string, sampleTitle?: string): string {
  return sampleTitle || roleKey.split("::").slice(2).join("::").replace(/-/g, " ");
}

function PostingRow({ posting }: { posting: Posting }) {
  const { status, setStatus } = useStore();
  const userClosed = status[posting.id]?.status === "closed";
  const dates =
    posting.state === "open"
      ? `posted ${fmtDate(posting.postedAt)} · seen ${relDays(posting.lastSeen)}`
      : `closed ${fmtDate(posting.closedAt)}`;
  return (
    <div className="posting">
      <StateBadge state={posting.state} />
      <span className="p-title">
        {posting.applyUrl ? (
          <a href={posting.applyUrl} target="_blank" rel="noopener">
            {posting.title} ↗
          </a>
        ) : (
          posting.title
        )}
      </span>
      <span className="p-loc">{posting.locations.length ? posting.locations.join(" · ") : "—"}</span>
      <span className="p-dates">{dates}</span>
      {posting.state === "open" || userClosed ? (
        <button
          type="button"
          className={`pill${userClosed ? " active" : ""}`}
          aria-pressed={userClosed}
          onClick={() => setStatus(posting.id, userClosed ? null : "closed")}
        >
          Closed
        </button>
      ) : null}
    </div>
  );
}

function Roles({ postings }: { postings: Posting[] }) {
  const roles = useMemo(() => {
    const byRole = new Map<string, Posting[]>();
    for (const p of postings) {
      const bucket = byRole.get(p.roleKey);
      if (bucket) bucket.push(p);
      else byRole.set(p.roleKey, [p]);
    }
    return [...byRole.entries()]
      .map(([key, ps]) => ({
        key,
        postings: ps,
        open: ps.filter((p) => p.state === "open").length,
      }))
      .sort((a, b) => b.open - a.open || b.postings.length - a.postings.length);
  }, [postings]);

  if (!roles.length) return <p className="muted">No postings recorded yet.</p>;

  return (
    <>
      {roles.map((role, i) => {
        const byTerm = new Map<string, Posting[]>();
        for (const p of role.postings) {
          for (const t of p.terms.length ? p.terms : ["New Grad"]) {
            const bucket = byTerm.get(t);
            if (bucket) bucket.push(p);
            else byTerm.set(t, [p]);
          }
        }
        const terms = [...byTerm.keys()].sort(cmpTerm);
        return (
          <details key={role.key} className="role" open={i === 0}>
            <summary>
              {roleTitle(role.key, role.postings[0]?.title)}{" "}
              <span className="count">
                · {role.open} open / {role.postings.length} total
              </span>
            </summary>
            {terms.map((t) => (
              <div key={t} className="term-block">
                <div className="term-title">{t}</div>
                {[...byTerm.get(t)!]
                  .sort((a, b) => (b.postedAt ?? 0) - (a.postedAt ?? 0))
                  .map((p) => (
                    <PostingRow key={p.id} posting={p} />
                  ))}
              </div>
            ))}
          </details>
        );
      })}
    </>
  );
}

export function Company({ data, slug }: { data: Data; slug: string }) {
  const [tab, setTab] = useState<"roles" | "timeline">("roles");
  const [events, setEvents] = useState<TrackerEvent[] | null>(null);

  const company = data.byslug.get(slug);
  const postings = useMemo(
    () => data.postings.filter((p) => p.companyId === slug),
    [data.postings, slug],
  );
  const openCount = postings.filter((p) => p.state === "open").length;

  useEffect(() => {
    let cancelled = false;
    setEvents(null);
    fetchJSONL<TrackerEvent>(`tracker/companies/${slug}/events.jsonl`)
      .catch(() => [] as TrackerEvent[])
      .then((rows) => {
        if (!cancelled) setEvents(rows);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  return (
    <>
      <a href="#/catalog?view=companies" className="back muted">
        ← all companies
      </a>
      <div className="detail-head">
        <TierBadge tier={company?.tier ?? null} />
        <h1>{company?.display_name ?? slug}</h1>
      </div>
      <p className="muted small">
        {openCount} open · {plural(postings.length, "total posting")}
        {company?.careers_url ? (
          <>
            {" · "}
            <a href={company.careers_url} target="_blank" rel="noopener">
              careers ↗
            </a>
          </>
        ) : null}
        {company?.levels_url ? (
          <>
            {" · "}
            <a href={company.levels_url} target="_blank" rel="noopener">
              levels.fyi ↗
            </a>
          </>
        ) : null}
      </p>

      <div className="tabs" role="tablist">
        {(["roles", "timeline"] as const).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={`tab${tab === t ? " active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t === "roles" ? "Roles" : "Timeline"}
          </button>
        ))}
      </div>

      {tab === "roles" ? (
        <Roles postings={postings} />
      ) : events === null ? (
        <p className="loading">Loading history…</p>
      ) : (
        <Timeline postings={postings} events={events} />
      )}
    </>
  );
}
