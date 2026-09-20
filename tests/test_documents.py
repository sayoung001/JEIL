"""성적서 읽기 · 문서 투입 (진단 PART C · PART D).

진단 문서가 **실제 PDF 를 열어 확인한 문구** 를 그대로 재료로 쓴다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core.documents import parse, parse_file, _규격찾기
from core.extract import extract
from core.ocr import OcrUnavailable, describe, get_provider, require_provider
from tests.fixtures import cfg

pymupdf = pytest.importorskip("pymupdf")

# --- 진단 PART C §7 실측 문구 -----------------------------------------
MT_TEXT = """시험성적서
발급 번호 IS-2026-163136-00      접수 일자 2026.09.15
시험명 자분탐상검사
결과   PHC파일 105동 NO 379 : 이상없음
참관자1 윤재웅   참관자2 김번환
책임기술인 신의식 / 시험검사자 정석모"""

재하_TEXT = """시험성적서
발급 번호 IS-2026-156157-00      접수 일자 2026.08.24
시험명 시항타 / 동재하 (KS F 2591)
결과   전체지지력(초기항타) : 2815 (kN/본)
       ·시험검사: 2026-08-24
       ·채취장소: 113동 No.152
       ·허용지지력(안전율2.5적용): 1126.0kN/본
       ·설계지지력: 1300.0kN/본"""

생산_TEXT = """PHC파일 시험성적서
종류및규격 A - 500 - 11    로트번호 260914    검사일자 2026.09.14
바깥지름 502 / 502   두께 85 / 83   길이 11001 / 11002   전부 합격"""

송장_TEXT = """출하송장
㈜한국파일    2026-09-05
규격 500-15M    수량 24 본"""


def _pdf(path: Path, text: str) -> Path:
    """텍스트 레이어가 있는 PDF 를 만든다 (아이텍 성적서와 같은 성질)."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), text, fontsize=9,
                     fontname="korea")          # PyMuPDF 내장 한국어 폰트
    doc.save(path)
    doc.close()
    return path


def _scan_pdf(path: Path) -> Path:
    """텍스트 레이어가 없는 스캔본 흉내 (그림만 있는 PDF)."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 200, 200), fill=(0.5, 0.5, 0.5))
    doc.save(path)
    doc.close()
    return path


# =====================================================================
# 파싱 — 항목이 제대로 나오는가
# =====================================================================
def test_MT성적서():
    d = parse(MT_TEXT)
    assert d.종류 == "MT성적서"
    assert d.get("성적서번호") == "IS-2026-163136-00"
    assert d.get("접수일자") == date(2026, 9, 15)
    assert d.get("동") == "105" and d.get("말뚝번호") == "379"
    assert d.get("결과") == "이상없음"
    assert d.get("판정") == "합 격"
    assert d.get("참관자") == "윤재웅"
    assert d.경고 == []


def test_재하성적서_허용지지력이_대장결과값이다():
    """진단 §7 — 1126 이 O-01,04 실시대장 '시험 결과' 열에 들어가는 값."""
    d = parse(재하_TEXT)
    assert d.종류 == "재하성적서"
    assert d.get("성적서번호") == "IS-2026-156157-00"
    assert d.get("허용지지력") == 1126.0
    assert d.get("설계지지력") == 1300.0
    assert d.get("전체지지력") == 2815.0
    assert d.get("동") == "113" and d.get("말뚝번호") == "152"
    assert d.get("시험일자") == date(2026, 8, 24)
    assert d.get("종별") == "시항타"


def test_재하_허용이_설계보다_작으면_단정하지_않고_알린다():
    """시항타는 판정 대상이 아닐 수 있다. 프로그램이 불합격이라 못 박지 않는다."""
    d = parse(재하_TEXT)
    assert d.get("판정_참고") == "허용 < 설계"
    assert "판정은 직접 정하세요" in " ".join(d.경고)
    assert "판정" not in d.항목            # 합·불을 임의로 채우지 않는다


def test_PHC생산성적서_치수():
    d = parse(생산_TEXT)
    assert d.종류 == "PHC생산성적서"
    assert (d.get("규격_A"), d.get("규격_m")) == (500, 11)
    assert d.get("로트번호") == "260914"
    assert d.get("검사일자") == date(2026, 9, 14)
    assert d.get("바깥지름") == [502.0, 502.0]
    assert d.get("두께") == [85.0, 83.0]
    assert d.get("길이") == [11001.0, 11002.0]


def test_송장_업체명은_vendor_alias로_정규화():
    d = parse(송장_TEXT, vendors=cfg().vendors)
    assert d.종류 == "자재송장"
    assert d.get("업체") == "한국파일"       # '㈜한국파일' -> 표준 키
    assert d.get("수량_본") == 24.0
    assert (d.get("규격_A"), d.get("규격_m")) == (500, 15)


@pytest.mark.parametrize("text,expect", [
    ("규격 500-15M 수량 24 본", (500, 15)),
    ("A - 500 - 11", (500, 11)),
    ("2026-09-05 출하", (None, None)),        # 날짜를 규격으로 읽지 않는다
    ("010-1234-5678", (None, None)),          # 전화번호도
    ("규격 500-99", (None, None)),            # 길이 범위 밖
])
def test_규격찾기가_날짜를_규격으로_읽지_않는다(text, expect):
    assert _규격찾기(text) == expect


def test_모르는_문서는_미상으로_두고_넘긴다():
    d = parse("오늘 점심 메뉴는 김치찌개입니다. 맛있게 드세요.")
    assert d.종류 == "미상"
    assert not d.읽힘
    assert "직접 분류" in " ".join(d.경고)


def test_빈_글자():
    d = parse("")
    assert d.종류 == "미상"
    assert "글자가 없습니다" in " ".join(d.경고)


# =====================================================================
# 추출 — 텍스트 레이어 우선, OCR 은 폴백
# =====================================================================
def test_텍스트레이어가_있으면_OCR없이_읽는다(tmp_path):
    p = _pdf(tmp_path / "mt.pdf", MT_TEXT)
    got = extract(p)
    assert got.방식 == "pdf-text"
    assert got.텍스트레이어 is True
    assert got.ok
    assert "IS-2026-163136-00" in got.text
    assert got.warnings == []


def test_파일에서_바로_파싱까지(tmp_path):
    p = _pdf(tmp_path / "재하.pdf", 재하_TEXT)
    doc, got = parse_file(p)
    assert got.방식 == "pdf-text"
    assert doc.종류 == "재하성적서"
    assert doc.get("허용지지력") == 1126.0


def test_스캔본은_OCR이_없으면_조용히_넘어가지_않는다(tmp_path):
    """글자 없는 문서로 착각하게 두면 안 된다."""
    p = _scan_pdf(tmp_path / "scan.pdf")
    got = extract(p)
    assert not got.ok
    합쳐 = " ".join(got.warnings)
    if get_provider() is None:
        assert "OCR" in 합쳐
    assert "텍스트 레이어" in 합쳐 or "OCR" in 합쳐


def test_없는_파일은_경고만(tmp_path):
    got = extract(tmp_path / "없음.pdf")
    assert not got.ok
    assert "파일이 없습니다" in " ".join(got.warnings)


def test_다룰수없는_형식(tmp_path):
    f = tmp_path / "메모.txt"
    f.write_text("내용", encoding="utf-8")
    got = extract(f)
    assert "형식" in " ".join(got.warnings)


# =====================================================================
# OCR 제공자
# =====================================================================
def test_OCR이_없으면_분명히_알린다():
    if get_provider() is not None:
        pytest.skip("이 환경에 OCR 엔진이 설치돼 있다")
    with pytest.raises(OcrUnavailable, match="설치"):
        require_provider()


def test_OCR_상태를_보여준다():
    text = describe()
    assert "rapidocr" in text and "easyocr" in text
    assert "선택" in text            # 필수가 아님을 명시


def test_모르는_엔진이름은_None():
    assert get_provider("없는엔진") is None
