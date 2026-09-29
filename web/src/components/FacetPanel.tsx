export type FacetOption = { value: string; label?: string; count: number };

export function FacetGroup({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: FacetOption[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  if (!options.length) return null;
  return (
    <fieldset className="facet-group">
      <legend>{label}</legend>
      {options.map((o) => {
        const on = selected.includes(o.value);
        return (
          <label key={o.value} className={`facet${o.count === 0 && !on ? " empty" : ""}`}>
            <input type="checkbox" checked={on} onChange={() => onToggle(o.value)} />
            <span className="facet-name">{o.label ?? o.value}</span>
            <span className="facet-count muted small">{o.count}</span>
          </label>
        );
      })}
    </fieldset>
  );
}
