@echo off
chcp 65001 > nul
REM ============================================================
REM  품질 업무 자동화 — exe 빌드 (SPEC §9 S10)
REM
REM  이 배치는 "만드는 PC"(노트북)에서 돌린다.
REM  만들어진 exe 는 "쓰는 PC"(회사)로 복사해서 쓴다.
REM  경로는 exe 안에 굳지 않는다 — exe 옆 config.yaml 에서 읽는다.
REM ============================================================
cd /d "%~dp0"

if not exist .venv (
    echo [1/3] 가상환경을 만듭니다...
    py -3.11 -m venv .venv
)
call .venv\Scripts\activate
echo [2/3] 의존성을 설치합니다...
pip install -r requirements.txt

echo [3/3] exe 를 만듭니다...
REM --add-data 로 넣은 것은 exe 안에 구워진다 (읽기 전용, 실행 중 임시폴더에 풀림).
REM config.yaml 은 절대 넣지 않는다 — PC 마다 달라야 하므로 exe 옆에 두고 읽는다.
pyinstaller --noconfirm --clean ^
    --onefile --windowed ^
    --name 품질자동화 ^
    --add-data "workflows;workflows" ^
    --add-data "templates;templates" ^
    --add-data "config.example.yaml;." ^
    --hidden-import xlwings ^
    --exclude-module pytest ^
    main.py

if errorlevel 1 (
    echo.
    echo !! 빌드에 실패했습니다. 위 메시지를 확인하세요.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  빌드 완료:  dist\품질자동화.exe
echo.
echo  회사 PC 로 옮기는 방법
echo    1. dist\품질자동화.exe 하나만 복사한다 (다른 파일 필요 없음)
echo    2. 처음 실행하면 옆에 config.yaml 이 자동으로 생긴다
echo    3. config.yaml 의 paths.quality_root 에 그 PC 의 경로가 있는지 확인한다
echo    4. 프로그램의 [경로 확인] 버튼으로 전부 O 인지 본다
echo.
echo  경로가 안 맞으면:  품질자동화.exe --paths
echo ============================================================
pause
