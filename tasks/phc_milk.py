"""T-04 PHC 밀크 / 물시멘트비 (Q-Q-01) — SPEC §17.

입력은 숫자 6개뿐이고 나머지는 전부 수식이다. 자동화 효과가 가장 큰 문서.

1. ``612`` `양식` -> `04` 시트 복제 + 셀 기입 (수식은 템플릿에 이미 있다)
2. ``612`` 짝이 되는 `사진대지 (N)` 시트도 복제 (**사진 삽입은 수동**)
3. ``612`` `대장` 1행 추가
4. ``Q-01,02 실시대장`` h=2 행그룹

`612` 는 레거시 `.xls` 다. 확장자를 바꾸지 않는다 (§20.1).
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.context import TaskContext
from core.engines import RowGroupWriter, SheetCloneWriter
from core.ledger import LedgerEntry, LedgerTemplate, LedgerWriter
from core.models import MilkTest, Series
from core.numbering import 대장_구분표기, 시험번호, 판정표기
from core.sheets import col_index

from .base import Task

log = logging.getLogger(__name__)

TEMPLATE_SHEET = "양식"
PHOTO_SHEET = "사진대지"
LIST_SHEET = "대장"

# 일지 시트 셀 맵 (§14.2). 값 앞의 공백 1칸은 원본 관행 그대로 유지한다.
CELLS = {
    "시험번호": "F3", "시료채취일": "U3", "시료종류": "F4", "채취장소": "U4",
    "시험일자": "F5", "시공업체": "U5",
    "S1_총중량": "I8", "S1_건조중량": "I9", "S1_용기무게": "I10",
    "S2_총중량": "P8", "S2_건조중량": "P9", "S2_용기무게": "P10",
    "기준": "W8", "판정": "AA8",
}
# 계산은 원본 수식을 그대로 다시 깔아 준다 (사람이 셀을 보면 검산이 되게)
FORMULAS = {
    "I11": "=I9-I10", "P11": "=P9-P10",
    "I12": "=I8-I11-I10", "P12": "=P8-P11-P10",
    "I13": "=I12/I11*100", "P13": "=P12/P11*100",
}

LIST_COL = {"No": 1, "날짜": 2, "S1": 3, "S2": 4, "판정": 5, "비고": 6}
LIST_FIRST_ROW = 5


def _ref(name: str) -> tuple[int, int]:
    a1 = CELLS[name]
    i = 0
    while a1[i].isalpha():
        i += 1
    return int(a1[i:]), col_index(a1[:i])


class PhcMilkTask(Task):
    name = "PHC 밀크 시험"
    workflow_file = "밀크.yaml"
    target_files = ("test_milk", "ledger_pile")

    def preview_sheets(self) -> dict[str, list[str]]:
        return {}

    # =================================================================
    def next_number(self, ctx: TaskContext) -> int:
        """612 의 숫자 시트('01','02',…) 다음 번호 (§17.1)."""
        clone = SheetCloneWriter(ctx.book("test_milk"), TEMPLATE_SHEET)
        return int(clone.next_numeric_name())

    # =================================================================
    def validate_before(self, data: MilkTest, ctx: TaskContext) -> list[str]:
        p: list[str] = []
        for label, sp in (("S-1", data.S1), ("S-2", data.S2)):
            if sp.건조중량 <= sp.용기무게:
                p.append(f"{label}: 건조 후 중량({sp.건조중량})이 용기 무게({sp.용기무게})보다 "
                         "커야 합니다. 시멘트 질량이 0 이하가 됩니다.")
            elif sp.총중량 <= sp.건조중량:
                p.append(f"{label}: 총중량({sp.총중량})이 건조 후 중량({sp.건조중량})보다 "
                         "커야 합니다. 물 질량이 음수가 됩니다.")
        if data.시험일자 < data.시료채취일:
            p.append("시험일자가 시료채취일보다 빠릅니다.")
        try:
            book = ctx.book("test_milk")
            if not book.has_sheet(TEMPLATE_SHEET):
                p.append(f"612 에 `{TEMPLATE_SHEET}` 시트가 없습니다: {book.sheet_names}")
            if book.has_sheet(f"{data.번호:02d}"):
                p.append(f"612 에 `{data.번호:02d}` 시트가 이미 있습니다.")
        except Exception as e:
            p.append(f"612 를 읽을 수 없습니다: {e}")
        return p

    # =================================================================
    def execute(self, data: MilkTest, ctx: TaskContext) -> None:
        self._write_journal(data, ctx)
        self._write_list(data, ctx)
        self._write_ledger(data, ctx)

    # -- 1·2. 일지 시트 + 사진대지 시트 복제 ------------------------------
    def _write_journal(self, data: MilkTest, ctx: TaskContext) -> None:
        book = ctx.book("test_milk")
        clone = SheetCloneWriter(book, TEMPLATE_SHEET)
        sheet = clone.clone(f"{data.번호:02d}")

        def put(key: str, value: object) -> None:
            r, c = _ref(key)
            sheet.write(r, c, value)

        # 원본 관행: 값 앞에 공백 1칸이 붙어 있다 (§14.2)
        put("시험번호", f" {시험번호(Series.PHC_MILK, data.번호)}")
        put("시료채취일", f" {data.시료채취일:%Y-%m-%d}")
        put("시료종류", f" {data.시료종류}")
        put("채취장소", f" {data.채취장소}")
        put("시험일자", f" {data.시험일자:%Y-%m-%d}")
        put("시공업체", f" {data.시공업체}")

        put("S1_총중량", data.S1.총중량)
        put("S1_건조중량", data.S1.건조중량)
        put("S1_용기무게", data.S1.용기무게)
        put("S2_총중량", data.S2.총중량)
        put("S2_건조중량", data.S2.건조중량)
        put("S2_용기무게", data.S2.용기무게)

        # 계산 수식 (템플릿에 이미 있어도 같은 값으로 다시 깔아 안전하게)
        for a1, formula in FORMULAS.items():
            i = 0
            while a1[i].isalpha():
                i += 1
            sheet.write(int(a1[i:]), col_index(a1[:i]), formula)

        put("기준", data.기준)
        put("판정", 판정표기(data.합격, "일지601"))

        # 짝이 되는 사진대지 시트 (사진 삽입은 수동)
        photo_name = clone.next_paired_name(PHOTO_SHEET)
        if book.has_sheet(PHOTO_SHEET):
            clone.clone(photo_name, after=sheet.name, template=PHOTO_SHEET)
        else:
            log.warning("612 에 `%s` 시트가 없어 사진대지 복제를 건너뜁니다", PHOTO_SHEET)

    # -- 3. 612 대장 -----------------------------------------------------
    def _write_list(self, data: MilkTest, ctx: TaskContext) -> None:
        sh = ctx.book("test_milk").sheet(LIST_SHEET)
        rg = RowGroupWriter(sh, LIST_FIRST_ROW, 1, key_col=LIST_COL["No"], width=6)
        row = rg.append_group()
        r1, r2 = data.결과들
        rg.set(row, LIST_COL["No"], rg.sequence_no())
        rg.set(row, LIST_COL["날짜"], data.시험일자, number_format="yyyy-mm-dd")
        rg.set(row, LIST_COL["S1"], round(r1, 1))
        rg.set(row, LIST_COL["S2"], round(r2, 1))
        rg.set(row, LIST_COL["판정"], 판정표기(data.합격, "대장612"))

    # -- 4. 실시대장 (h=2, L만 행별) --------------------------------------
    def _write_ledger(self, data: MilkTest, ctx: TaskContext) -> None:
        tpl = LedgerTemplate.load(
            Path(__file__).resolve().parent.parent / "templates" / "현장시험" / "PHC밀크.yaml")
        writer = LedgerWriter(ctx.book("ledger_pile"), tpl)
        r1, r2 = data.결과들
        writer.append(LedgerEntry(
            날짜=data.완료일,
            구분=대장_구분표기(Series.PHC_MILK, data.번호),
            공장=data.시공업체,
            장소="현장내",
            규격="-",
            # 실시대장 L열은 소수 1자리 (§17.2 실측: 79.9 / 76.4)
            결과=[round(r1, 1), round(r2, 1)],
            판정=판정표기(data.합격, "실시대장"),
            기술인=data.품질관리기술인,
            감리원=data.감리원,
        ))
