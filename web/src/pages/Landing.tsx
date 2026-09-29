import { useMemo, useState } from "react";
import { PostingCard } from "../components/PostingCard";
import { ProfileBar } from "../components/ProfileBar";
import { useFacetValues, type Data } from "../lib/data";
import { matchesProfile, rankAll } from "../lib/profiles";
import { useStore } from "../lib/store";
import { plural } from "../lib/format";
import { catalogHref } from "../lib/useHashRoute";

const INITIAL_SHOWN = 25;

export function Landing({ data }: { data: Data }) {
  const { activeProfile, status, lastVisit, clearAllStatus } = useStore();
  const [showAll, setShowAll] = useState(false);
  const facets = useFacetValues(data.postings);

  const openPostings = useMemo(
    () => data.postings.filter((p) => p.state === "open"),
    [data.postings],
  );

  const matched = useMemo(
    () => openPostings.filter((p) => matchesProfile(p, activeProfile)),
    [openPostings, activeProfile],
  );

  const ranked = useMemo(() => {
    const pending = matched.filter((p) => {
      const s = status[p.id]?.status;
      return s !== "applied" && s !== "skipped";
    });
    return rankAll(pending, activeProfile);
  }, [matched, status, activeProfile]);

  const freshCount = useMemo(
    () => (lastVisit ? matched.filter((p) => (p.firstSeen ?? 0) > lastVisit).length : 0),
    [matched, lastVisit],
  );

  const tracked = useMemo(() => {
    let applied = 0;
    let skipped = 0;
    for (const entry of Object.values(status)) {
      if (entry.status === "applied") applied++;
      else if (entry.status === "skipped") skipped++;
    }
    return { applied, skipped };
  }, [status]);

  const shown = showAll ? ranked : ranked.slice(0, INITIAL_SHOWN);

  const exportStatus = () => {
    void navigator.clipboard
      ?.writeText(JSON.stringify(status, null, 2))
      .then(() => alert("Application status copied to the clipboard as JSON."))
      .catch(() => alert("Couldn't reach the clipboard. Open the console and read localStorage['jw-status']."));
  };

  return (
    <>
      <h1>Must apply</h1>
      <p className="muted small">
        {plural(ranked.length, "open role")} match your{" "}
        <strong>{activeProfile.name}</strong> profile
        {freshCount > 0 ? ` · ${freshCount} new since your last visit` : ""}
        {" · "}
        <a href={catalogHref()}>browse the full catalog</a>
      </p>

      <ProfileBar
        categories={facets.categories}
        terms={facets.terms}
        matchCount={matched.length}
      />

      {ranked.length === 0 ? (
        <p className="empty">
          Nothing open matches this profile right now. Widen the include keywords or drop a facet
          in <strong>Edit</strong> above, or <a href={catalogHref()}>browse everything</a>.
        </p>
      ) : (
        <div className="posting-list">
          {shown.map((r) => (
            <PostingCard key={r.posting.id} posting={r.posting} reasons={r.reasons} />
          ))}
        </div>
      )}

      {!showAll && ranked.length > INITIAL_SHOWN ? (
        <button type="button" className="ghost-btn block" onClick={() => setShowAll(true)}>
          Show all {ranked.length}
        </button>
      ) : null}

      {tracked.applied || tracked.skipped ? (
        <p className="muted small tracking-line">
          Tracking {plural(tracked.applied, "application")} and {tracked.skipped} skipped, in this
          browser only. <button type="button" className="linkish" onClick={exportStatus}>Export JSON</button>{" "}
          ·{" "}
          <button
            type="button"
            className="linkish"
            onClick={() => {
              if (confirm("Clear every applied/skipped/interested mark in this browser?")) {
                clearAllStatus();
              }
            }}
          >
            Clear
          </button>
        </p>
      ) : null}
    </>
  );
}
