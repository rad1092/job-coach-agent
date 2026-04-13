from __future__ import annotations

from backend.app.services.preparation import _coerce_gap_list


def test_coerce_gap_list_formats_english_keys_into_korean_sections() -> None:
    formatted = _coerce_gap_list(
        [
            {
                "weakness": "소프트웨어 구현 깊이가 아직 얕아 보입니다.",
                "compensation": "작은 프로젝트를 완성해 깃허브와 문서로 정리하세요.",
            }
        ],
        limit=3,
    )

    assert formatted == [
        "보완 포인트: 소프트웨어 구현 깊이가 아직 얕아 보입니다.\n보완 방법: 작은 프로젝트를 완성해 깃허브와 문서로 정리하세요."
    ]
