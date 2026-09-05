"""T-05 BSCW / JSP 압축강도 (Q-Q-03 / Q-Q-04) — SPEC §18. **2단계 태스크.**

7일과 28일 사이가 3주다. 그 사이를 ``state.json`` 이 추적한다.

    [NEW]  채취 등록  -> 일지 블록 생성(4~6행) + 시험목록 타설일     -> AWAIT_7D
    [7D]   7일 강도   -> 일지 11~13행 + 시험목록 C열(평균)           -> AWAIT_28D
    [28D]  28일 강도  -> 일지 18~20행 + 목록 D열 + **실시대장 기록**  -> DONE

대장에 기록되는 것은 28일 단계뿐이고, 날짜는 **채취일+28** 이다 (§15.2).
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.context import TaskContext
from core.engines import HorizontalBlockWriter
from core.ledger import LedgerEntry, LedgerTemplate, LedgerWriter
from core.models import CompressiveTest, CompStage, Series
from core.numbering import (TEST_SERIES, 대장_구분표기, 서명줄, 시험번호, 판정표기,
                            parse_시험번호)

from .base import Task

log = logging.getLogger(__name__)

LIST_SHEET = "시험목록"
BLOCK_WIDTH = 11
BLOCK_ROWS = (1, 26)
LIST_FIRST_ROW = 4

# 일지 블록 offset (§14.3)
ROW_7D = (11, 12, 13)
ROW_28D = (18, 19, 20)
OFF = {"제목": 1, "라벨": 0, "값": 2, "라벨2": 6, "값2": 8,
       "시험횟수": 0, "측정값": 3, "평균": 6, "판정": 9}

# 시험목록 열: BSCW 는 A~D, JSP 는 E~H (§14.3)
LIST_COLS = {Series.BSCW: {"번호": 1, "타설일": 2, "강도7": 3, "강도28": 4},
             Series.JSP:  {"번호": 5, "타설일": 6, "강도7": 7, "강도28": 8}}


class CompressiveTask(Task):
    """BSCW 와 JSP 를 같은 코드로 처리한다. 다른 것은 시트·계열·목록 열뿐 (§18.4)."""

    workflow_file = "압축강도.yaml"
    target_files = ("test_bscw_jsp", "ledger_civil")

    def __init__(self, cfg, series: Series = Series.BSCW):
        super().__init__(cfg)
        if series not in (Series.BSCW, Series.JSP):
            raise ValueError(f"BSCW 또는 JSP 만 가능합니다: {series}")
        self.series = series
        self.name = f"{series.value} 압축강도 시험"

    @property
    def journal_sheet(self) -> str:
        return TEST_SERIES[self.series]["sheet"]

    @property
    def list_cols(self) -> dict[str, int]:
        return LIST_COLS[self.series]

    def preview_sheets(self) -> dict[str, list[str]]:
        return {"test_bscw_jsp": [self.journal_sheet, LIST_SHEET]}

    # =================================================================
    def next_number(self, ctx: TaskContext) -> int:
        sh = ctx.book("test_bscw_jsp").sheet(self.journal_sheet)
        w = HorizontalBlockWriter(sh, BLOCK_WIDTH, BLOCK_ROWS)
        last = w.last_block_index()
        if last == 0:
            return 1
        parsed = parse_시험번호(w.get(last, 5, OFF["값"]))
        return (parsed[1] + 1) if parsed else last + 1

    # =================================================================
    def validate_before(self, data: CompressiveTest, ctx: TaskContext) -> list[str]:
        p: list[str] = []
        if data.series is not self.series:
            p.append(f"태스크는 {self.series.value} 인데 데이터는 {data.series.value} 입니다.")
        if data.stage is CompStage.AWAIT_28D and len(data.측정_7일) != 3:
            p.append("7일 측정값 3개가 있어야 28일 단계로 갈 수 있습니다.")
        stage = data.stage
        if stage is CompStage.AWAIT_7D and len(data.측정_7일) != 3:
            p.append(f"7일 측정값이 3개여야 합니다 (현재 {len(data.측정_7일)}개).")
        if stage is CompStage.AWAIT_28D and len(data.측정_28일) != 3:
            p.append(f"28일 측정값이 3개여야 합니다 (현재 {len(data.측정_28일)}개).")
        if data.목록행번호 and not 1 <= data.목록행번호 <= 36:
            p.append(f"시험목록 번호는 1~36 입니다: {data.목록행번호}")
        return p

    # =================================================================
    def execute(self, data: CompressiveTest, ctx: TaskContext) -> None:
        """``data.stage`` 가 '지금 무엇을 입력하는가' 를 뜻한다."""
        if data.stage is CompStage.NEW:
            self._register(data, ctx)
        elif data.stage is CompStage.AWAIT_7D:
            self._write_7d(data, ctx)
        elif data.stage is CompStage.AWAIT_28D:
            self._write_28d(data, ctx)
        else:
            raise ValueError(f"이미 끝난 시험입니다: {data.stage}")

    # -- [NEW] 채취 등록 --------------------------------------------------
    def _register(self, data: CompressiveTest, ctx: TaskContext) -> None:
        sh = ctx.book("test_bscw_jsp").sheet(self.journal_sheet)
        w = HorizontalBlockWriter(sh, BLOCK_WIDTH, BLOCK_ROWS)
        idx = w.clone_last()

        title = "BSCW 압축강도 시험일지   " if self.series is Series.BSCW \
            else "JSP 압축강도 시험일지   "
        w.set(idx, 1, OFF["제목"], title)
        w.set(idx, 4, OFF["값"], data.공종)                     # ' 흙막이(JSP)' (§18.4)
        w.set(idx, 4, OFF["값2"], data.채취일, number_format="yyyy-mm-dd")
        w.set(idx, 5, OFF["값"], 시험번호(self.series, data.번호))
        w.set(idx, 5, OFF["값2"], f" {data.채취장소}")
        w.set(idx, 6, OFF["값"], f" {data.시공업체}")

        # 날짜 체인: 7일 = 채취일+7, 28일 = 7일날짜+21 (§14.3)
        채취일셀 = w.cell_ref(idx, 4, OFF["값2"])
        일자7셀 = w.cell_ref(idx, 9, OFF["판정"])
        w.set(idx, 9, OFF["판정"], f"={채취일셀}+7", number_format="yyyy-mm-dd")
        w.set(idx, 16, OFF["판정"], f"={일자7셀}+21", number_format="yyyy-mm-dd")

        # 평균 수식은 측정값을 넣기 전에 미리 깔아 둔다
        for base in (ROW_7D[0], ROW_28D[0]):
            D = w.cell_ref(idx, base, OFF["측정값"])[:-len(str(base))]
            w.set(idx, base, OFF["평균"],
                  f"=({D}{base}+{D}{base + 1}+{D}{base + 2})/3")
        w.set(idx, ROW_7D[0], OFF["판정"], "-")     # 7일은 판정 없음

        # 측정값 자리는 직전 블록에서 복사돼 온 값을 비운다
        for row in (*ROW_7D, *ROW_28D):
            w.set(idx, row, OFF["측정값"], None)
        w.set(idx, ROW_28D[0], OFF["판정"], None)

        w.set(idx, 25, 0, 서명줄("품질관리자", data.품질관리기술인))
        w.set(idx, 26, 0, 서명줄("감   리   원", data.감리원))
        w.update_print_area(idx)

        # 시험목록 타설일
        lst = ctx.book("test_bscw_jsp").sheet(LIST_SHEET)
        row = LIST_FIRST_ROW + data.목록행번호 - 1
        lst.write(row, self.list_cols["타설일"], data.채취일, number_format="yyyy-mm-dd")

    # -- [7D] -------------------------------------------------------------
    def _write_7d(self, data: CompressiveTest, ctx: TaskContext) -> None:
        idx = self._find_block(data, ctx)
        sh = ctx.book("test_bscw_jsp").sheet(self.journal_sheet)
        w = HorizontalBlockWriter(sh, BLOCK_WIDTH, BLOCK_ROWS)
        for row, v in zip(ROW_7D, data.측정_7일):
            w.set(idx, row, OFF["측정값"], v)
        lst = ctx.book("test_bscw_jsp").sheet(LIST_SHEET)
        lst.write(LIST_FIRST_ROW + data.목록행번호 - 1,
                  self.list_cols["강도7"], data.평균_7일)

    # -- [28D] — 여기서 대장에 기록된다 -------------------------------------
    def _write_28d(self, data: CompressiveTest, ctx: TaskContext) -> None:
        idx = self._find_block(data, ctx)
        sh = ctx.book("test_bscw_jsp").sheet(self.journal_sheet)
        w = HorizontalBlockWriter(sh, BLOCK_WIDTH, BLOCK_ROWS)
        for row, v in zip(ROW_28D, data.측정_28일):
            w.set(idx, row, OFF["측정값"], v)
        합격 = bool(data.합격)
        w.set(idx, ROW_28D[0], OFF["판정"], 판정표기(합격, "일지613"))

        lst = ctx.book("test_bscw_jsp").sheet(LIST_SHEET)
        lst.write(LIST_FIRST_ROW + data.목록행번호 - 1,
                  self.list_cols["강도28"], data.평균_28일)

        tpl = LedgerTemplate.load(
            Path(__file__).resolve().parent.parent / "templates" / "현장시험" / "압축강도.yaml")
        writer = LedgerWriter(ctx.book("ledger_civil"), tpl)
        writer.append(LedgerEntry(
            날짜=data.완료일,                      # 채취일 + 28 (§15.2)
            구분=대장_구분표기(self.series, data.번호),
            대상재료=f"{self.series.value} 압축강도",
            공장=data.시공업체,
            장소="현장내",
            규격="-",
            결과=[data.평균_7일, data.평균_28일],
            판정=판정표기(합격, "실시대장"),
            기술인=data.품질관리기술인,
            감리원=data.감리원,
        ))

    # -- 공통 -------------------------------------------------------------
    def _find_block(self, data: CompressiveTest, ctx: TaskContext) -> int:
        """시험번호로 일지 블록을 찾는다. 없으면 명확히 실패시킨다."""
        sh = ctx.book("test_bscw_jsp").sheet(self.journal_sheet)
        w = HorizontalBlockWriter(sh, BLOCK_WIDTH, BLOCK_ROWS)
        want = 시험번호(self.series, data.번호)
        for n in range(1, w.last_block_index() + 1):
            if str(w.get(n, 5, OFF["값"]) or "").strip() == want:
                return n
        raise ValueError(
            f"{self.journal_sheet} 에서 {want} 블록을 찾지 못했습니다. "
            "채취 등록([NEW])이 먼저 끝나야 합니다."
        )
