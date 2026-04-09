# 취업 코치형 에이전트

희망 산업·직군·직무를 입력하면 관련 공고와 공개 정보를 탐색하고, 지원 준비 요약서와 실행 항목, 면접 자료를 한 흐름으로 정리하는 로컬 데모 프로젝트입니다.

## 요구 사항

- Python 3.12
- `uv`
- OpenAI API 키
- Tavily API 키

## 설치

의존성을 먼저 설치합니다.

```powershell
uv sync
```

루트에 `.env` 파일을 만들고 값을 채웁니다. 예시는 [`.env.example`](./.env.example)에 있습니다.

```env
OPENAI_API_KEY=...
TAVILY_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
SEARCH_PROVIDER=tavily
LLM_PROVIDER=openai
BACKEND_BASE_URL=http://127.0.0.1:8000
```

## 실행

백엔드를 먼저 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_backend.ps1
```

다른 터미널에서 프론트를 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_frontend.ps1
```

브라우저에서 아래 주소로 접속합니다.

```text
http://localhost:8501
```

## 스모크 테스트

백엔드가 실행 중인 상태에서 핵심 흐름을 한 번에 확인할 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_real.ps1
```

직무를 바꿔서 확인하려면 인자를 넘깁니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_real.ps1 -Industry "마케팅" -JobFamily "콘텐츠" -JobRole "콘텐츠 마케터"
```

## 현재 기능 범위

- 산업·직군·직무 입력
- 지원 대상 후보 탐색
- 공고 우선 단일 선택
- 지원 준비 요약서 생성
- 실행 항목 생성
- 예상 면접 질문과 답변 구조 생성

## 주의 사항

- `.env`는 저장소에 올리지 않습니다.
- 공개 웹 정보를 바탕으로 보강하지만, 실시간 완전 최신성을 보장하지 않습니다.
- 메모/DB 레이어와 장기 세션 기억은 아직 `MVP+` 범위입니다 - 완성보장이 어렵습니다

## 저장소 구성 참고

- 앱 실행 코드는 `backend`, `frontend`, `scripts`에 있습니다.
- 내부 진행 기록과 작성 기준은 `.agents/contracts`의 공개 문서만 남겼습니다.
