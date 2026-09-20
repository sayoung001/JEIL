"""T-09 월간 품질시험·검사 실적보고서 자동 집계 (진단 PART D 1순위).

실시대장 4종을 세어 보고서의 금월·누계 칸을 채운다.

**세는 것과 쓰는 것을 나눴다.**
세는 일(``core/monthly_report.py``)은 실측표로 검증돼 있고, 쓰는 일은
보고서 레이아웃을 실측하지 못해 **글자로 자리를 찾는다**(``core/report_layout.py``).
자리를 못 찾으면 아무 데나 쓰지 않고 멈춘다 — 감리 제출 문서라 엉뚱한 칸에
숫자가 들어가는 것이 빈칸보다 나쁘다.

집계만 먼저 써 보려면 Excel 없이 ``--monthly 26.08`` 로 확인할 수 있다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.context import TaskContext
from core.monthly_report import MonthlyReporter, MonthlyTally
from core.report_layout import LayoutError, find_layout

from .base import Task

log = logging.getLogger(__name__)


@dataclass
class MonthlyInput:
    """어느 달을, 어느 시트에."""

    월: str                                  # '26.08'
    시트: str | None = None                  # 없으면 이름으로 찾는다
    #: 누계도 함께 쓸 것인가
    누계쓰기: bool = True
    #: 미리 계산해 둔 집계 (미리보기에서 이어 쓸 때)
    전월: MonthlyTally | None = None
    금월: MonthlyTally | None = None
    경고무시: bool = False

    @property
    def 월이름(self) -> str:
        """'26.08' -> '8월' (시트 이름 찾기용)."""
        return f"{int(self.월.split('.')[1])}월"


class MonthlyReportTask(Task):
    name = "월간 실적보고서 집계"
    workflow_file = "실적보고서.yaml"
    target_files = ("report_monthly",)

    def __init__(self, cfg):
        super().__init__(cfg)
        self.reporter = MonthlyReporter(cfg)

    # =================================================================
    def 집계(self, data: MonthlyInput) -> tuple[MonthlyTally, MonthlyTally]:
        if data.전월 is None or data.금월 is None:
            data.전월, data.금월 = self.reporter.누계(data.월)
        return data.전월, data.금월

    def _시트(self, ctx: TaskContext, data: MonthlyInput):
        book = ctx.book("report_monthly")
        if data.시트:
            return book.sheet(data.시트)
        # '품질시험검사 실적보고서(8월)' 처럼 월 이름이 든 시트를 찾는다
        후보 = [n for n in book.sheet_names if data.월이름 in n]
        if not 후보:
            raise LayoutError(
                f"실적보고서에서 '{data.월이름}' 이 든 시트를 찾지 못했습니다.\n"
                f"  있는 시트: {book.sheet_names}\n"
                "  시트 이름을 직접 지정하세요.")
        if len(후보) > 1:
            # 진단 §5 — 같은 달 시트가 3본씩 있다. 사람이 고르게 한다.
            raise LayoutError(
                f"'{data.월이름}' 시트가 여러 개입니다: {후보}\n"
                "  어느 것이 정본인지 프로그램이 정할 수 없습니다. 시트를 지정하세요.")
        return book.sheet(후보[0])

    # =================================================================
    def validate_before(self, data: MonthlyInput, ctx: TaskContext) -> list[str]:
        p: list[str] = []
        전월, 금월 = self.집계(data)

        if 금월.총건수 == 0:
            p.append(f"{data.월} 에 집계된 시험이 없습니다. 달을 확인하세요.")
        if not data.경고무시:
            p += [f"집계 경고: {w}" for w in 금월.경고
                  if "세지 못했습니다" in w or "판정이 비어" in w]

        try:
            sheet = self._시트(ctx, data)
            layout = find_layout(sheet)
        except (LayoutError, KeyError) as e:
            p.append(str(e))
            return p

        없는종목 = [k for k in 금월.종목 if layout.찾기(k) is None]
        if 없는종목:
            p.append("보고서에서 찾지 못한 종목이 있습니다: " + ", ".join(없는종목)
                     + f"\n  보고서에 있는 종목: {', '.join(list(layout.종목행)[:12])}")
        if data.누계쓰기 and "누계" not in layout.묶음:
            p.append("보고서에서 '누계' 칸을 찾지 못했습니다. "
                     "누계 없이 쓰려면 [누계 쓰기] 를 끄세요.")
        return p

    # =================================================================
    def execute(self, data: MonthlyInput, ctx: TaskContext) -> None:
        전월, 금월 = self.집계(data)
        sheet = self._시트(ctx, data)
        layout = find_layout(sheet)
        누계 = 전월.더하기(금월)

        쓸것 = [("금월", 금월)]
        if data.누계쓰기 and "누계" in layout.묶음:
            쓸것.append(("누계", 누계))

        for 묶음이름, tally in 쓸것:
            칸들 = layout.묶음.get(묶음이름, {})
            for 종목이름, 값 in tally.종목.items():
                행 = layout.찾기(종목이름)
                if 행 is None:
                    continue
                for 항목, 수 in (("실시", 값.실시), ("합격", 값.합격),
                                 ("불합격", 값.불합격), ("재시험", 값.재시험)):
                    열 = 칸들.get(항목)
                    if 열:
                        sheet.write(행, 열, 수)
        log.info("실적보고서 %s: %s", data.월, layout.요약())

    # =================================================================
    def validate_after(self, data: MonthlyInput, ctx: TaskContext) -> list[str]:
        """쓴 값이 집계와 같은지 되읽어 확인한다."""
        _, 금월 = self.집계(data)
        try:
            sheet = self._시트(ctx, data)
            layout = find_layout(sheet)
        except (LayoutError, KeyError) as e:
            return [str(e)]

        어긋남: list[str] = []
        열 = layout.묶음.get("금월", {}).get("실시")
        if 열 is None:
            return ["금월 실시 열을 찾지 못해 확인하지 못했습니다."]
        for 종목이름, 값 in 금월.종목.items():
            행 = layout.찾기(종목이름)
            if 행 is None:
                continue
            읽은값 = sheet.read(행, 열)
            if 읽은값 is None or int(float(읽은값)) != 값.실시:
                어긋남.append(f"{종목이름}: 쓴 값 {값.실시}, 읽은 값 {읽은값!r}")
        return 어긋남
