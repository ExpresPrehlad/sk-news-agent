"""Output contracts only; editorial policy remains in digest.py prompts."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


BOOL_SIGNALS = (
    "direct_slovak_relevance", "ongoing_danger", "public_impact",
    "strategic_infrastructure", "mass_casualty", "terrorism",
    "public_transport", "hazardous_materials",
)


def _without_tracking(url: str) -> str:
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in
             {"fbclid", "gclid", "mc_cid", "mc_eid"}]
    # Keep host, article path, functional query arguments and fragments intact.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def resolve_source_link(link: str, allowed_links: set[str]) -> str:
    """Return an INPUT URL, tolerating only differences in tracking parameters."""
    if link in allowed_links:
        return link
    canonical = _without_tracking(link)
    for original in sorted(allowed_links):
        if _without_tracking(original) == canonical:
            return original
    raise ValueError("source link is not present in input articles")


def selection_schema(task: str) -> dict:
    key = "alerts" if task == "triage" else "topics"
    fields = ("title", "reason") if task == "triage" else ("headline", "perex")
    properties = {field: {"type": "string"} for field in fields}
    properties["links"] = {
        "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3,
    }
    required = [*fields, "links"]
    if task == "triage":
        signals = {
            "geography": {"type": "string"},
            "event_type": {"type": "string"},
            **{name: {"type": "boolean"} for name in BOOL_SIGNALS},
        }
        properties["signals"] = {
            "type": "object", "properties": signals,
            "required": list(signals), "additionalProperties": False,
        }
        required.append("signals")
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "array", "minItems": 0 if task == "triage" else 1,
                "maxItems": 5 if task == "triage" else 10,
                "items": {
                    "type": "object", "properties": properties,
                    "required": required, "additionalProperties": False,
                },
            },
        },
        "required": [key], "additionalProperties": False,
    }


def validate_selection(text: str, task: str, allowed_links: set[str]) -> None:
    """Validate BEFORE accepting a model. Never repair a truncated decision.

    Tolerate legacy Markdown fences and optional signals, but not wrong task
    objects, missing content, invented links or a partial/malformed JSON reply.
    An empty alerts array is a valid decision and does not trigger another call.
    """
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("missing JSON object")
    data = json.loads(cleaned[start:end + 1])
    key = "alerts" if task == "triage" else "topics"
    if not isinstance(data, dict) or set(data) != {key}:
        raise ValueError("wrong selection task or root fields")
    items = data[key]
    if not isinstance(items, list):
        raise ValueError("selection must be an array")
    if task == "synthesis" and not items:
        raise ValueError("empty topics are not a usable digest")
    if len(items) > (5 if task == "triage" else 10):
        raise ValueError("too many selections")
    fields = ("title", "reason") if task == "triage" else ("headline", "perex")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("selection item must be an object")
        for field in fields:
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"missing selection field: {field}")
        links = item.get("links")
        if not isinstance(links, list) or not 1 <= len(links) <= 3:
            raise ValueError("missing or invalid source links")
        for link in links:
            if not isinstance(link, str):
                raise ValueError("source link must be a string")
            resolve_source_link(link, allowed_links)
        if task == "triage" and "signals" in item and not isinstance(item["signals"], dict):
            raise ValueError("invalid decision signals")
