from .digest import matches_watchlist, normalize_category


def active_visible(obs, filters):
    state = obs.get("state_raw") or {}
    if filters.get("active_only", True) and not state.get("active", True):
        return False
    if filters.get("visible_only", True) and not state.get("is_visible", True):
        return False
    return True


def passes(obs, filters):
    if not active_visible(obs, filters):
        return False

    categories = filters.get("categories") or []
    if categories:
        canon = normalize_category((obs.get("extra") or {}).get("category"))
        if canon not in {normalize_category(c) for c in categories}:
            return False

    keywords = filters.get("title_keywords") or []
    if keywords:
        title = (obs.get("title_raw") or "").lower()
        if not any(kw.lower() in title for kw in keywords):
            return False

    locations = filters.get("locations") or []
    if locations:
        haystack = " ".join(obs.get("locations") or []).lower()
        if not any(loc.lower() in haystack for loc in locations):
            return False

    return True


def surfaces(obs, filters, watchlist):
    return passes(obs, filters) or (
        matches_watchlist(obs.get("company_raw"), watchlist)
        and active_visible(obs, filters)
    )
