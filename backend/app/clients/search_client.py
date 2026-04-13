from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from tavily import TavilyClient

from backend.app.core.settings import Settings


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    content: str | None = None


class SearchConfigurationError(RuntimeError):
    pass


class FixtureSearchClient:
    def __init__(self, data_dir: Path) -> None:
        self._fixture_path = data_dir / "fixtures" / "sample_search_results.json"

    def search(
        self,
        query: str,
        max_results: int = 5,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        country: str | None = None,
    ) -> list[SearchHit]:
        del country
        raw_items = json.loads(self._fixture_path.read_text(encoding="utf-8"))
        lowered = query.lower()
        ranked: list[tuple[int, dict[str, object]]] = []

        for item in raw_items:
            haystack = " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("snippet", "")),
                    " ".join(item.get("tags", [])),
                ]
            ).lower()
            score = sum(1 for token in lowered.split() if token in haystack)
            ranked.append((score, item))

        ranked.sort(
            key=lambda pair: (
                -pair[0],
                hashlib.md5(f"{query}:{pair[1].get('url', '')}".encode("utf-8")).hexdigest(),
            )
        )
        hits = [
            SearchHit(
                title=str(item["title"]),
                url=str(item["url"]),
                snippet=str(item["snippet"]),
                content=str(item.get("content", "")) or None,
            )
            for _, item in ranked
        ]

        filtered: list[SearchHit] = []
        for hit in hits:
            domain = urlparse(hit.url).netloc.lower()
            if include_domains and not any(domain == candidate or domain.endswith(f".{candidate}") for candidate in include_domains):
                continue
            if exclude_domains and any(domain == candidate or domain.endswith(f".{candidate}") for candidate in exclude_domains):
                continue
            filtered.append(hit)

        return filtered[:max_results]


class TavilySearchAdapter:
    def __init__(self, api_key: str) -> None:
        self._client = TavilyClient(api_key=api_key)

    def search(
        self,
        query: str,
        max_results: int = 5,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        country: str | None = None,
    ) -> list[SearchHit]:
        search_kwargs: dict[str, object] = {
            "query": query,
            "max_results": max_results,
            "include_raw_content": "text",
            "search_depth": "basic",
        }
        if include_domains:
            search_kwargs["include_domains"] = include_domains
        if exclude_domains:
            search_kwargs["exclude_domains"] = exclude_domains
        if country:
            search_kwargs["country"] = country

        response = self._client.search(**search_kwargs)
        return [
            SearchHit(
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("content", "")[:300],
                content=result.get("raw_content"),
            )
            for result in response.get("results", [])
        ]


def build_search_client(settings: Settings) -> FixtureSearchClient | TavilySearchAdapter:
    if settings.search_provider == "fixture":
        return FixtureSearchClient(settings.data_dir)
    if not settings.tavily_api_key:
        raise SearchConfigurationError("TAVILY_API_KEY is required when SEARCH_PROVIDER=tavily.")
    return TavilySearchAdapter(settings.tavily_api_key)

