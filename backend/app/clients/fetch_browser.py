from __future__ import annotations

from typing import Any

from backend.app.clients.fetch_extractors import extract_job_posting_text, extract_visible_text_from_html
from backend.app.clients.fetch_models import FetchResult


def is_playwright_available() -> bool:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


async def fetch_browser_content(url: str, timeout_seconds: float = 15.0) -> FetchResult:
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ModuleNotFoundError:
        return FetchResult(
            url=url,
            final_url=url,
            method="browser_render",
            status="error",
            text="",
            metadata={"transport_error": "playwright_not_installed"},
            error_reason="playwright_not_installed",
        )

    browser = None
    page = None
    response: Any = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                locale="ko-KR",
                user_agent="job-coach-runtime/0.2",
            )
            page = await context.new_page()
            response = await page.goto(url, wait_until="networkidle", timeout=int(timeout_seconds * 1000))
            html = await page.content()
            final_url = page.url

            metadata = {
                "status_code": response.status if response is not None else None,
                "content_type": response.headers.get("content-type", "") if response is not None else "",
            }
            if response is not None and response.status in {401, 403, 429, 451}:
                return FetchResult(
                    url=url,
                    final_url=final_url,
                    method="browser_render",
                    status="blocked",
                    text="",
                    metadata=metadata,
                    error_reason=f"http_{response.status}",
                )

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
                    method="browser_render",
                    status="success",
                    text=visible_text,
                    metadata=metadata,
                )

            return FetchResult(
                url=url,
                final_url=final_url,
                method="browser_render",
                status="empty_body",
                text="",
                metadata=metadata,
                error_reason="empty_body",
            )
    except PlaywrightTimeoutError:
        return FetchResult(
            url=url,
            final_url=page.url if page is not None else url,
            method="browser_render",
            status="error",
            text="",
            metadata={"transport_error": "timeout"},
            error_reason="browser_timeout",
        )
    except Exception as exc:
        return FetchResult(
            url=url,
            final_url=page.url if page is not None else url,
            method="browser_render",
            status="error",
            text="",
            metadata={"transport_error": exc.__class__.__name__},
            error_reason=str(exc),
        )
    finally:
        if browser is not None:
            await browser.close()
