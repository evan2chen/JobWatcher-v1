import { useState } from "react";
import { useStore } from "../lib/store";
import type { Profile } from "../lib/profiles";
import { cmpTerm } from "../lib/format";
import { LEVELS, TIERS, type Level, type Tier } from "../lib/types";

function KeywordEditor({
  label,
  hint,
  words,
  onChange,
}: {
  label: string;
  hint: string;
  words: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const w = draft.trim().toLowerCase();
    if (w && !words.includes(w)) onChange([...words, w]);
    setDraft("");
  };

  return (
    <div className="kw-editor">
      <div className="kw-label">
        {label} <span className="muted small">{hint}</span>
      </div>
      <div className="kw-chips">
        {words.map((w) => (
          <button
            key={w}
            type="button"
            className="chip chip-removable"
            title={`Remove "${w}"`}
            onClick={() => onChange(words.filter((x) => x !== w))}
          >
            {w} <span aria-hidden="true">×</span>
          </button>
        ))}
        <input
          className="kw-input"
          value={draft}
          placeholder="add…"
          aria-label={`Add a ${label.toLowerCase()} keyword`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          onBlur={add}
        />
      </div>
    </div>
  );
}

function CheckRow<T extends string>({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: T[];
  selected: T[];
  onChange: (next: T[]) => void;
}) {
  return (
    <div className="check-row">
      <div className="kw-label">
        {label} <span className="muted small">{selected.length ? "" : "any"}</span>
      </div>
      <div className="kw-chips">
        {options.map((o) => {
          const on = selected.includes(o);
          return (
            <button
              key={o}
              type="button"
              className={`chip chip-toggle${on ? " active" : ""}`}
              aria-pressed={on}
              onClick={() => onChange(on ? selected.filter((x) => x !== o) : [...selected, o])}
            >
              {o}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ProfileBar({
  categories,
  terms,
  matchCount,
}: {
  categories: string[];
  terms: string[];
  matchCount: number;
}) {
  const { profiles, activeProfile, setActiveProfileId, updateProfile, resetProfile, isCustomized } =
    useStore();
  const [open, setOpen] = useState(false);

  const edit = (patch: Partial<Profile>) => updateProfile({ ...activeProfile, ...patch });
  const customized = isCustomized(activeProfile.id);
  const sortedTerms = [...terms].sort(cmpTerm);

  return (
    <section className="profile-bar">
      <div className="pb-row">
        <span className="pb-label">Profile</span>
        <div className="pb-tabs" role="tablist" aria-label="Application profile">
          {profiles.map((p) => (
            <button
              key={p.id}
              type="button"
              role="tab"
              aria-selected={p.id === activeProfile.id}
              className={`pb-tab${p.id === activeProfile.id ? " active" : ""}`}
              onClick={() => setActiveProfileId(p.id)}
            >
              {p.name}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <span className="muted small">{matchCount} matching</span>
        <button type="button" className="ghost-btn wide" onClick={() => setOpen((o) => !o)}>
          {open ? "Done" : "Edit"}
        </button>
      </div>

      {open ? (
        <div className="pb-editor">
          <p className="muted small">
            Keywords match the job title, case-insensitively. Exclude wins over include; the facets
            below are ANDed on top. Edits are saved in this browser only.
          </p>
          <KeywordEditor
            label="Include"
            hint="any one of these must appear"
            words={activeProfile.include}
            onChange={(include) => edit({ include })}
          />
          <KeywordEditor
            label="Exclude"
            hint="any one of these rules it out"
            words={activeProfile.exclude}
            onChange={(exclude) => edit({ exclude })}
          />
          <CheckRow
            label="Category"
            options={categories}
            selected={activeProfile.categories}
            onChange={(cats) => edit({ categories: cats })}
          />
          <CheckRow<Level>
            label="Level"
            options={LEVELS}
            selected={activeProfile.levels}
            onChange={(levels) => edit({ levels })}
          />
          <CheckRow
            label="Term"
            options={sortedTerms}
            selected={activeProfile.terms}
            onChange={(t) => edit({ terms: t })}
          />
          <div className="check-row">
            <div className="kw-label">
              Company tier <span className="muted small">{activeProfile.minTier ? "" : "any"}</span>
            </div>
            <div className="kw-chips">
              {TIERS.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`chip chip-toggle${activeProfile.minTier === t ? " active" : ""}`}
                  aria-pressed={activeProfile.minTier === t}
                  title={`${t} and above`}
                  onClick={() => edit({ minTier: activeProfile.minTier === t ? null : (t as Tier) })}
                >
                  {t}+
                </button>
              ))}
            </div>
          </div>
          <div className="pb-footer">
            <button
              type="button"
              className="ghost-btn wide"
              disabled={!customized}
              onClick={() => resetProfile(activeProfile.id)}
            >
              {customized ? "Reset to default" : "Unchanged from default"}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
