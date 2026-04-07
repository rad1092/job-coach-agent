# Encoding Policy

이 문서는 인코딩 관련 빠른 확인용 메모다.
전체 작성 규칙과 한글 가독성 기준은 `.agents/contracts/project-policy.md`를 따른다.

## Required

- `SKILL.md`: UTF-8 without BOM
- `*.yaml`: UTF-8 without BOM
- `*.md`: UTF-8 without BOM
- `*.py`: UTF-8 without BOM
- `*.ps1`: UTF-8 with BOM

## Why

The skill loader expects `SKILL.md` to start with raw `---` YAML frontmatter.
If a BOM is added before `---`, the loader can reject the skill as invalid.

## Quick Check

- `SKILL.md` must start with `---` on the very first byte
- No `Skipped loading ... invalid SKILL.md` warnings should appear
- In Windows PowerShell, prefer `Get-Content -Encoding utf8`
- A smoke-test subagent using one of the local skills should run without skill-loading errors
