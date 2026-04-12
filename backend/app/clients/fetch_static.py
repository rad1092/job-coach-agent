from __future__ import annotations

import httpx

from backend.app.clients.fetch_extractors import extract_job_posting_text, extract_visible_text_from_html, looks_like_requires_js
from backend.app.clients.fetch_models import FetchResult

DEFAULT_FETCH_HEADERS = {
    "User-Agent": "job-coach-runtime/0.2",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


async def fetch_static_content(url: str, timeout_seconds: float = 10.0) -> FetchResult:
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers=DEFAULT_FETCH_HEADERS,
        ) as client:
            response = await client.get(url)
    except httpx.RequestError as exc:
        return FetchResult(
            url=url,
            final_url=url,
            method="static_html",
            status="error",
            text="",
            metadata={"transport_error": exc.__class__.__name__},
            error_reason=str(exc),
        )

    final_url = str(response.url)
    metadata = {
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
    }

    if response.status_code in {401, 403, 429, 451}:
        return FetchResult(
            url=url,
            final_url=final_url,
            method="static_html",
            status="blocked",
            text="",
            metadata=metadata,
            error_reason=f"http_{response.status_code}",
        )

    if response.status_code >= 400:
        return FetchResult(
            url=url,
            final_url=final_url,
            method="static_html",
            status="error",
            text="",
            metadata=metadata,
            error_reason=f"http_{response.status_code}",
        )

    html = response.text
    json_ld_text = extract_job_posting_text(html)
    if json_ld_text:
        return FetchResult(
            url=url,
            final_url=final_url,
            method="json_ld",
            status="success",
            text=json_ld_text,
            metadata=metadata,
        )

    visible_text, extractor_metrics = extract_visible_text_from_html(html)
    metadata.update(extractor_metrics)
    if visible_text:
        return FetchResult(
            url=url,
            final_url=final_url,
            method="static_html",
            status="success",
            text=visible_text,
            metadata=metadata,
        )

    status = "requires_js" if looks_like_requires_js(visible_text, extractor_metrics) else "empty_body"
    return FetchResult(
        url=url,
        final_url=final_url,
        method="static_html",
        status=status,
        text="",
        metadata=metadata,
        error_reason=status,
    )
