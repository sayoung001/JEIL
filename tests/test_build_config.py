"""빌드 설정이 코드와 어긋나지 않는가.

exe 는 만들어 보기 전에는 문제를 모른다. 여기서 막을 수 있는 것만이라도 막는다.

리눅스에서 실제로 PyInstaller 빌드를 돌려 확인한 것:
  · workflows / templates / config.example.yaml 이 번들에 들어간다
  · 함수 안에서 늦게 import 하는 pymupdf · PIL · xlrd 가 잡힌다
  · exe 옆에 config.yaml · logs · 진단결과.txt 가 생긴다
  · 파이썬이 전혀 없는 환경에서 --selftest · --monthly · GUI 가 돈다
Windows 빌드는 Windows 에서 확인해야 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = (ROOT / "build.bat").read_text(encoding="utf-8")


def _옵션(이름: str) -> list[str]:
    return re.findall(rf"{re.escape(이름)}\s+\"?([^\"^\s]+)\"?", BUILD)


def test_번들에_넣는_경로가_실제로_있다():
    """--add-data 가 가리키는 것이 없으면 exe 안에 자원이 안 들어간다."""
    entries = re.findall(r'--add-data\s+"([^";]+);', BUILD)
    assert entries, "--add-data 가 없습니다"
    for rel in entries:
        assert (ROOT / rel).exists(), f"--add-data 대상이 없습니다: {rel}"


def test_번들에_들어가야_할_것이_빠지지_않았다():
    entries = re.findall(r'--add-data\s+"([^";]+);', BUILD)
    for 필요 in ("workflows", "templates", "config.example.yaml"):
        assert 필요 in entries, f"{필요} 가 --add-data 에 없습니다"


def test_config_yaml_은_번들에_넣지_않는다():
    """PC 마다 달라야 하므로 exe 옆에 두고 읽는다."""
    entries = re.findall(r'--add-data\s+"([^";]+);', BUILD)
    assert "config.yaml" not in entries


def test_늦게_import_하는_모듈이_hidden_import_에_있다():
    """함수 안 import 는 exe 에서만 터진다. 못박아 둔다."""
    hidden = set(_옵션("--hidden-import"))
    for 모듈 in ("xlwings", "pymupdf", "xlrd", "openpyxl", "PIL"):
        assert 모듈 in hidden, f"--hidden-import {모듈} 가 없습니다"


@pytest.mark.parametrize("모듈,파일", [
    ("pymupdf", "core/extract.py"),
    ("xlrd", "core/excel_reader.py"),
    ("openpyxl", "core/excel_reader.py"),
    ("xlwings", "core/excel_writer.py"),
])
def test_hidden_import_가_실제로_쓰이는_모듈이다(모듈, 파일):
    """쓰지도 않는 것을 넣어 두면 나중에 헷갈린다."""
    본문 = (ROOT / 파일).read_text(encoding="utf-8")
    assert f"import {모듈}" in 본문, f"{파일} 이 {모듈} 을 쓰지 않습니다"


def test_배포_폴더에_들어가는_파일이_존재한다():
    복사 = re.findall(r"copy /y ([^\s\"]+)", BUILD)
    for 파일 in 복사:
        if 파일.startswith("dist"):
            continue                       # 빌드 결과물이라 아직 없다
        assert (ROOT / 파일).exists(), f"배포 파일이 없습니다: {파일}"


def test_회사PC로_가는_배치는_파이썬을_요구하지_않는다():
    """회사 PC 에는 파이썬이 없다. exe 만으로 돌아야 한다."""
    복사 = [f for f in re.findall(r"copy /y ([^\s\"]+)", BUILD)
            if f.endswith(".bat")]
    assert 복사, "배포 폴더에 배치 파일이 없습니다"
    for 파일 in 복사:
        본문 = (ROOT / 파일).read_text(encoding="utf-8")
        for 줄 in 본문.splitlines():
            벗김 = 줄.strip()
            if 벗김.startswith("REM") or 벗김.startswith("::"):
                continue
            if "python" in 벗김 or ".venv" in 벗김:
                # exe 가 없을 때만 쓰는 폴백은 허용 (노트북에서도 쓰라고)
                assert "if exist" in 본문, (
                    f"{파일} 이 파이썬을 요구합니다: {벗김}")


def test_처음설정은_exe만_쓴다():
    """회사 PC 에서 제일 먼저 더블클릭하는 파일."""
    본문 = (ROOT / "처음설정.bat").read_text(encoding="utf-8")
    assert "python" not in 본문 and ".venv" not in 본문
    for 옵션 in ("--setup", "--selftest", "--paths"):
        assert 옵션 in 본문, f"처음설정.bat 에 {옵션} 이 없습니다"


def test_onefile_과_windowed_를_함께_쓴다():
    assert "--onefile" in BUILD
    assert "--windowed" in BUILD, "GUI 프로그램이므로 콘솔 창이 뜨면 안 된다"


def test_windowed_라서_콘솔붙이기가_필요하다():
    """--windowed exe 는 cmd 에 출력을 못 보낸다. 대응이 있어야 한다."""
    if "--windowed" not in BUILD:
        pytest.skip("windowed 빌드가 아니다")
    paths = (ROOT / "core" / "paths.py").read_text(encoding="utf-8")
    assert "AttachConsole" in paths
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "attach_console()" in main
    assert "진단결과" in main, "콘솔이 안 붙어도 결과가 파일로 남아야 한다"
