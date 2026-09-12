@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist .venv (
    py -3.11 -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
)
REM config.yaml 은 없으면 프로그램이 알아서 만든다
python main.py
pause
