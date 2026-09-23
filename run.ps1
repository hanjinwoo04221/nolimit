# ContextForge PowerShell Launcher
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " 🧠 ContextForge - 무한 컨텍스트 로컬 AI 어시스턴트 실행기 (PowerShell)" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

if (-not (Test-Path ".venv")) {
    Write-Host "[1/3] 가상환경을 생성하는 중입니다 (.venv)..." -ForegroundColor Yellow
    uv venv .venv
}

Write-Host "[2/3] 가상환경 활성화 및 종속성 설치..." -ForegroundColor Yellow
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet

Write-Host "[3/3] ContextForge 서버 및 웹 대시보드 시작 (http://localhost:8765)..." -ForegroundColor Green
& ".\.venv\Scripts\python.exe" main.py
