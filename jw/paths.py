import os
import sys

HOME_ENV = "JW_HOME"
LEGACY_ROOT_ENV = "JOBWATCHER_ROOT"
DB_ENV = "JOBWATCHER_DB"
LEGACY_MARKERS = ("sources.json", "jobwatcher.db")


def code_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_home():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "jobwatcher")


def resolve_home():
    explicit = os.environ.get(HOME_ENV)
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit)), HOME_ENV
    legacy = os.environ.get(LEGACY_ROOT_ENV)
    if legacy:
        return os.path.abspath(os.path.expanduser(legacy)), LEGACY_ROOT_ENV
    checkout = code_root()
    if any(os.path.exists(os.path.join(checkout, marker)) for marker in LEGACY_MARKERS):
        return checkout, "checkout"
    return default_home(), "default"


def home():
    return resolve_home()[0]


def db_path(root=None):
    return os.environ.get(DB_ENV) or os.path.join(root or home(), "jobwatcher.db")


def sources_path(root=None):
    return os.path.join(root or home(), "sources.json")


def seen_path(root=None):
    return os.path.join(root or home(), "seen_listings.json")


def watchlist_path(root=None):
    return os.path.join(root or home(), "watchlist.json")


def collectors_path(root=None):
    return os.path.join(root or home(), "collectors.json")


def observed_path(root=None):
    return os.path.join(root or home(), "observed.json")


def tracker_dir(root=None):
    return os.path.join(root or home(), "tracker")


def companies_path(root=None):
    return os.path.join(tracker_dir(root), "companies.json")


def companies_dir(tracker_root=None):
    return os.path.join(tracker_root or tracker_dir(), "companies")


def company_dir(company_id, tracker_root=None):
    return os.path.join(companies_dir(tracker_root), company_id)


def package_site_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")


def site_dir(root=None):
    candidates = (
        os.path.join(root or home(), "docs"),
        package_site_dir(),
        os.path.join(code_root(), "docs"),
    )
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "index.html")):
            return candidate
    return candidates[0]


def starter_path(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "starter", name)
