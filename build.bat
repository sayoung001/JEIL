@echo off
chcp 65001 > nul
REM 품질 업무 자동화 — exe 빌드 (SPEC §9 S10)
cd /d "%~dp0"

if not exist .venv (
    py -3.11 -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt

pyinstaller --onefile --windowed ^
    --name 품질자동화 ^
    --add-data "workflows;workflows" ^
    --add-data "templates;templates" ^
    --add-data "config.example.yaml;." ^
    main.py

echo.
echo 빌드 완료: dist\품질자동화.exe
echo config.yaml 을 exe 옆에 두고 실행하세요.
pause
