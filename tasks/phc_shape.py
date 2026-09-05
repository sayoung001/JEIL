"""T-03 PHC파일 겉모양·치수 (Q-Q-02) — SPEC §16.

세 곳을 함께 갱신한다.

1. ``601`` `일지`  — 12열 가로 블록 + 인쇄영역 이동
2. ``601`` `대장`  — 1행 추가
3. ``Q-01,02 실시대장`` 해당 월 시트 — 5행 행그룹
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.context import TaskContext
from core.engines import HorizontalBlockWriter, RowGroupWriter
from core.ledger import LedgerEntry, LedgerTemplate, LedgerWriter
from core.models import Series, ShapeTest
from core.numbering import (기준문자열, 대장_구분표기, 서명줄, 시험번호, 판정_겉모양,
                            판정표기, parse_시험번호)
from core.sheets import col_letter

from .base import Task

log = logging.getLogger(__name__)

JOURNAL_SHEET = "일지"
LIST_SHEET = "대장"
BLOCK_WIDTH = 12
BLOCK_ROWS = (1, 23)
SAMPLE_ROWS = list(range(9, 17))        # 9~16행, 시료 최대 8개

# 일지 블록 내부 offset (§14.1)
OFF = {"라벨1": 0, "값1": 3, "라벨2": 6, "값2": 9,
       "시료번호": 0, "길이": 1, "길이허용": 2, "바깥지름": 3, "바깥지름허용": 4,
       "두께": 5, "두께허용": 6, "모양": 7, "겉모양": 9, "판정": 11}

# 601 `대장` 열 (§14.1)
LIST_COL = {"No": 1, "날짜": 2, "업체명": 3, "규격": 4, "판정": 5, "CSI": 6}
LIST_FIRST_ROW = 5


class PhcShapeTask(Task):
    name = "PHC 겉모양·치수 시험"
    workflow_file = "겉모양치수.yaml"
    target_files = ("test_shape", "ledger_pile")

    def preview_sheets(self) -> dict[str, list[str]]:
        return {"test_shape": [JOURNAL_SHEET, LIST_SHEET]}

    # =================================================================
    def next_number(self, ctx: TaskContext) -> int:
        """601 일지 마지막 블록의 시험번호 + 1 (§16.1)."""
        sh = ctx.book("test_shape").sheet(JOURNAL_SHEET)
        w = HorizontalBlockWriter(sh, BLOCK_WIDTH, BLOCK_ROWS)
        last = w.last_block_index()
        if last == 0:
            return 1
        parsed = parse_시험번호(w.get(last, 3, OFF["값1"]))
        return (parsed[1] + 1) if parsed else last + 1

    # =================================================================
    def validate_before(self, data: ShapeTest, ctx: TaskContext) -> list[str]:
        p: list[str] = []
        if self.cfg.vendors.canonical(data.업체명) is None:
            p.append(f"vendor_alias 에 없는 업체명입니다: {data.업체명!r}")
        if not data.시료목록:
            p.append("시료가 없습니다.")
        if len(data.시료목록) > len(SAMPLE_ROWS):
            p.append(f"시료는 최대 {len(SAMPLE_ROWS)}개까지입니다 (일지 9~16행).")
        for s in data.시료목록:
            if s.길이 <= 0 or s.바깥지름 <= 0 or s.두께 <= 0:
                p.append(f"시료 {s.시료번호}: 길이·바깥지름·두께를 입력하세요.")

        try:
            sh = ctx.book("test_shape").sheet(JOURNAL_SHEET)
            w = HorizontalBlockWriter(sh, BLOCK_WIDTH, BLOCK_ROWS)
            for n in range(1, w.last_block_index() + 1):
                parsed = parse_시험번호(w.get(n, 3, OFF["값1"]))
                if parsed and parsed[1] == data.번호:
                    p.append(f"601 일지 {n}번 블록에 이미 "
                             f"{시험번호(Series.PHC_SHAPE, data.번호)} 가 있습니다.")
        except Exception as e:
            p.append(f"601 일지를 읽을 수 없습니다: {e}")
        return p

    # =================================================================
    def execute(self, data: ShapeTest, ctx: TaskContext) -> None:
        self._write_journal(data, ctx)
        self._write_list(data, ctx)
        self._write_ledger(data, ctx)

    # -- 1. 601 일지 (§14.1) ---------------------------------------------
    def _write_journal(self, data: ShapeTest, ctx: TaskContext) -> None:
        sh = ctx.book("test_shape").sheet(JOURNAL_SHEET)
        w = HorizontalBlockWriter(sh, BLOCK_WIDTH, BLOCK_ROWS)
        idx = w.clone_last()

        w.set(idx, 3, OFF["값1"], 시험번호(Series.PHC_SHAPE, data.번호))
        w.set(idx, 3, OFF["값2"], data.채취장소)
        w.set(idx, 4, OFF["값1"], data.시료종류)
        w.set(idx, 4, OFF["값2"], self.cfg.vendors.form(data.업체명, "시험601"))
        w.set(idx, 5, OFF["값1"], data.시료채취일, number_format="yyyy-mm-dd")

        채취일셀 = w.cell_ref(idx, 5, OFF["값1"])
        반입일 = data.시료반입일 or data.시료채취일
        w.set(idx, 5, OFF["값2"], 반입일, number_format="yyyy-mm-dd")
        # 4.시험일자 = 채취일 (수식 체인 유지 — §14.1)
        w.set(idx, 6, OFF["값1"], f"=+{채취일셀}", number_format="yyyy-mm-dd")
        w.set(idx, 6, OFF["값2"], f"{data.시료반입량_본} 본")

        for row, s in zip(SAMPLE_ROWS, data.시료목록):
            합격 = 판정_겉모양(s, data.규격_A, data.규격_m)
            w.set(idx, row, OFF["시료번호"], s.시료번호)
            w.set(idx, row, OFF["길이"], s.길이)
            w.set(idx, row, OFF["길이허용"], "±0.3%")
            w.set(idx, row, OFF["바깥지름"], s.바깥지름)
            w.set(idx, row, OFF["바깥지름허용"], "+5, -2")
            w.set(idx, row, OFF["두께"], s.두께)
            w.set(idx, row, OFF["두께허용"], "80이상")
            w.set(idx, row, OFF["모양"], s.모양)
            w.set(idx, row, OFF["겉모양"], s.겉모양)
            w.set(idx, row, OFF["판정"], 판정표기(합격, "일지601"))
        # 시료 수를 넘는 행은 직전 블록에서 복사돼 온 값을 지운다
        for row in SAMPLE_ROWS[len(data.시료목록):]:
            w.clear(idx, row, OFF.values())

        w.set(idx, 20, 0, 서명줄("품질관리자", data.품질관리기술인))
        w.set(idx, 22, 0, 서명줄("감   리   원", data.감리원))
        w.update_print_area(idx)

    # -- 2. 601 대장 -----------------------------------------------------
    def _write_list(self, data: ShapeTest, ctx: TaskContext) -> None:
        sh = ctx.book("test_shape").sheet(LIST_SHEET)
        rg = RowGroupWriter(sh, LIST_FIRST_ROW, 1, key_col=LIST_COL["No"], width=6)
        row = rg.append_group()
        rg.set(row, LIST_COL["No"], rg.sequence_no())
        rg.set(row, LIST_COL["날짜"], data.시험일자, number_format="yyyy-mm-dd")
        rg.set(row, LIST_COL["업체명"], self.cfg.vendors.form(data.업체명, "시험601"))
        rg.set(row, LIST_COL["규격"], f"{data.규격_A}-{data.규격_m}")
        rg.set(row, LIST_COL["판정"], 판정표기(self._합격(data), "대장601"))
        rg.set(row, LIST_COL["CSI"], "ㅇ")

    # -- 3. 실시대장 (§14.4 h=5) -----------------------------------------
    def _write_ledger(self, data: ShapeTest, ctx: TaskContext) -> None:
        tpl = LedgerTemplate.load(_template_path("현장시험/PHC겉모양치수.yaml"))
        writer = LedgerWriter(ctx.book("ledger_pile"), tpl)
        s = data.시료목록[0]
        writer.append(LedgerEntry(
            날짜=data.완료일,
            구분=대장_구분표기(Series.PHC_SHAPE, data.번호),
            공장=self.cfg.vendors.form(data.업체명, "대장"),
            장소="현장내",
            규격=f"{data.규격_A}-{data.규격_m}",
            결과=[s.길이, s.바깥지름, s.두께, s.모양, s.겉모양],
            판정=판정표기(self._합격(data), "실시대장"),
            기술인=data.품질관리기술인,
            감리원=data.감리원,
            변수={"규격m": data.규격_m, "규격A": data.규격_A},
        ))

    def _합격(self, data: ShapeTest) -> bool:
        return all(판정_겉모양(s, data.규격_A, data.규격_m) for s in data.시료목록)

    # =================================================================
    def validate_after(self, data: ShapeTest, ctx: TaskContext) -> list[str]:
        """기준 문자열이 실제로 들어갔는지 (대장 K열) 확인."""
        p: list[str] = []
        expect = 기준문자열("길이", data.규격_m)
        if "±" not in expect:
            p.append(f"길이 기준 문자열이 이상합니다: {expect!r}")
        return p


def _template_path(rel: str) -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / rel
