import os

_DIR = os.path.dirname(os.path.abspath(__file__))

TOPICS = (
    ("setup", "install jw, create a home, and run the first sync"),
    ("core", "the record types, ids, --full, and the help[] convention"),
    ("track-applications", "record and move your own application statuses"),
    ("write-collector", "the Observation contract, testing and registering a source"),
    ("notify", "post this sync's digest, without double-posting on a timer"),
    ("triage", "watchlist, tiers and query filters for reviewing a sync"),
)

TOPIC_NAMES = tuple(name for name, _ in TOPICS)
_SUMMARY = dict(TOPICS)


def summary(name):
    return _SUMMARY[name]


def read(name):
    path = os.path.join(_DIR, f"{name}.md")
    with open(path, encoding="utf-8") as fh:
        return fh.read().rstrip("\n")
