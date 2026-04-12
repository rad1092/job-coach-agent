from __future__ import annotations

from typing import Final


UNDECIDED_JOB_ROLE: Final[str] = "미정"
CUSTOM_JOB_ROLE: Final[str] = "직접 입력"

INDUSTRIES: Final[tuple[str, ...]] = (
    "IT/소프트웨어",
    "금융",
    "이커머스/리테일",
    "플랫폼/서비스",
    "콘텐츠/미디어",
    "헬스케어/바이오",
    "제조/하드웨어",
    "교육",
    "모빌리티/물류",
    "공공/비영리",
    "기타",
)

JOB_FAMILY_ROLES: Final[dict[str, tuple[str, ...]]] = {
    "개발": ("백엔드", "프론트엔드", "풀스택", "모바일", "DevOps/SRE", "QA/테스트", "보안", "임베디드/시스템", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "데이터/AI": ("데이터 분석", "데이터 엔지니어", "데이터 사이언티스트", "ML 엔지니어", "BI/리서치", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "제품/기획": ("PM", "서비스 기획", "사업기획", "운영기획", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "디자인": ("UX/UI", "Product Designer", "BX/브랜드", "콘텐츠 디자인", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "마케팅": ("퍼포먼스", "콘텐츠", "CRM", "브랜딩", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "영업/사업개발": ("B2B 영업", "AE/AM", "사업개발", "파트너십", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "운영/프로젝트관리": ("운영", "PMO", "프로젝트 매니저", "오퍼레이션", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "HR/리크루팅": ("채용", "HRBP", "인사운영", "교육/조직문화", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "재무/회계": ("회계", "재무", "FP&A", "세무", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
    "고객지원/CS": ("CX", "CS", "고객성공", "기술지원", UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE),
}

JOB_FAMILIES: Final[tuple[str, ...]] = tuple(JOB_FAMILY_ROLES.keys())
EXPERIENCE_LEVELS: Final[tuple[str, ...]] = ("신입", "경력무관", "경력")

PREFERENCE_OPTIONS: Final[dict[str, tuple[str, ...]]] = {
    "근무형태": ("원격", "하이브리드", "상주"),
    "고용형태": ("정규직", "계약직", "인턴"),
    "지역": ("수도권", "비수도권", "해외"),
    "기업규모": ("스타트업", "성장기업", "중견·대기업"),
}

PREFERENCE_CATEGORIES: Final[tuple[str, ...]] = tuple(PREFERENCE_OPTIONS.keys())
PREFERENCE_TAGS: Final[tuple[str, ...]] = tuple(
    f"{category}: {option}"
    for category in PREFERENCE_CATEGORIES
    for option in PREFERENCE_OPTIONS[category]
)

_ALL_KNOWN_JOB_ROLES: Final[frozenset[str]] = frozenset(
    role
    for roles in JOB_FAMILY_ROLES.values()
    for role in roles
)


def compact_text(value: object | None) -> str | None:
    if value is None:
        return None
    compact = " ".join(str(value).split())
    return compact or None


def is_valid_industry(value: str) -> bool:
    return value in INDUSTRIES


def is_valid_job_family(value: str) -> bool:
    return value in JOB_FAMILIES


def job_roles_for_family(job_family: str) -> tuple[str, ...]:
    return JOB_FAMILY_ROLES.get(job_family, ())


def normalize_job_role(value: str | None) -> str | None:
    compact = compact_text(value)
    if compact in {None, UNDECIDED_JOB_ROLE}:
        return None
    return compact


def validate_job_role(job_family: str, job_role: str | None) -> bool:
    role = normalize_job_role(job_role)
    if role is None:
        return True

    allowed_roles = job_roles_for_family(job_family)
    if not allowed_roles:
        return False

    selectable_roles = {
        item
        for item in allowed_roles
        if item not in {UNDECIDED_JOB_ROLE, CUSTOM_JOB_ROLE}
    }
    if role in selectable_roles:
        return True

    if role in _ALL_KNOWN_JOB_ROLES:
        return False

    return True


def build_preferences_text(tags: list[str], extra_note: str | None = None) -> str | None:
    ordered_tags = [tag for tag in PREFERENCE_TAGS if tag in tags]
    note = compact_text(extra_note)

    parts = [*ordered_tags]
    if note:
        parts.append(f"기타: {note}")

    if not parts:
        return None
    return " / ".join(parts)
