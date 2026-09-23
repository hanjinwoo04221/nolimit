@echo off
chcp 65001 > nul
title ContextForge - Infinite Context Local AI Assistant

echo ======================================================================
echo  🧠 ContextForge - 무한 컨텍스트 로컬 AI 어시스턴트 실행기
echo ======================================================================

if exist ".venv\Scripts\python.exe" (
    echo [1/2] 가상환경(.venv) 파이썬으로 구동합니다...
    ".venv\Scripts\python.exe" main.py
) else (
    echo [1/2] 시스템 파이썬으로 가상환경 생성 및 구동 시도...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
    ".venv\Scripts\python.exe" main.py
)

pause
