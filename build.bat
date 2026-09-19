@echo off
chcp 65001 > nul
REM ============================================================
REM  품질 업무 자동화 — exe 빌드 (SPEC §9 S10)
REM
REM  이 배치는 "만드는 PC"(노트북)에서만 돌린다.
REM  만들어진 배포 폴더를 회사 PC 로 통째로 복사하면 끝이다.
REM  회사 PC 에는 파이썬도 VS Code 도 필요 없다.
REM ============================================================
cd /d "%~dp0"

if not exist .venv (
    echo [1/4] 가상환경을 만듭니다...
    py -3.11 -m venv .venv
)
call .venv\Scripts\activate
echo [2/4] 의존성을 설치합니다...
pip install -r requirements.txt

REM OCR 을 함께 넣으려면 아래 주석을 풀고 --hidden-import 도 푼다.
REM 성적서 PDF 는 텍스트 레이어가 있어 OCR 없이 읽히므로 기본은 빼 둔다 (exe 가 가벼워진다).
REM pip install rapidocr-onnxruntime

echo [3/4] exe 를 만듭니다...
REM --add-data 로 넣은 것은 exe 안에 구워진다 (읽기 전용).
REM config.yaml 은 절대 넣지 않는다 — PC 마다 달라야 하므로 exe 옆에 두고 읽는다.
pyinstaller --noconfirm --clean ^
    --onefile --windowed ^
    --name 품질자동화 ^
    --add-data "workflows;workflows" ^
    --add-data "templates;templates" ^
    --add-data "config.example.yaml;." ^
    --hidden-import xlwings ^
    --hidden-import pymupdf ^
    --collect-binaries pymupdf ^
    --exclude-module pytest ^
    --exclude-module rapidocr_onnxruntime ^
    main.py

if errorlevel 1 (
    echo.
    echo !! 빌드에 실패했습니다. 위 메시지를 확인하세요.
    pause
    exit /b 1
)

echo [4/4] 배포 폴더를 꾸립니다...
set DEPLOY=dist\회사PC로_복사할것
if exist "%DEPLOY%" rmdir /s /q "%DEPLOY%"
mkdir "%DEPLOY%"
copy /y dist\품질자동화.exe "%DEPLOY%\" > nul
copy /y 배포안내.txt         "%DEPLOY%\" > nul
copy /y 처음설정.bat         "%DEPLOY%\" > nul
copy /y 자가점검.bat         "%DEPLOY%\" > nul

echo.
echo ============================================================
echo  빌드 완료:  %DEPLOY%
echo.
echo  회사 PC 로 옮기는 방법
echo    1. 위 폴더를 통째로 USB 에 담아 회사 PC 로 복사한다
echo    2. 회사 PC 에서 처음설정.bat 을 더블클릭한다
echo       (config.yaml 생성 + 서류투입 폴더 생성 + 자가 점검)
echo    3. 화면에 X 가 있으면 배포안내.txt 를 본다
echo    4. 품질자동화.exe 를 더블클릭해 쓴다
echo.
echo  회사 PC 에는 파이썬도 VS Code 도 설치할 필요가 없다.
echo ============================================================
pause
