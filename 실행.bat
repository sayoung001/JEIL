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
if not exist config.yaml copy config.example.yaml config.yaml
python main.py
pause
