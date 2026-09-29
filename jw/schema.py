MAX_TIMESTAMP = 4102444800
LEVELS = ("intern", "new-grad", "unknown")

_TIMESTAMP = {"type": "integer", "minimum": 0, "maximum": MAX_TIMESTAMP}

OBSERVATION = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "JobWatcher Observation",
    "description": (
        "One job posting as one source saw it. A collector prints one JSON object per "
        "line (JSONL) on stdout; `jw ingest` reads the same lines from stdin."
    ),
    "type": "object",
    "required": ["source", "external_id", "company_raw", "title_raw"],
    "additionalProperties": False,
    "properties": {
        "source": {
            "type": "string", "minLength": 1,
            "description": "The registered source name, constant for one collector, "
                           "for example greenhouse:acme.",
        },
        "external_id": {
            "type": "string", "minLength": 1,
            "description": "Stable id within the source and unique across all sources: "
                           "prefix short numeric ids with the source name. Use the "
                           "posting URL when the site has no id.",
        },
        "company_raw": {
            "type": "string", "minLength": 1,
            "description": "Company name exactly as the source spells it. jw maps it to "
                           "a tracked company by alias.",
        },
        "title_raw": {
            "type": "string", "minLength": 1,
            "description": "Job title exactly as the source spells it.",
        },
        "observed_at": {
            **_TIMESTAMP,
            "description": "Epoch seconds when the collector saw the posting. Optional.",
        },
        "level": {
            "type": "string", "enum": list(LEVELS),
            "description": "intern or new-grad; unknown when neither applies (default).",
        },
        "terms": {
            "type": "array", "items": {"type": "string"},
            "description": "Season and year strings such as 'Summer 2027'. Leave empty "
                           "for new-grad roles.",
        },
        "locations": {
            "type": "array", "items": {"type": "string"},
            "description": "Locations as the source lists them.",
        },
        "url": {
            "type": ["string", "null"],
            "description": "The apply link.",
        },
        "posted_at": {
            "type": ["integer", "null"], "minimum": 0, "maximum": MAX_TIMESTAMP,
            "description": "Epoch SECONDS when the source published the posting, when known.",
        },
        "updated_at": {
            "type": ["integer", "null"], "minimum": 0, "maximum": MAX_TIMESTAMP,
            "description": "Epoch seconds when the source last edited the posting.",
        },
        "state_raw": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "active": {"type": "boolean"},
                "is_visible": {"type": "boolean"},
            },
            "description": "Set active or is_visible to false ONLY when the source "
                           "explicitly reports the posting closed. A posting that is "
                           "merely absent from the feed stays open.",
        },
        "extra": {
            "type": "object",
            "description": "Anything else worth keeping. category (Software, AI/ML/Data, "
                           "Hardware, Quant, Product), sponsorship and degrees feed the "
                           "UI filters and the digest filters.",
        },
    },
}

EXAMPLE = {
    "source": "acme-careers",
    "external_id": "acme-careers:4711",
    "company_raw": "Acme Corp",
    "title_raw": "Software Engineer Intern",
    "level": "intern",
    "terms": ["Summer 2027"],
    "locations": ["New York, NY"],
    "url": "https://acme.example/careers/4711",
    "posted_at": 1790000000,
    "state_raw": {"active": True, "is_visible": True},
    "extra": {"category": "Software"},
}

_TYPE_NAMES = {
    "string": str, "integer": int, "boolean": bool, "object": dict, "array": list,
    "null": type(None),
}


def _json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _matches(value, type_name):
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    return isinstance(value, _TYPE_NAMES[type_name])


def _join(path, key):
    return f"{path}.{key}" if path else key


def validate(value, schema=OBSERVATION, path=""):
    label = path or "observation"
    types = schema.get("type")
    if types is not None:
        wanted = types if isinstance(types, list) else [types]
        if not any(_matches(value, t) for t in wanted):
            return [f"{label}: must be {' or '.join(wanted)}, got {_json_type(value)}"]

    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{label}: must be one of {', '.join(map(str, schema['enum']))}")
    if isinstance(value, str) and schema.get("minLength") and len(value.strip()) < 1:
        errors.append(f"{label}: must not be empty")
    if isinstance(value, int) and not isinstance(value, bool):
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            hint = " (looks like milliseconds; use epoch seconds)" if value // 1000 <= maximum else ""
            errors.append(f"{label}: must be at most {maximum}{hint}")
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{label}: must be at least {minimum}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{_join(path, key)}: is required")
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], _join(path, key)))
            elif schema.get("additionalProperties") is False:
                where = " (put extra data under 'extra')" if not path else ""
                errors.append(f"{_join(path, key)}: unexpected field{where}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{label}[{index}]"))
    return errors


def normalize(obs, now):
    out = dict(obs)
    out.setdefault("level", "unknown")
    out.setdefault("terms", [])
    out.setdefault("locations", [])
    out.setdefault("url", None)
    out.setdefault("posted_at", None)
    out.setdefault("state_raw", {})
    out.setdefault("extra", {})
    out.setdefault("observed_at", now)
    return out
