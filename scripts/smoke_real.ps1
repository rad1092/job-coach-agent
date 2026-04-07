param(
    [string]$Industry = "IT",
    [string]$JobFamily = "개발",
    [string]$JobRole = "백엔드 개발자",
    [string]$ExperienceLevel = "주니어",
    [string]$Preferences = "데이터 처리와 API 설계 중심",
    [string]$UserBackground = "FastAPI와 데이터 처리 프로젝트 경험이 있습니다.",
    [string]$Notes = "API 설계와 협업 경험을 강조하고 싶습니다."
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

# 실제 `.env` 설정을 사용해 백엔드 핵심 흐름을 빠르게 확인한다.
# 백엔드 서버가 먼저 실행되어 있어야 한다.

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $root ".env"

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    $line = Get-Content -Encoding utf8 $Path | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
    if (-not $line) {
        return $null
    }

    return $line.Substring($Name.Length + 1).Trim()
}

$baseUrl = Get-EnvValue -Path $envPath -Name "BACKEND_BASE_URL"
if (-not $baseUrl) {
    $baseUrl = "http://127.0.0.1:8000"
}

Write-Host "백엔드 상태를 확인합니다: $baseUrl" -ForegroundColor Cyan
$health = Invoke-RestMethod -Method Get -Uri "$baseUrl/health"
Write-Host "상태 확인 완료: $($health.status)" -ForegroundColor Green

$explorePayload = @{
    industry = $Industry
    job_family = $JobFamily
    job_role = $JobRole
    experience_level = $ExperienceLevel
    preferences = $Preferences
    user_background = $UserBackground
} | ConvertTo-Json -Depth 8

Write-Host "기업·공고 후보를 탐색합니다..." -ForegroundColor Cyan
$explore = Invoke-RestMethod -Method Post -Uri "$baseUrl/explore" -ContentType "application/json; charset=utf-8" -Body $explorePayload

$companyCount = @($explore.company_candidates).Count
$postingCount = @($explore.posting_candidates).Count
Write-Host "탐색 완료: 관련 기업 정보 ${companyCount}개, 공고 후보 ${postingCount}개" -ForegroundColor Green

$selectedTarget = $null

if ($postingCount -gt 0) {
    $selectedTarget = @{
        name = $explore.posting_candidates[0].name
        kind = $explore.posting_candidates[0].kind
        summary = $explore.posting_candidates[0].summary
        source_url = $explore.posting_candidates[0].source_url
    }
} elseif ($companyCount -gt 0) {
    $selectedTarget = @{
        name = $explore.company_candidates[0].name
        kind = $explore.company_candidates[0].kind
        summary = $explore.company_candidates[0].summary
        source_url = $explore.company_candidates[0].source_url
    }
}

if (-not $selectedTarget) {
    throw "선택할 수 있는 지원 대상 후보가 없습니다."
}

Write-Host "선택한 지원 대상: $($selectedTarget.name) [$($selectedTarget.kind)]" -ForegroundColor Green

$preparePayload = @{
    run_id = $explore.run_id
    selected_target = $selectedTarget
    user_background = $UserBackground
    notes = $Notes
} | ConvertTo-Json -Depth 8

Write-Host "지원 준비 요약서를 생성합니다..." -ForegroundColor Cyan
$prepare = Invoke-RestMethod -Method Post -Uri "$baseUrl/prepare-summary" -ContentType "application/json; charset=utf-8" -Body $preparePayload
Write-Host "지원 준비 요약서 생성 완료" -ForegroundColor Green
Write-Host $prepare.preparation_summary

if (@($prepare.warnings).Count -gt 0) {
    Write-Host ""
    Write-Host "경고:" -ForegroundColor Yellow
    $prepare.warnings | ForEach-Object { Write-Host "- $_" }
}

Write-Host ""
Write-Host "준비 포인트:" -ForegroundColor Yellow
$prepare.preparation_points | ForEach-Object { Write-Host "- $_" }

Write-Host ""
Write-Host "부족 역량과 보완 포인트:" -ForegroundColor Yellow
$prepare.skill_gaps | ForEach-Object { Write-Host "- $_" }

$artifactPayload = @{
    run_id = $prepare.run_id
    selected_target = $selectedTarget
    preparation_summary = $prepare.preparation_summary
    user_background = $UserBackground
    notes = $Notes
} | ConvertTo-Json -Depth 8

Write-Host "실행 항목과 면접 자료를 생성합니다..." -ForegroundColor Cyan
$artifacts = Invoke-RestMethod -Method Post -Uri "$baseUrl/prep-artifacts" -ContentType "application/json; charset=utf-8" -Body $artifactPayload
Write-Host "산출물 생성 완료" -ForegroundColor Green

if (@($artifacts.warnings).Count -gt 0) {
    Write-Host ""
    Write-Host "경고:" -ForegroundColor Yellow
    $artifacts.warnings | ForEach-Object { Write-Host "- $_" }
}

Write-Host ""
Write-Host "실행 항목:" -ForegroundColor Yellow
$artifacts.action_items | ForEach-Object { Write-Host "- $_" }

Write-Host ""
Write-Host "예상 면접 질문:" -ForegroundColor Yellow
$artifacts.interview_questions | ForEach-Object { Write-Host "- $_" }

Write-Host ""
Write-Host "답변 구조:" -ForegroundColor Yellow
$artifacts.answer_frames | ForEach-Object { Write-Host "- $_" }
