#!/usr/bin/env python3

import re
import unicodedata


SEASONS = {
    "spring": "Spring",
    "summer": "Summer",
    "fall": "Fall",
    "autumn": "Fall",
    "winter": "Winter",
}
NEW_GRAD_BUCKET = "New Grad"

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_SEASON_RE = re.compile(r"\b(spring|summer|fall|autumn|winter)\b", re.IGNORECASE)


def canonical_term(term):
    if not term:
        return None
    s = str(term)
    season_m = _SEASON_RE.search(s)
    year_m = _YEAR_RE.search(s)
    if not season_m:
        return None
    season = SEASONS[season_m.group(1).lower()]
    if year_m:
        return f"{season} {year_m.group(1)}"
    return season


def canonical_terms(terms, level=None):
    if level == "new-grad":
        return [NEW_GRAD_BUCKET]
    out = []
    for t in terms or []:
        c = canonical_term(t)
        if c and c not in out:
            out.append(c)
    if not out:
        return [NEW_GRAD_BUCKET]
    return sorted(out)


def primary_term(terms, level=None):
    canon = canonical_terms(terms, level)
    return canon[0] if canon else NEW_GRAD_BUCKET


_ABBREVIATIONS = {
    "swe": "software engineer",
    "sde": "software engineer",
    "sdet": "software engineer in test",
    "sre": "site reliability engineer",
    "ml": "machine learning",
    "nlp": "natural language processing",
    "ai": "artificial intelligence",
    "pm": "product manager",
    "hw": "hardware",
    "qa": "quality assurance",
}

_NOISE = {
    "intern", "interns", "internship", "internships", "co", "op", "coop",
    "program", "new", "grad", "graduate", "graduates", "university", "student",
    "students", "fulltime", "parttime", "temporary", "temp", "contract",
    "spring", "summer", "fall", "autumn", "winter",
    "the", "a", "an", "of", "for", "and", "to", "at", "in",
}

_TERM_YEAR_RE = re.compile(r"\b20\d{2}\b")
_PAREN_RE = re.compile(r"[\(\[\{].*?[\)\]\}]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _title_tokens(title):
    if not title:
        return []
    s = unicodedata.normalize("NFKD", str(title)).encode("ascii", "ignore").decode()
    s = s.lower()
    s = _PAREN_RE.sub(" ", s)
    s = _TERM_YEAR_RE.sub(" ", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    tokens = []
    for tok in s.split():
        tok = _ABBREVIATIONS.get(tok, tok)
        tokens.extend(tok.split())
    tokens = [t for t in tokens if t not in _NOISE]
    return tokens


def normalize_title(title):
    return " ".join(_title_tokens(title))


def title_slug(title):
    return "-".join(_title_tokens(title))


_COMPANY_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "plc", "group", "holdings", "technologies", "technology",
    "labs", "the",
}


def normalize_company(name):
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    tokens = [t for t in s.split() if t not in _COMPANY_SUFFIXES]
    return " ".join(tokens).strip()


def slugify(text):
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    s = s.lower()
    s = _NON_ALNUM_RE.sub("-", s)
    return s.strip("-")


_CATEGORY_ALIASES = {
    "software": "Software",
    "software engineering": "Software",
    "hardware": "Hardware",
    "hardware engineering": "Hardware",
    "ai ml data": "AI/ML/Data",
    "data science ai machine learning": "AI/ML/Data",
    "product": "Product",
    "quant": "Quant",
}


def canonical_category(category):
    if not category:
        return ""
    key = " ".join(_NON_ALNUM_RE.sub(" ", str(category).lower()).split())
    return _CATEGORY_ALIASES.get(key, str(category).strip())


def normalize_location(loc):
    if not loc:
        return ""
    s = unicodedata.normalize("NFKD", str(loc)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def primary_location(locations):
    for loc in locations or []:
        key = normalize_location(loc)
        if key:
            return key
    return ""


def normalize_url(url):
    if not url:
        return ""
    s = str(url).strip()
    s = s.split("#", 1)[0]
    s = s.split("?", 1)[0]
    m = re.match(r"^(https?://)?(.*)$", s, re.IGNORECASE)
    rest = m.group(2) if m else s
    if "/" in rest:
        host, path = rest.split("/", 1)
        rest = host.lower() + "/" + path
    else:
        rest = rest.lower()
    return rest.rstrip("/")


def role_key(company_id, level, title):
    return f"{company_id}::{level or 'unknown'}::{title_slug(title)}"


def natural_key(company_id, level, title, terms, locations, url):
    parts = [
        company_id,
        level or "unknown",
        title_slug(title),
        primary_term(terms, level),
        primary_location(locations),
        normalize_url(url),
    ]
    return " | ".join(parts)
