import { relDays } from "../lib/format";
import { companyHref } from "../lib/useHashRoute";
import type { Company } from "../lib/types";

export function CompanyCard({ company }: { company: Company }) {
  return (
    <div className="company-card">
      <a className="card-main" href={companyHref(company.slug)}>
        <div className="name">{company.display_name}</div>
        <div className="stats">
          <span className="bignum">{company.open_count || 0}</span> open ·{" "}
          {company.posting_count || 0} total
        </div>
        <div className="stats small">updated {relDays(company.last_updated)}</div>
      </a>
      {company.levels_url ? (
        <a className="card-levels" href={company.levels_url} target="_blank" rel="noopener">
          levels.fyi ↗
        </a>
      ) : null}
    </div>
  );
}
