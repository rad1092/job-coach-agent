from __future__ import annotations

from frontend import app


def test_download_report_markdown_sanitizes_markdown_breakers() -> None:
    app.st.session_state.clear()
    app._init_state()
    app.st.session_state.input_payload = {
        "industry": "IT·플랫폼",
        "job_family": "개발",
        "job_role": "백엔드 개발자",
        "experience_level": "무관",
        "experience_years": "미정",
        "preferences": "AI 활용, 수도권 지방 무관",
        "user_background": "데이터 수집과 정제, 적재 자동화 경험이 있습니다.",
        "notes": "자동화 강점을 강조하고 싶습니다.",
    }

    selected_target = {
        "name": "[그렙(프로그래머스)] [프로그래머스] 백엔드 개발자(공통플랫폼팀) 채용 공고 | 원티드",
        "kind": "posting",
        "summary": (
            "![thumb](https://image.wanted.co.kr/optimize?src=x) "
            "공통 플랫폼에서 여러 서비스가 함께 쓰는 기능을 개발합니다."
        ),
        "source_url": "https://www.wanted.co.kr/wd/246051",
    }
    prepare_summary = {
        "preparation_summary": "첫 문단입니다.\n\n둘째 문단입니다.",
        "preparation_points": ["핵심 메시지: 공통 기능 개발 경험과 연결합니다."],
        "skill_gaps": ["보완 포인트: 대규모 서비스 경험이 직접적이지 않습니다. | 보완 방법: 운영 관점 학습 계획을 제시합니다."],
    }
    artifacts = {
        "action_items": ["공고 핵심 키워드 3개를 정리합니다."],
        "interview_questions": ["왜 이 직무에 지원했나요?"],
        "answer_frames": ["핵심 메시지: 지원 이유를 먼저 말합니다. | 직무 연결: 빠르게 기여할 포인트를 덧붙입니다."],
        "self_intro_draft": "자기소개 초안입니다.",
    }

    result = app._build_download_report_markdown(selected_target, prepare_summary, artifacts)

    assert "| 항목 | 내용 |" not in result
    assert "![thumb]" not in result
    assert "https://image.wanted.co.kr/optimize" not in result
    assert "\n        ##" not in result
    assert "## 문서 한눈에 보기" in result
    assert "- **지원 대상**:" in result
    assert "- **공고명**:" in result
    assert "[공고 바로가기](https://www.wanted.co.kr/wd/246051)" in result
