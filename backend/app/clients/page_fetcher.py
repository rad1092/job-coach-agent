from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


async def fetch_page_text(url: str, timeout_seconds: float = 10.0) -> str:
    headers = {"User-Agent": "job-coach-runtime/0.1"}
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = clean_text(soup.get_text(" "))
    return text[:5000]

