@echo off
chcp 65001 > nul
REM exe 를 다른 PC 로 옮긴 뒤 경로가 안 맞을 때 제일 먼저 돌려 볼 것.
cd /d "%~dp0"
if exist 품질자동화.exe (
    품질자동화.exe --paths
) else (
    if exist .venv call .venv\Scripts\activate
    python main.py --paths
)
echo.
pause
