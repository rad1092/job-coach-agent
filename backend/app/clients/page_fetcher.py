from __future__ import annotations

from backend.app.clients.fetch_browser import fetch_browser_content, is_playwright_available
from backend.app.clients.fetch_cache import save_fetch_cache, load_fetch_cache
from backend.app.clients.fetch_extractors import clean_text, truncate_text
from backend.app.clients.fetch_models import FetchResult
from backend.app.clients.fetch_policies import get_fetch_policy
from backend.app.clients.fetch_static import fetch_static_content
from backend.app.core.settings import Settings


def _build_raw_content_result(url: str, raw_content: str) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        method="raw_content",
        status="success",
        text=truncate_text(clean_text(raw_content)),
        metadata={"source": "search_raw_content"},
    )


def _build_summary_only_result(url: str, policy_name: str, strategy: str) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        method="summary_only_policy",
        status="summary_only",
        text="",
        metadata={"policy_name": policy_name, "strategy": strategy},
        error_reason="summary_only_policy",
    )


def _should_cache_result(result: FetchResult) -> bool:
    return result.status != "error"


async def fetch_page_content(
    settings: Settings,
    url: str,
    raw_content: str | None = None,
    timeout_seconds: float = 10.0,
) -> FetchResult:
    if raw_content and clean_text(raw_content):
        return _build_raw_content_result(url, raw_content)

    cached_result = load_fetch_cache(settings.data_dir, url)
    if cached_result is not None:
        return cached_result

    policy = get_fetch_policy(url)
    if policy.strategy == "summary_only":
        result = _build_summary_only_result(url, policy.name, policy.strategy)
    elif policy.strategy == "browser_only":
        result = await fetch_browser_content(url, timeout_seconds=max(timeout_seconds, 15.0))
    elif policy.strategy == "browser_allowed" and is_playwright_available():
        result = await fetch_browser_content(url, timeout_seconds=max(timeout_seconds, 15.0))
    else:
        result = await fetch_static_content(url, timeout_seconds=timeout_seconds)

    result.metadata.setdefault("policy_name", policy.name)
    result.metadata.setdefault("strategy", policy.strategy)
    if _should_cache_result(result):
        save_fetch_cache(settings.data_dir, url, result)
    return result
