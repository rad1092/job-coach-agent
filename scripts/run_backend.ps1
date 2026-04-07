$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

# 백엔드 FastAPI 서버를 로컬에서 실행한다.
# `.env`는 애플리케이션이 직접 읽으므로 스크립트에서는 별도 처리하지 않는다.

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "가상환경 파이썬을 찾지 못했습니다. 먼저 uv sync를 실행해 주세요."
}

Set-Location $root
Write-Host "백엔드를 실행합니다. 주소: http://127.0.0.1:8000" -ForegroundColor Cyan
& $python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
