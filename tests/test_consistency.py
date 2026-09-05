"""정합성 검사기 검증 (SPEC §21).

§21.1 에서 실제로 잡힌 오류 3건과 §21.2 의 미정정 2건을 재현해,
검사기가 앞으로도 같은 것을 잡는지 본다.
"""
from __future__ import annotations

from datetime import date

import openpyxl
import pytest

from core.config import Config
from core.consistency import ConsistencyChecker
from tests.fixtures import cfg as base_cfg


def _613(path, *, 목록_C10=1.03, 일지7_7일=1.03) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BSCW_압축강도_시험일지"
    for n in range(1, 9):
        c0 = 1 + (n - 1) * 11
        ws.cell(5, c0 + 2, f"Q-Q-03-{n:02d}")
        ws.cell(11, c0 + 6, 일지7_7일 if n == 7 else 1.0)
        ws.cell(18, c0 + 6, 2.0)
    jsp = wb.create_sheet("JSP_압축강도_시험일지")
    jsp.cell(5, 3, "Q-Q-03-01")            # §21.2 #4 — JSP 일지에 BSCW 계열 번호
    목록 = wb.create_sheet("시험목록")
    for i in range(8):
        목록.cell(4 + i, 1, i + 1)
        목록.cell(4 + i, 2, date(2026, 7, 31))
        목록.cell(4 + i, 3, 1.0)
        목록.cell(4 + i, 4, 2.0)
    목록.cell(10, 3, 목록_C10)              # 7번의 7일 강도 (§21.1 #3)
    wb.save(path)


def _대장(path, *, A10=4, 날짜=None) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "26.09"
    for i in range(4):
        r = 4 + i
        ws.cell(r, 1, i + 1 if r != 10 else None)
        ws.cell(r, 2, date(2026, 8, 28))
        ws.cell(r, 3, f"Q-Q-\n03-{i + 1:02d}")
    ws.cell(10, 1, A10)                     # §21.2 #5 — 일련번호 중복
    ws.cell(10, 2, 날짜 or date(2026, 8, 28))
    ws.cell(10, 3, "Q-Q-\n03-04")
    wb.save(path)


@pytest.fixture()
def 환경(tmp_path):
    def build(**kw):
        c = base_cfg()
        raw = dict(c.raw)
        raw["files"] = dict(raw["files"])
        p613 = tmp_path / "613.xlsx"
        _613(p613, 목록_C10=kw.get("목록_C10", 1.03), 일지7_7일=kw.get("일지7_7일", 1.03))
        p대장 = tmp_path / "Q-03.xlsx"
        _대장(p대장, A10=kw.get("A10", 4), 날짜=kw.get("날짜"))
        raw["files"]["test_bscw_jsp"] = str(p613)
        raw["files"]["ledger_civil"] = str(p대장)
        for k in ("ledger_pile", "ledger_outsrc", "test_shape", "test_milk"):
            raw["files"][k] = str(tmp_path / "없음.xlsx")
        return Config(raw=raw)
    return build


# =====================================================================
def test_평균값_3자불일치를_잡는다(환경):
    """§21.1 #3 — 613 시험목록 C10 이 3.08 이었는데 일지 평균은 1.03 이었다."""
    found = ConsistencyChecker(환경(목록_C10=3.08)).check_all(date(2026, 9, 5))
    hits = [f for f in found if f.수준 == "error" and "평균" in f.내용]
    assert hits, [str(f) for f in found]
    assert hits[0].수준 == "error"
    assert hits[0].고칠수있음 and hits[0].제안값 == 1.03
    assert "시험목록!C10" in hits[0].위치


def test_평균이_맞으면_보고하지_않는다(환경):
    found = ConsistencyChecker(환경()).check_all(date(2026, 9, 5))
    assert not [f for f in found if f.수준 == "error" and "평균" in f.내용]


def test_JSP일지의_BSCW계열_번호를_잡는다(환경):
    """§21.1 #1,#2 와 §21.2 #4 — 계열이 뒤섞인 시험번호."""
    found = ConsistencyChecker(환경()).check_all(date(2026, 9, 5))
    hits = [f for f in found if f.수준 == "error" and "계열" in f.내용]
    assert hits
    assert hits[0].제안값 == "Q-Q-04-01"        # JSP 계열로 고쳐야 한다


def test_대장_일련번호_중복을_잡는다(환경):
    """§21.2 #5 — Q-03 대장 26.09 A10 이 3 으로 중복돼 있었다 (4여야 함)."""
    found = ConsistencyChecker(환경(A10=3)).check_all(date(2026, 9, 5))
    hits = [f for f in found if f.수준 == "error" and "일련번호" in f.내용]
    assert hits and hits[0].제안값 == 5           # 5번째 행이므로 5
    assert hits[0].고칠수있음


def test_BSCW_대장날짜_규칙위반을_잡는다(환경):
    """§15.2 — 채취일 7/31 + 28 = 8/28 이어야 한다."""
    found = ConsistencyChecker(환경(날짜=date(2026, 9, 1))).check_all(date(2026, 9, 5))
    hits = [f for f in found if f.수준 == "error" and "+28" in f.내용]
    assert hits and hits[0].제안값 == date(2026, 8, 28)


def test_읽지_못한_파일은_경고로_남는다(환경):
    found = ConsistencyChecker(환경()).check_all(date(2026, 9, 5))
    warns = [f for f in found if f.수준 == "warn" and "읽지 못했습니다" in f.내용]
    assert warns                                  # 조용히 건너뛰지 않는다
