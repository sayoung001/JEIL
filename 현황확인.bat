@echo off
chcp 65001 > nul
REM 엑셀을 띄우지 않고 현재 상태만 출력한다 (읽기 전용)
cd /d "%~dp0"
if exist .venv call .venv\Scripts\activate
echo ===== 파일 현황 =====
python main.py --dump
echo.
echo ===== 시험 도래 판정 =====
python main.py --check
echo.
echo ===== 정합성 검사 =====
python main.py --verify
pause
