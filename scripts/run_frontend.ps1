$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

# Streamlit 프론트를 로컬에서 실행한다.
# 백엔드는 별도 터미널에서 먼저 실행되어 있어야 한다.

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "가상환경 파이썬을 찾지 못했습니다. 먼저 uv sync를 실행해 주세요."
}

Set-Location $root
Write-Host "프론트를 실행합니다. 기본 주소: http://localhost:8501" -ForegroundColor Cyan
& $python -m streamlit run frontend/app.py
