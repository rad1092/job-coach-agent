from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from backend.app.clients.fetch_models import FetchResult

FETCH_CACHE_TTL_SECONDS = 24 * 60 * 60


def normalize_cache_url(url: str) -> str:
    split = urlsplit(url.strip())
    if not split.scheme or not split.netloc:
        return url.strip()
    return urlunsplit((split.scheme.lower(), split.netloc.lower(), split.path, split.query, ""))


def load_fetch_cache(data_dir: Path, url: str, ttl_seconds: int = FETCH_CACHE_TTL_SECONDS) -> FetchResult | None:
    path = _cache_path(data_dir, url)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    cached_at = float(payload.get("cached_at", 0))
    if cached_at <= 0 or (time.time() - cached_at) > ttl_seconds:
        return None

    raw_result = FetchResult.from_payload(dict(payload.get("result", {})))
    metadata = dict(raw_result.metadata)
    metadata.setdefault("cached_method", raw_result.method)
    metadata.setdefault("cached_status", raw_result.status)
    metadata.setdefault("cache_key", payload.get("cache_key"))

    return FetchResult(
        url=raw_result.url,
        final_url=raw_result.final_url,
        method="cache_hit",
        status=raw_result.status,
        text=raw_result.text,
        metadata=metadata,
        error_reason=raw_result.error_reason,
        used_cache=True,
    )


def save_fetch_cache(data_dir: Path, url: str, result: FetchResult) -> Path:
    path = _cache_path(data_dir, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cache_key": path.stem,
        "cached_at": time.time(),
        "normalized_url": normalize_cache_url(url),
        "result": result.to_payload(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _cache_path(data_dir: Path, url: str) -> Path:
    cache_dir = data_dir / "fetch_cache"
    normalized = normalize_cache_url(url)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"
