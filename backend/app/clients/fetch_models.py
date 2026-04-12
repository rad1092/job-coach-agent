from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FetchStatus = Literal["success", "summary_only", "blocked", "requires_js", "empty_body", "error"]
FetchMethod = Literal["raw_content", "static_html", "json_ld", "browser_render", "cache_hit", "summary_only_policy"]

_SUCCESS_CONFIDENCE = {
    "raw_content": 0.95,
    "json_ld": 0.92,
    "browser_render": 0.88,
    "static_html": 0.82,
}


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    method: FetchMethod
    status: FetchStatus
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error_reason: str | None = None
    used_cache: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "method": self.method,
            "status": self.status,
            "text": self.text,
            "metadata": self.metadata,
            "error_reason": self.error_reason,
            "used_cache": self.used_cache,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FetchResult":
        return cls(
            url=str(payload.get("url", "")),
            final_url=str(payload.get("final_url") or payload.get("url") or ""),
            method=payload.get("method", "static_html"),
            status=payload.get("status", "error"),
            text=str(payload.get("text", "")),
            metadata=dict(payload.get("metadata", {})),
            error_reason=payload.get("error_reason"),
            used_cache=bool(payload.get("used_cache", False)),
        )


def effective_fetch_method(result: FetchResult) -> FetchMethod:
    if result.method != "cache_hit":
        return result.method

    cached_method = result.metadata.get("cached_method")
    if cached_method in _SUCCESS_CONFIDENCE or cached_method == "summary_only_policy":
        return cached_method
    return "static_html"


def confidence_for_fetch_result(result: FetchResult) -> float:
    method = effective_fetch_method(result)
    if result.status == "success":
        return _SUCCESS_CONFIDENCE.get(method, 0.82)
    if method == "summary_only_policy" or result.status == "summary_only":
        return 0.55
    return 0.60


def note_for_fetch_result(result: FetchResult) -> str | None:
    if result.status == "success":
        return None

    if effective_fetch_method(result) == "summary_only_policy" or result.status == "summary_only":
        return f"사이트 정책상 검색 요약만 사용한 URL: {result.url}"
    if result.status == "requires_js":
        return f"동적 페이지로 본문 수집에 실패해 검색 요약만 사용한 URL: {result.url}"
    return f"검색 요약만 사용한 URL: {result.url}"
