@echo off
chcp 65001 > nul
title ContextForge - Infinite Context Local AI Assistant

echo ======================================================================
echo  🧠 ContextForge - 무한 컨텍스트 로컬 AI 어시스턴트 실행기
echo ======================================================================

if not exist ".venv" (
    echo [1/3] 가상환경을 생성하는 중입니다 (.venv)...
    python -m venv .venv
    if errorlevel 1 (
        echo [!] uv를 통한 가상환경 생성 시도...
        uv venv .venv
    )
)

echo [2/3] 가상환경 활성화 및 패키지 확인...
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt --quiet

echo [3/3] ContextForge 서버 및 웹 대시보드 구동...
python main.py

pause
