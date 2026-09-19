"""보고서 자리 찾기 · 기입 (좌표를 실측하지 못한 파일을 글자로 다룬다)."""
from __future__ import annotations

from datetime import date

import pytest

from core.monthly_report import 종목집계, MonthlyTally
from core.report_layout import LayoutError, find_layout
from core.sheets import MemorySheet
from tasks.monthly_report import MonthlyInput, MonthlyReportTask
from tests.fixtures import FakeContext, cfg as base_cfg


def 보고서시트(*, 누계=True, 종목=None) -> MemorySheet:
    """건설기술진흥법 서식 모양의 실적보고서 시트."""
    sh = MemorySheet(name="품질시험검사 실적보고서(8월)")
    sh.write(1, 1, "품질시험·검사 실적보고서")
    sh.write(3, 3, "금   월")
    if 누계:
        sh.write(3, 7, "누   계")
    sh.write(4, 1, "시험·검사 종목")
    for i, 이름 in enumerate(("실시", "합격", "불합격", "재시험")):
        sh.write(4, 3 + i, 이름)
        if 누계:
            sh.write(4, 7 + i, 이름)
    종목 = 종목 or ["겉모양 및 모양", "치수", "물시멘트비(W/C)",
                    "동재하시험", "용접부 비파괴검사"]
    for i, 이름 in enumerate(종목):
        sh.write(5 + i, 1, 이름)
    sh.write(5 + len(종목), 1, "계")
    sh.log.clear()
    return sh


# =====================================================================
# 자리 찾기
# =====================================================================
def test_헤더와_종목열과_묶음을_찾는다():
    layout = find_layout(보고서시트())
    assert layout.헤더행 == 4
    assert layout.종목열 == 1
    assert layout.묶음["금월"] == {"실시": 3, "합격": 4, "불합격": 5, "재시험": 6}
    assert layout.묶음["누계"] == {"실시": 7, "합격": 8, "불합격": 9, "재시험": 10}


def test_종목행을_찾는다():
    layout = find_layout(보고서시트())
    assert layout.찾기("치수") == 6
    assert layout.찾기("동재하시험") == 8
    assert layout.찾기("없는종목") is None


def test_공백을_무시하고_찾는다():
    """'합 격' 처럼 파일마다 공백이 다르다."""
    layout = find_layout(보고서시트(종목=["겉 모 양 및 모양", "치 수"]))
    assert layout.찾기("겉모양 및 모양") is not None
    assert layout.찾기("치수") is not None


def test_불합격이_합격으로_잡히지_않는다():
    layout = find_layout(보고서시트())
    assert layout.묶음["금월"]["합격"] != layout.묶음["금월"]["불합격"]


def test_계_행은_종목으로_잡지_않는다():
    layout = find_layout(보고서시트())
    assert "계" not in layout.종목행


def test_누계칸이_없으면_금월만_잡는다():
    layout = find_layout(보고서시트(누계=False))
    assert "금월" in layout.묶음
    assert "누계" not in layout.묶음


def test_헤더가_없으면_추측하지_않고_멈춘다():
    sh = MemorySheet(name="엉뚱한시트")
    sh.write(1, 1, "이 시트에는 표가 없습니다")
    with pytest.raises(LayoutError, match="헤더 행을 찾지 못했습니다"):
        find_layout(sh)


def test_종목이_하나도_없으면_멈춘다():
    sh = MemorySheet(name="빈표")
    sh.write(3, 3, "금   월")
    sh.write(4, 1, "시험·검사 종목")
    for i, 이름 in enumerate(("실시", "합격", "불합격", "재시험")):
        sh.write(4, 3 + i, 이름)
    with pytest.raises(LayoutError, match="종목 이름을 하나도"):
        find_layout(sh)


def test_중복_종목은_첫_행을_쓰고_알린다():
    layout = find_layout(보고서시트(종목=["치수", "치수", "동재하시험"]))
    assert layout.찾기("치수") == 5
    assert any("중복" in w for w in layout.경고)


# =====================================================================
# 기입
# =====================================================================
def _tally(시트명: str, **값) -> MonthlyTally:
    t = MonthlyTally(시트명=시트명)
    for 이름, (실시, 합격) in 값.items():
        t.종목[이름] = 종목집계(이름, 실시=실시, 합격=합격)
    return t


def _books(sheet: MemorySheet):
    from core.sheets import MemoryWorkbook

    wb = MemoryWorkbook(path="윤재웅 실적총괄.xlsx")
    wb.sheets[sheet.name] = sheet
    return {"report_monthly": wb}


def test_금월과_누계를_쓴다():
    sh = 보고서시트()
    ctx = FakeContext(base_cfg(), _books(sh))
    data = MonthlyInput(
        월="26.08",
        전월=_tally("전월누계", **{"치수": (2, 2), "동재하시험": (1, 1)}),
        금월=_tally("26.08", **{"치수": (4, 4), "동재하시험": (3, 3)}))

    MonthlyReportTask(base_cfg()).execute(data, ctx)

    assert sh.read(6, 3) == 4 and sh.read(6, 4) == 4       # 치수 금월
    assert sh.read(6, 7) == 6 and sh.read(6, 8) == 6       # 치수 누계 = 2+4
    assert sh.read(8, 3) == 3                               # 동재하 금월
    assert sh.read(8, 7) == 4                               # 동재하 누계 = 1+3


def test_누계쓰기를_끄면_금월만_쓴다():
    sh = 보고서시트()
    ctx = FakeContext(base_cfg(), _books(sh))
    data = MonthlyInput(월="26.08", 누계쓰기=False,
                        전월=_tally("전월누계", **{"치수": (2, 2)}),
                        금월=_tally("26.08", **{"치수": (4, 4)}))
    MonthlyReportTask(base_cfg()).execute(data, ctx)
    assert sh.read(6, 3) == 4
    assert sh.read(6, 7) is None


def test_보고서에_없는_종목은_건너뛴다():
    """조용히 넘어가도 되는 유일한 경우 — 사전 검증이 이미 경고한다."""
    sh = 보고서시트(종목=["치수"])
    ctx = FakeContext(base_cfg(), _books(sh))
    data = MonthlyInput(월="26.08", 전월=_tally("전월누계"),
                        금월=_tally("26.08", **{"치수": (4, 4), "없는종목": (1, 1)}))
    MonthlyReportTask(base_cfg()).execute(data, ctx)
    assert sh.read(5, 3) == 4


def test_사후검증이_어긋남을_잡는다():
    sh = 보고서시트()
    ctx = FakeContext(base_cfg(), _books(sh))
    task = MonthlyReportTask(base_cfg())
    data = MonthlyInput(월="26.08", 전월=_tally("전월누계"),
                        금월=_tally("26.08", **{"치수": (4, 4)}))
    task.execute(data, ctx)
    assert task.validate_after(data, ctx) == []

    sh.write(6, 3, 99)                                      # 사람이 손댄 척
    어긋남 = task.validate_after(data, ctx)
    assert 어긋남 and "치수" in 어긋남[0]


def test_같은_달_시트가_여러개면_사람이_고르게_한다():
    """진단 §5 — (8월) (8월)(2) 8월 수정본 세 벌이 실제로 있다."""
    from core.sheets import MemoryWorkbook

    wb = MemoryWorkbook(path="윤재웅 실적총괄.xlsx")
    for 이름 in ("품질시험검사 실적보고서(8월)", "품질시험검사 실적보고서(8월)(2)"):
        sh = 보고서시트()
        sh.name = 이름
        wb.sheets[이름] = sh
    ctx = FakeContext(base_cfg(), {"report_monthly": wb})
    task = MonthlyReportTask(base_cfg())
    data = MonthlyInput(월="26.08", 전월=_tally("전월누계"),
                        금월=_tally("26.08", **{"치수": (4, 4)}))
    문제 = task.validate_before(data, ctx)
    assert any("여러 개입니다" in p for p in 문제)


def test_시트를_지정하면_그것을_쓴다():
    from core.sheets import MemoryWorkbook

    wb = MemoryWorkbook(path="윤재웅 실적총괄.xlsx")
    for 이름 in ("품질시험검사 실적보고서(8월)", "품질시험검사 실적보고서(8월) 수정본"):
        sh = 보고서시트()
        sh.name = 이름
        wb.sheets[이름] = sh
    ctx = FakeContext(base_cfg(), {"report_monthly": wb})
    data = MonthlyInput(월="26.08", 시트="품질시험검사 실적보고서(8월) 수정본",
                        전월=_tally("전월누계"), 금월=_tally("26.08", **{"치수": (4, 4)}))
    MonthlyReportTask(base_cfg()).execute(data, ctx)
    assert wb.sheets["품질시험검사 실적보고서(8월) 수정본"].read(6, 3) == 4
    assert wb.sheets["품질시험검사 실적보고서(8월)"].read(6, 3) is None


def test_월이름_변환():
    assert MonthlyInput(월="26.08").월이름 == "8월"
    assert MonthlyInput(월="26.12").월이름 == "12월"
