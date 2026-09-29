SLACK_MAX_CHARS = 3900

CATEGORY_CANON = {
    "software": "Software",
    "software engineering": "Software",
    "ai/ml/data": "AI/ML/Data",
    "data science, ai & machine learning": "AI/ML/Data",
    "hardware": "Hardware",
    "hardware engineering": "Hardware",
    "quant": "Quant",
    "quantitative finance": "Quant",
    "product": "Product",
    "product management": "Product",
}


def normalize_category(raw):
    if not raw:
        return raw
    return CATEGORY_CANON.get(str(raw).strip().lower(), raw)


def normalize_watchlist(terms):
    return [str(t).strip().lower() for t in terms or [] if str(t).strip()]


def matches_watchlist(company_name, watchlist):
    if not watchlist:
        return False
    name = (company_name or "").strip().lower()
    if not name:
        return False
    return name in set(watchlist)


def _fmt_listing(s, with_source=False):
    loc = (s.get("locations") or ["—"])[0]
    company = s.get("company_name") or "?"
    title = s.get("title") or "?"
    url = s.get("url") or ""
    tail = f"  ({s.get('source_repo')})" if with_source else ""
    return f"• {company} — {title} — {loc}  <{url}|apply>{tail}"


def build_slack_message(survivors_by_source, watchlist=None):
    watchlist = watchlist or []
    total = sum(len(v) for v in survivors_by_source.values())
    lines = [f"*JobWatcher: {total} new listing{'s' if total != 1 else ''}*"]

    interest, rest = [], {}
    for source, survivors in survivors_by_source.items():
        for s in survivors:
            if matches_watchlist(s.get("company_name"), watchlist):
                interest.append(s)
            else:
                rest.setdefault(source, []).append(s)

    if interest:
        lines.append(f"\n<!channel> :star: *Companies of interest* ({len(interest)})")
        for s in interest:
            lines.append(_fmt_listing(s, with_source=True))

    for source, survivors in rest.items():
        if not survivors:
            continue
        lines.append(f"\n*{source}* ({len(survivors)})")
        for s in survivors:
            lines.append(_fmt_listing(s))
    return "\n".join(lines)


def split_slack_message(text, limit=SLACK_MAX_CHARS):
    chunks, current, current_len = [], [], 0
    for line in text.split("\n"):
        if len(line) > limit:
            line = line[:limit]
        add = len(line) + (1 if current else 0)
        if current and current_len + add > limit:
            chunks.append("\n".join(current))
            current, current_len = [line], len(line)
        else:
            current.append(line)
            current_len += add
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]
