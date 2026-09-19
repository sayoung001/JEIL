@echo off
chcp 65001 > nul
REM 문제가 생겼을 때 제일 먼저 돌려 볼 것. 결과를 그대로 알려 주면 된다.
cd /d "%~dp0"
if exist 품질자동화.exe (
    품질자동화.exe --selftest
    echo.
    품질자동화.exe --paths
) else (
    if exist .venv call .venv\Scripts\activate
    python main.py --selftest
    echo.
    python main.py --paths
)
echo.
pause
