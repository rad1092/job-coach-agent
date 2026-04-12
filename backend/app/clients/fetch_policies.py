from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

FetchStrategy = Literal["static_first", "summary_only", "browser_only", "browser_allowed"]


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    name: str
    strategy: FetchStrategy
    domains: tuple[str, ...]


DEFAULT_FETCH_POLICY = FetchPolicy(
    name="default_static",
    strategy="static_first",
    domains=(),
)

FETCH_POLICIES: tuple[FetchPolicy, ...] = (
    FetchPolicy(
        name="summary_only_indeed",
        strategy="summary_only",
        domains=("indeed.com", "indeed.co.kr"),
    ),
    FetchPolicy(
        name="browser_only_workday",
        strategy="browser_only",
        domains=("myworkdayjobs.com",),
    ),
    FetchPolicy(
        name="browser_allowed_ats",
        strategy="browser_allowed",
        domains=("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com"),
    ),
)


def _matches_domain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def get_fetch_policy(url: str) -> FetchPolicy:
    hostname = (urlparse(url).hostname or "").lower()
    if not hostname:
        return DEFAULT_FETCH_POLICY

    for policy in FETCH_POLICIES:
        if any(_matches_domain(hostname, domain) for domain in policy.domains):
            return policy
    return DEFAULT_FETCH_POLICY
