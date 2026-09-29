import json
import os

from . import paths


def _read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def watchlist_list(root=None):
    path = paths.watchlist_path(root)
    terms = _read(path, [])
    return terms if isinstance(terms, list) else []


def watchlist_add(term, root=None, dry_run=False):
    term = (term or "").strip()
    if not term:
        raise ValueError("term is required")
    path = paths.watchlist_path(root)
    terms = watchlist_list(root)
    if any(t.strip().lower() == term.lower() for t in terms):
        return {"changed": False, "reason": "already present", "term": term,
                "count": len(terms)}
    if not dry_run:
        _write(path, terms + [term])
    return {"changed": True, "term": term, "count": len(terms) + 1}


def watchlist_remove(term, root=None, dry_run=False):
    term = (term or "").strip()
    path = paths.watchlist_path(root)
    terms = watchlist_list(root)
    kept = [t for t in terms if t.strip().lower() != term.lower()]
    if len(kept) == len(terms):
        return {"changed": False, "reason": "not found", "term": term, "count": len(terms)}
    if not dry_run:
        _write(path, kept)
    return {"changed": True, "term": term, "count": len(kept)}


def _companies_path(root=None):
    return paths.companies_path(root)


def companies_list(root=None):
    data = _read(_companies_path(root), [])
    return data if isinstance(data, list) else []


def company_add(company_id, display_name=None, aliases=None, tier=None,
                careers_url=None, levels_url=None, notes="", root=None, dry_run=False):
    company_id = (company_id or "").strip().lower()
    if not company_id:
        raise ValueError("company id (slug) is required")
    companies = companies_list(root)
    aliases = [a for a in (aliases or []) if a and a.strip()]

    existing = next((c for c in companies if c.get("id") == company_id), None)
    if existing is not None:
        current = existing.get("aliases", {}).get("*", [])
        added = [a for a in aliases
                 if a.lower() not in {c.lower() for c in current}]
        if not added:
            return {"changed": False, "reason": "already tracked", "id": company_id}
        existing.setdefault("aliases", {}).setdefault("*", []).extend(added)
        if not dry_run:
            _write(_companies_path(root), companies)
        return {"changed": True, "id": company_id, "aliases_added": added}

    record = {
        "id": company_id,
        "display_name": display_name or company_id.replace("-", " ").title(),
        "tier": tier,
        "careers_url": careers_url,
        "levels_url": levels_url,
        "aliases": {"*": aliases or [display_name or company_id]},
        "notes": notes or "",
    }
    if not dry_run:
        _write(_companies_path(root), companies + [record])
    return {"changed": True, "id": company_id, "added": record}


def companies_append(records, root=None):
    _write(_companies_path(root), companies_list(root) + list(records))


def company_remove(company_id, root=None, dry_run=False):
    company_id = (company_id or "").strip().lower()
    companies = companies_list(root)
    kept = [c for c in companies if c.get("id") != company_id]
    if len(kept) == len(companies):
        return {"changed": False, "reason": "not tracked", "id": company_id}
    if not dry_run:
        _write(_companies_path(root), kept)
    store = paths.company_dir(company_id, paths.tracker_dir(root))
    return {
        "changed": True,
        "id": company_id,
        "store_kept": os.path.isdir(store),
        "note": "posting history left in place; delete tracker/companies/%s to discard it"
                % company_id,
    }


def refresh_companies_table(con, root=None):
    from .importer import _import_companies

    con.execute("DELETE FROM companies")
    n = _import_companies(con, root or paths.home())
    con.commit()
    return n
