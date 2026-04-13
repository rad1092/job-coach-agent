from __future__ import annotations

from urllib.parse import urlparse

CUSTOM_OPTION = "직접 입력"

INDUSTRY_FAMILY_MAP: dict[str, tuple[str, ...]] = {
    "IT·플랫폼": ("개발", "데이터·AI", "제품", "디자인", "마케팅·그로스", "영업·사업개발", "경영지원"),
    "AI·데이터": ("개발", "데이터·AI", "제품", "디자인", "마케팅·그로스"),
    "이커머스·리테일": ("개발", "데이터·AI", "제품", "디자인", "마케팅·그로스", "영업·사업개발", "경영지원"),
    "핀테크·금융": ("개발", "데이터·AI", "제품", "디자인", "마케팅·그로스", "경영지원"),
    "게임": ("개발", "데이터·AI", "제품", "디자인", "마케팅·그로스"),
    "SaaS·B2B 솔루션": ("개발", "데이터·AI", "제품", "디자인", "마케팅·그로스", "영업·사업개발", "경영지원"),
    "콘텐츠·미디어": ("개발", "데이터·AI", "제품", "디자인", "마케팅·그로스", "영업·사업개발"),
    "제조·모빌리티": ("개발", "데이터·AI", "제품", "디자인", "영업·사업개발", "경영지원"),
    "바이오·헬스케어": ("개발", "데이터·AI", "제품", "디자인", "영업·사업개발", "경영지원"),
    "공공·교육": ("개발", "데이터·AI", "제품", "디자인", "마케팅·그로스", "경영지원"),
}

JOB_ROLE_MAP: dict[str, tuple[str, ...]] = {
    "개발": (
        "백엔드 개발자",
        "프론트엔드 개발자",
        "풀스택 개발자",
        "모바일 앱 개발자",
        "데브옵스 엔지니어",
        "QA 엔지니어",
        "보안 엔지니어",
    ),
    "데이터·AI": (
        "데이터 분석가",
        "데이터 사이언티스트",
        "데이터 엔지니어",
        "머신러닝 엔지니어",
        "AI 애플리케이션 엔지니어",
        "BI 분석가",
    ),
    "제품": (
        "프로덕트 매니저",
        "서비스 기획자",
        "프로젝트 매니저",
        "프로덕트 오퍼레이션",
    ),
    "디자인": (
        "프로덕트 디자이너",
        "UX 디자이너",
        "UI 디자이너",
        "브랜드 디자이너",
        "콘텐츠 디자이너",
    ),
    "마케팅·그로스": (
        "퍼포먼스 마케터",
        "CRM 마케터",
        "콘텐츠 마케터",
        "브랜드 마케터",
        "그로스 마케터",
    ),
    "영업·사업개발": (
        "B2B 영업",
        "어카운트 매니저",
        "사업개발 매니저",
        "파트너십 매니저",
        "고객 성공 매니저",
    ),
    "경영지원": (
        "인사",
        "채용 담당자",
        "재무·회계",
        "전략기획",
        "운영 매니저",
    ),
}

EXPERIENCE_LEVEL_OPTIONS: tuple[str, ...] = (
    "무관",
    "인턴",
    "신입",
    "연차",
)

PREFERENCE_OPTIONS: tuple[str, ...] = (
    "원격·하이브리드",
    "유연근무",
    "데이터 중심 문화",
    "AI 활용",
    "B2B 서비스",
    "B2C 서비스",
    "플랫폼 비즈니스",
    "스타트업",
    "중견·대기업",
    "글로벌 서비스",
    "공공·안정성",
    "빠른 실행 환경",
)

JOB_BOARD_LABELS: dict[str, str] = {
    "jobkorea.co.kr": "잡코리아",
    "saramin.co.kr": "사람인",
    "wanted.co.kr": "원티드",
    "work24.go.kr": "고용24",
    "jasoseol.com": "자소설닷컴",
    "jumpit.saramin.co.kr": "점핏",
    "jobplanet.co.kr": "잡플래닛",
    "catch.co.kr": "캐치",
}

CORE_JOB_BOARD_DOMAINS: tuple[str, ...] = (
    "jobkorea.co.kr",
    "saramin.co.kr",
    "wanted.co.kr",
    "work24.go.kr",
)

EXTENDED_JOB_BOARD_DOMAINS: tuple[str, ...] = (
    "jasoseol.com",
    "jumpit.saramin.co.kr",
    "jobplanet.co.kr",
    "catch.co.kr",
)

DIRECT_POSTING_PATTERNS: dict[str, tuple[str, ...]] = {
    "jobkorea.co.kr": ("/Recruit/GI_Read/",),
    "saramin.co.kr": ("/zf_user/jobs/relay/view", "/job-search/view"),
    "wanted.co.kr": ("/wd/",),
    "work24.go.kr": ("retriveDtlEmpSrchList.do",),
    "jasoseol.com": ("/recruit/",),
    "jumpit.saramin.co.kr": ("/position/",),
    "jobplanet.co.kr": ("/job/",),
    "catch.co.kr": ("/NCS/RecruitInfoDetails", "/RecruitInfoDetails", "/Recruit"),
}

EXCLUDED_SEARCH_DOMAINS: tuple[str, ...] = (
    "linkedin.com",
    "theorg.com",
    "zoominfo.com",
    "pitchbook.com",
    "marketscreener.com",
    "rocketreach.co",
)

BLOCKED_URL_KEYWORDS: tuple[str, ...] = (
    "/about",
    "/company",
    "/team",
    "/leadership",
    "/board",
    "/executive",
    "/investor",
    "/ir",
    "/news",
    "/review",
    "/salary",
    "/community",
    "/blog",
    "/press",
    "/search",
    "/list",
)

BLOCKED_TEXT_KEYWORDS: tuple[str, ...] = (
    "임원",
    "이사진",
    "대표이사",
    "leadership",
    "board of directors",
    "investor relations",
    "기업리뷰",
    "연봉",
    "뉴스룸",
)


def _domain_matches(domain: str, candidate: str) -> bool:
    return domain == candidate or domain.endswith(f".{candidate}")


def industry_options() -> list[str]:
    return list(INDUSTRY_FAMILY_MAP)


def job_families_for_industry(industry: str | None) -> list[str]:
    if industry and industry in INDUSTRY_FAMILY_MAP:
        return list(INDUSTRY_FAMILY_MAP[industry])
    merged: list[str] = []
    seen: set[str] = set()
    for families in INDUSTRY_FAMILY_MAP.values():
        for family in families:
            if family not in seen:
                seen.add(family)
                merged.append(family)
    return merged


def job_roles_for_family(job_family: str | None) -> list[str]:
    if job_family and job_family in JOB_ROLE_MAP:
        return list(JOB_ROLE_MAP[job_family])
    merged: list[str] = []
    seen: set[str] = set()
    for roles in JOB_ROLE_MAP.values():
        for role in roles:
            if role not in seen:
                seen.add(role)
                merged.append(role)
    return merged


def job_board_domains_for_retry(retry_count: int) -> list[str]:
    domains = list(CORE_JOB_BOARD_DOMAINS)
    if retry_count > 0:
        domains.extend(EXTENDED_JOB_BOARD_DOMAINS)
    return domains


def job_board_label_for_url(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    for candidate, label in sorted(JOB_BOARD_LABELS.items(), key=lambda item: len(item[0]), reverse=True):
        if _domain_matches(domain, candidate):
            return label
    return "채용 사이트"


def is_direct_posting_url(url: str) -> bool:
    lowered_url = url.lower()
    domain = urlparse(url).netloc.lower()
    for candidate, patterns in sorted(DIRECT_POSTING_PATTERNS.items(), key=lambda item: len(item[0]), reverse=True):
        if _domain_matches(domain, candidate):
            return any(pattern.lower() in lowered_url for pattern in patterns)
    return False
