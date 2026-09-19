"""자가 점검 — 회사 PC 처럼 아무것도 없는 곳에서 스스로 진단하는가."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from core.config import Config
from core.selftest import make_intake_dirs, report, run_selftest
from tests.fixtures import cfg as base_cfg


def test_설치된것과_빠진것을_구분한다():
    checks = {c.이름: c for c in run_selftest(None)}
    assert checks["사진 처리(Pillow)"].통과            # 필수, 설치돼 있다
    assert checks["PDF 글자 추출(PyMuPDF)"].통과
    assert checks["OCR 엔진(선택)"].치명적 is False     # 없어도 되는 것


def test_실제로_동작하는지까지_본다():
    """import 만 확인하면 exe 에서 자원이 빠진 것을 못 잡는다."""
    checks = {c.이름: c for c in run_selftest(None)}
    assert checks["PDF 에서 글자를 실제로 뽑는가"].통과
    assert checks["사진 압축·EXIF 제거가 되는가"].통과


def test_내장자원이_있는지_확인한다():
    이름 = [c.이름 for c in run_selftest(None)]
    assert any("workflows/자재검수.yaml" in n for n in 이름)
    assert any("templates/의뢰시험/재하시험.yaml" in n for n in 이름)


def test_설정없이도_점검이_된다():
    """회사 PC 첫 실행 — config.yaml 이 아직 없어도 진단은 돼야 한다."""
    text, 치명 = report(None)
    assert "자가 점검" in text
    assert isinstance(치명, int)


def test_엑셀쓰기_실패는_치명적이지만_안내가_붙는다():
    text, _ = report(None)
    if not sys.platform.startswith("win"):
        assert "엑셀 쓰기" in text
        assert "읽기·미리보기·판정은 그대로" in text


def test_서류투입_폴더를_만들어_준다(tmp_path):
    root = Path(__file__).resolve().parent.parent
    raw = yaml.safe_load((root / "config.example.yaml").read_text(encoding="utf-8"))
    raw["paths"] = {"quality_root": str(tmp_path / "품질"),
                    "intake_root": str(tmp_path / "서류투입")}
    import re

    table = dict(raw["paths"])

    def expand(node):
        if isinstance(node, str):
            return re.sub(r"\{(\w+)\}", lambda m: table.get(m.group(1), m.group(0)), node)
        if isinstance(node, dict):
            return {k: expand(v) for k, v in node.items()}
        if isinstance(node, list):
            return [expand(v) for v in node]
        return node

    raw = expand(raw)
    raw["paths"] = table
    made = make_intake_dirs(Config(raw=raw))

    투입 = tmp_path / "서류투입"
    assert (투입 / "BSCW").is_dir()
    assert (투입 / "의뢰시험_재하").is_dir()
    assert (투입 / "성적서_재하").is_dir()
    assert len(made) == 14

    # 하위폴더가 필요한 칸에는 안내문이 들어간다
    안내 = 투입 / "BSCW" / "여기에_폴더를_만들어_넣으세요.txt"
    assert 안내.exists()
    assert "타설일" in 안내.read_text(encoding="utf-8")
    assert not (투입 / "자재검수" / "여기에_폴더를_만들어_넣으세요.txt").exists()

    made2 = make_intake_dirs(Config(raw=raw))     # 두 번 해도 덮어쓰지 않는다
    assert made2 == []


def test_배포_안내문이_함께_간다():
    """회사 PC 담당자가 읽을 문서가 저장소에 있는가."""
    root = Path(__file__).resolve().parent.parent
    안내 = (root / "배포안내.txt").read_text(encoding="utf-8")
    assert "파이썬도 VS Code 도 설치할 필요가 없습니다" in 안내
    assert "처음설정.bat" in 안내
    assert "원본을 넣으세요" in 안내
    for bat in ("처음설정.bat", "자가점검.bat", "build.bat"):
        assert (root / bat).exists(), bat
