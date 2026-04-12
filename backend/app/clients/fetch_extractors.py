from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

MAX_FETCH_TEXT_LENGTH = 5000


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(text: str, limit: int = MAX_FETCH_TEXT_LENGTH) -> str:
    return text[:limit]


def clean_html_fragment(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    return clean_text(soup.get_text(" "))


def extract_visible_text_from_html(html: str) -> tuple[str, dict[str, int]]:
    soup = BeautifulSoup(html, "html.parser")
    script_count = len(soup.find_all("script"))
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = clean_text(soup.get_text(" "))
    return truncate_text(text), {"script_count": script_count, "text_length": len(text)}


def looks_like_requires_js(text: str, metrics: dict[str, int]) -> bool:
    return len(text) < 120 and metrics.get("script_count", 0) >= 3


def extract_job_posting_text(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", attrs={"type": lambda value: value and "ld+json" in value.lower()})

    for script in scripts:
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for candidate in _iter_json_nodes(payload):
            if not _is_job_posting(candidate):
                continue

            text = _build_job_posting_text(candidate)
            if text:
                return truncate_text(text)

    return None


def _iter_json_nodes(value: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(value, dict):
        nodes.append(value)
        if "@graph" in value and isinstance(value["@graph"], list):
            for item in value["@graph"]:
                nodes.extend(_iter_json_nodes(item))
    elif isinstance(value, list):
        for item in value:
            nodes.extend(_iter_json_nodes(item))
    return nodes


def _is_job_posting(node: dict[str, Any]) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, list):
        return any(item == "JobPosting" for item in node_type)
    return node_type == "JobPosting"


def _build_job_posting_text(node: dict[str, Any]) -> str:
    parts: list[str] = []

    title = _coerce_text(node.get("title"))
    hiring_org = _coerce_org(node.get("hiringOrganization"))
    employment_type = _coerce_text(node.get("employmentType"))
    description = _coerce_text(node.get("description"))
    qualifications = _coerce_text(node.get("qualifications"))
    responsibilities = _coerce_text(node.get("responsibilities"))
    skills = _coerce_text(node.get("skills"))
    experience = _coerce_text(node.get("experienceRequirements"))
    location = _coerce_location(node.get("jobLocation"))

    for value in (
        ("직무", title),
        ("회사", hiring_org),
        ("고용 형태", employment_type),
        ("근무지", location),
        ("설명", description),
        ("주요 업무", responsibilities),
        ("자격 요건", qualifications),
        ("필요 역량", skills),
        ("경력 요건", experience),
    ):
        if value[1]:
            parts.append(f"{value[0]}: {clean_html_fragment(value[1])}")

    return clean_text(" ".join(parts))


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        items = [item for item in (_coerce_text(item) for item in value) if item]
        return clean_text(" ".join(items)) or None
    if isinstance(value, dict):
        for key in ("name", "text", "value"):
            if key in value:
                return _coerce_text(value[key])
    return clean_text(str(value)) or None


def _coerce_org(value: Any) -> str | None:
    if isinstance(value, dict):
        return _coerce_text(value.get("name"))
    return _coerce_text(value)


def _coerce_location(value: Any) -> str | None:
    if isinstance(value, list):
        items = [item for item in (_coerce_location(item) for item in value) if item]
        return clean_text(" ".join(items)) or None

    if isinstance(value, dict):
        address = value.get("address")
        if isinstance(address, dict):
            parts = [
                _coerce_text(address.get("addressLocality")),
                _coerce_text(address.get("addressRegion")),
                _coerce_text(address.get("addressCountry")),
            ]
            compact = clean_text(" ".join(part for part in parts if part))
            return compact or None

    return _coerce_text(value)
