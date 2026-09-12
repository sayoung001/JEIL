"""T-01 자재검수 회차 생성 (SPEC §4, §5) — 1차 핵심.

한 번 실행하면 세 파일이 함께 갱신된다.

1. ``★수불부 체크용.xlsx``   `파일 (2)` — 송장 행 추가 (SSOT)
2. ``자재검수요청서 갑지.xlsx`` `자재검수(PHC)` — 신규 10열 블록 + 인쇄영역 이동
3. ``JQC304-A 자재수불부(PHC파일).xlsx`` `500` — 월 16열 블록에 2행 1건 추가
4. (선택) 사진대지 시트 생성
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from core.context import TaskContext
from core.engines import HorizontalBlockWriter, RowGroupWriter
from core.excel_reader import read_book
from core.models import InspectionRound
from core.numbering import (검수결과_표기, 서명란, 요청서_문서번호, 통보서_문서번호,
                            통보일_문자열)
from core.sheets import col_letter
from core.util import as_date, as_number, has_zip_entry

from .base import Task

log = logging.getLogger(__name__)

# --- ★수불부 체크용 `파일 (2)` (§4.1) --------------------------------
CHECK_SHEET = "파일 (2)"
CHECK_FIRST_ROW = 18
CHECK_COLS = {"송장일자": 1, "반입일자": 2, "업체명": 3, "규격_A": 4, "규격_m": 5,
              "구분": 6, "수량_본": 7, "밴드500": 8, "밴드600": 9, "규격x본": 10,
              "차수": 11, "완미완": 12}

# --- 갑지 `자재검수(PHC)` (§4.2) --------------------------------------
COVER_SHEET = "자재검수(PHC)"
COVER_WIDTH = 10
COVER_ROWS = (1, 20)
COVER_MATERIAL_ROWS = (5, 6, 7, 8)          # 최대 4건
COVER_VALUE_OFFSETS = (0, 1, 3, 4, 5, 6, 7, 8)   # 5~8행에서 비워야 할 자리

# --- 자재수불부 `500` (§4.3) ------------------------------------------
LEDGER_SHEET = "500"
LEDGER_WIDTH = 16
LEDGER_DATA_ROWS = list(range(5, 39, 2))    # 5,7,...,37 → 월당 최대 17건
LEDGER_OFF = {"설계량": 0, "단위": 1, "규격": 2, "길이": 3, "반입일": 4, "반입량": 5,
              "합격_금회": 6, "합격_누계": 7, "불합격": 8, "사유": 9, "출고일": 10,
              "출고량": 11, "잔량": 12, "검수자": 13, "서명": 14, "비고": 15}


def 갑지_블록순번(차수: int) -> int:
    """차수 2 = 블록 1 (A열). 차수 13 = 블록 12 (DG열) — §4.2 실측표."""
    return 차수 - 1


def 수불부_블록순번(기준월: date, 첫달: date) -> int:
    """자재수불부는 월 1블록. 2026-08 = 블록 1 (A), 2026-09 = 블록 2 (Q)."""
    return (기준월.year - 첫달.year) * 12 + (기준월.month - 첫달.month) + 1


class MaterialInspectionTask(Task):
    name = "자재검수 회차 생성"
    workflow_file = "자재검수.yaml"
    _BASE_FILES = ("supply_check", "request_cover", "ledger_phc")

    def __init__(self, cfg, 사진대지: bool = True):
        super().__init__(cfg)
        # 사진대지 시트 생성은 선택 단계다 (§5.1 9번). 양식 파일이 없으면 알아서 빠진다.
        self.사진대지 = 사진대지 and Path(cfg.path("photo_template")).exists()

    @property
    def target_files(self) -> tuple[str, ...]:
        return (*self._BASE_FILES, "photo_template") if self.사진대지 else self._BASE_FILES

    def preview_sheets(self) -> dict[str, list[str]]:
        return {"supply_check": [CHECK_SHEET], "request_cover": [COVER_SHEET],
                "ledger_phc": [LEDGER_SHEET]}

    # =================================================================
    # 사전 검증 (§5.2)
    # =================================================================
    def validate_before(self, data: InspectionRound, ctx: TaskContext) -> list[str]:
        p: list[str] = []
        if not 1 <= len(data.자재목록) <= 4:
            p.append(f"자재 목록은 1~4건이어야 합니다 (갑지가 4행까지만 수용). 현재 {len(data.자재목록)}건")
        if not data.송장목록:
            p.append("송장 목록이 비어 있습니다.")

        # 업체명이 vendor_alias 에 전부 있는가 (§5.2)
        for d in data.송장목록:
            if self.cfg.vendors.canonical(d.업체명) is None:
                p.append(f"vendor_alias 에 없는 업체명입니다: {d.업체명!r} — config.yaml 에 추가하세요")

        # 송장 합계 == 자재 반입수량 합계
        if data.송장목록 and data.송장본합계 != data.반입수량합계:
            p.append(f"송장 합계({data.송장본합계}본)와 자재 반입수량 합계"
                     f"({data.반입수량합계}본)가 다릅니다.")

        # 차수 중복 / 직전 반입일자
        try:
            check = ctx.book("supply_check").sheet(CHECK_SHEET)
            last = check.last_filled_row(CHECK_COLS["송장일자"], CHECK_FIRST_ROW)
            차수들 = [as_number(v) for v in
                     check.read_col(CHECK_COLS["차수"], CHECK_FIRST_ROW, max(last, CHECK_FIRST_ROW))]
            기존 = {int(v) for v in 차수들 if v is not None}
            if data.차수 in 기존:
                p.append(f"{data.차수}차는 ★수불부 체크용 K열에 이미 있습니다.")
            if 기존 and data.차수 != max(기존) + 1:
                p.append(f"차수가 이어지지 않습니다: 마지막 {max(기존)}차 -> 입력 {data.차수}차")
            if last >= CHECK_FIRST_ROW:
                직전 = as_date(check.read(last, CHECK_COLS["송장일자"]))
                if 직전 and data.반입일자 < 직전:
                    p.append(f"반입일자({data.반입일자})가 직전 회차({직전})보다 빠릅니다.")
        except Exception as e:                       # 파일이 없거나 시트명이 다른 경우
            p.append(f"★수불부 체크용을 읽을 수 없습니다: {e}")

        # 갑지에 해당 차수 블록이 이미 있는가
        try:
            cover = ctx.book("request_cover").sheet(COVER_SHEET)
            w = HorizontalBlockWriter(cover, COVER_WIDTH, COVER_ROWS)
            idx = 갑지_블록순번(data.차수)
            if w.get(idx, 2, 2) not in (None, ""):
                p.append(f"갑지에 {data.차수}차 블록({col_letter(w.block_col(idx))}열)이 이미 있습니다.")
            if w.last_block_index() != idx - 1:
                p.append(f"갑지 마지막 블록이 {w.last_block_index()}번인데 "
                         f"{data.차수}차는 {idx}번 자리입니다. 차수를 확인하세요.")
        except Exception as e:
            p.append(f"갑지를 읽을 수 없습니다: {e}")
        return p

    # =================================================================
    # 실행 (§5.1 6~9)
    # =================================================================
    def execute(self, data: InspectionRound, ctx: TaskContext) -> None:
        self._write_check(data, ctx)
        self._write_cover(data, ctx)
        self._write_ledger(data, ctx)
        if self.사진대지:
            self._write_photo_sheet(data, ctx)

    # -- 9. 사진대지 시트 (§4.4) — 반입일 기입까지, 사진 삽입은 수동 ----------
    def _write_photo_sheet(self, data: InspectionRound, ctx: TaskContext) -> None:
        from .photo_sheet import PhotoSheetTask

        PhotoSheetTask(self.cfg).execute(data.반입일자, ctx)

    # -- 6. ★수불부 체크용 (§4.1) ---------------------------------------
    def _write_check(self, data: InspectionRound, ctx: TaskContext) -> None:
        sh = ctx.book("supply_check").sheet(CHECK_SHEET)
        C = CHECK_COLS
        start = sh.last_filled_row(C["송장일자"], CHECK_FIRST_ROW) + 1
        rows = list(range(start, start + len(data.송장목록)))

        for i, (r, d) in enumerate(zip(rows, data.송장목록)):
            # 서식은 바로 윗행에서 복사
            if r - 1 >= CHECK_FIRST_ROW:
                sh.copy_formats((r - 1, 1, r - 1, 12), (r, 1, r, 12))
            sh.write(r, C["송장일자"], d.송장일자, number_format="yyyy-mm-dd")
            # B열은 '=+A{r}' 수식으로 통일한다 (§4.1 규칙 4)
            sh.write(r, C["반입일자"], f"=+A{r}", number_format="yyyy-mm-dd")
            sh.write(r, C["업체명"], self.cfg.vendors.form(d.업체명, "체크용"))
            sh.write(r, C["규격_A"], d.규격_A)
            sh.write(r, C["규격_m"], d.규격_m)
            sh.write(r, C["구분"], d.구분)
            sh.write(r, C["수량_본"], d.수량_본)
            sh.write(r, C["밴드500"], d.밴드500)
            sh.write(r, C["밴드600"], d.밴드600)
            # J열: 이미 수식이 깔려 있으면 덮어쓰지 않는다 (§4.1 규칙 3 — 55·56행)
            if not _is_formula(sh.read(r, C["규격x본"])):
                sh.write(r, C["규격x본"], f"=E{r}*G{r}")
            # K·L열은 회차의 마지막 행에만 (§4.1 규칙 5,6)
            last_of_round = i == len(data.송장목록) - 1
            sh.write(r, C["차수"], data.차수 if last_of_round else None)
            sh.write(r, C["완미완"], "완" if last_of_round else None)

    # -- 7. 갑지 (§4.2) --------------------------------------------------
    def _write_cover(self, data: InspectionRound, ctx: TaskContext) -> None:
        sh = ctx.book("request_cover").sheet(COVER_SHEET)
        w = HorizontalBlockWriter(sh, COVER_WIDTH, COVER_ROWS)
        idx = 갑지_블록순번(data.차수)
        w.clone(idx - 1, idx)                     # 직전 블록을 오른쪽으로 통째 복사

        # --- 요청서 ---
        w.set(idx, 2, 2, 요청서_문서번호(data.차수))
        w.set(idx, 2, 6, data.요청서수신)
        w.set(idx, 3, 2, data.반입일자, number_format="yyyy-mm-dd")   # §10 #12
        w.set(idx, 3, 6, data.공종)

        for row, mat in zip(COVER_MATERIAL_ROWS, data.자재목록):
            F = col_letter(w.block_col(idx) + 5)
            G = col_letter(w.block_col(idx) + 6)
            w.set(idx, row, 0, COVER_MATERIAL_ROWS.index(row) + 1)
            w.set(idx, row, 1, mat.품명)
            w.set(idx, row, 3, mat.규격)
            w.set(idx, row, 4, mat.단위)
            w.set(idx, row, 5, mat.전일수량)
            w.set(idx, row, 6, mat.반입수량)
            w.set(idx, row, 7, f"=+{F}{row}+{G}{row}")      # 누계수량은 수식
            w.set(idx, row, 8, mat.비고, wrap=True)          # 줄바꿈 (§10 #10)
        # 자재 건수를 넘는 행은 값만 비운다. 병합·테두리는 유지 (§10 #4)
        for row in COVER_MATERIAL_ROWS[len(data.자재목록):]:
            w.clear(idx, row, COVER_VALUE_OFFSETS)

        # 합계 행 (수식)
        for off in (5, 6, 7):
            c = col_letter(w.block_col(idx) + off)
            w.set(idx, 9, off, f"=SUM({c}5:{c}8)")
        w.set(idx, 9, 4, data.자재목록[0].단위 if data.자재목록 else "본")

        w.set(idx, 11, 3, data.첨부물)
        w.set(idx, 12, 8, 서명란(data.담당자))
        w.set(idx, 13, 8, 서명란(data.현장대리인))

        # --- 통보서 ---
        w.set(idx, 15, 2, 통보서_문서번호(data.차수, data.통보일자, data.현장약칭, data.자재구분))
        w.set(idx, 15, 6, data.통보서수신)
        w.set(idx, 16, 2, 검수결과_표기(data.검수결과 == "적합"))
        w.set(idx, 16, 6, data.부적합사유)
        w.set(idx, 17, 2, data.특기사항)
        w.set(idx, 18, 9, 통보일_문자열(data.통보일자))
        w.set(idx, 19, 8, 서명란(data.담당감리원))
        w.set(idx, 20, 8, 서명란(data.총괄감리원))

        # 인쇄영역은 항상 최신 블록 (§10 #6)
        w.update_print_area(idx)

    # -- 8. 자재수불부 (§4.3) --------------------------------------------
    def _write_ledger(self, data: InspectionRound, ctx: TaskContext) -> None:
        sh = ctx.book("ledger_phc").sheet(LEDGER_SHEET)
        block, first_row = self._ledger_target_block(sh, data.반입일자)
        c0 = 1 + (block - 1) * LEDGER_WIDTH
        O = LEDGER_OFF

        # 이번 달 블록에서 이미 채워진 마지막 데이터 행
        used = [r for r in LEDGER_DATA_ROWS
                if _nonempty(sh.read(r, c0 + O["반입일"]))]
        next_rows = [r for r in LEDGER_DATA_ROWS if r not in used]
        if len(next_rows) < len(data.송장목록):
            raise ValueError(
                f"{data.반입일자:%Y-%m}월 블록에 남은 자리가 "
                f"{len(next_rows)}건뿐입니다 (필요 {len(data.송장목록)}건). "
                "월당 17건이 상한입니다."
            )

        prev_row = used[-1] if used else None
        prev_col = c0 + O["합격_누계"]
        if prev_row is None:
            # 월이 바뀐 첫 행 → 전월 블록의 마지막 누계를 참조 (§4.3, §10 #3)
            prev_row, prev_col = self._prev_month_total(sh, block)

        for i, d in enumerate(data.송장목록):
            r = next_rows[i]
            if r != LEDGER_DATA_ROWS[0]:
                src = r - 2
                sh.copy_formats((src, c0, src + 1, c0 + LEDGER_WIDTH - 1),
                                (r, c0, r + 1, c0 + LEDGER_WIDTH - 1))
            D = col_letter(c0 + O["길이"])
            E = col_letter(c0 + O["반입일"])
            F = col_letter(c0 + O["반입량"])
            G = col_letter(c0 + O["합격_금회"])
            H = col_letter(c0 + O["합격_누계"])

            sh.write(r, c0 + O["설계량"], "-" if (block == 1 and r == LEDGER_DATA_ROWS[0]) else None)
            sh.write(r, c0 + O["단위"], "m")
            sh.write(r, c0 + O["규격"], f"A{d.규격_A}")
            sh.write(r, c0 + O["길이"], d.규격_m)
            sh.write(r, c0 + O["반입일"], d.반입일자, number_format="yyyy-mm-dd")
            sh.write(r, c0 + O["반입량"], d.수량_본)
            sh.write(r, c0 + O["합격_금회"], f"={D}{r}*{F}{r}")
            # 누계 체인 — 직전 데이터 행을 실제로 찾아 참조를 만든다 (§10 #2)
            sh.write(r, c0 + O["합격_누계"],
                     f"=+{col_letter(prev_col)}{prev_row}+{G}{r}")
            sh.write(r, c0 + O["출고일"], f"=+{E}{r}")
            sh.write(r, c0 + O["출고량"], f"={G}{r}")
            sh.write(r, c0 + O["비고"], self.cfg.vendors.form(d.업체명, "수불부"))
            prev_row, prev_col = r, c0 + O["합격_누계"]

    def _ledger_target_block(self, sh: Any, when: date) -> tuple[int, int]:
        """반입일자의 월 블록을 찾는다. 없으면 직전 월 블록을 복제해 만든다 (§10 #3)."""
        want = f"{when:%y}년 {when:%m}월"
        for n in range(1, 200):
            c0 = 1 + (n - 1) * LEDGER_WIDTH
            title = sh.read(1, c0)
            if title is None or str(title).strip() == "":
                # 빈 자리 → 직전 블록을 복제해 새 월 블록을 만든다
                if n == 1:
                    raise ValueError("자재수불부 `500` 시트가 비어 있습니다. 원본을 확인하세요.")
                prev_c0 = c0 - LEDGER_WIDTH
                sh.copy_all((1, prev_c0, 38, prev_c0 + LEDGER_WIDTH - 1),
                            (1, c0, 38, c0 + LEDGER_WIDTH - 1))
                for i in range(LEDGER_WIDTH):
                    sh.set_column_width(c0 + i, sh.get_column_width(prev_c0 + i))
                sh.write(1, c0, f"주요자재 검사 및 수불부 ({when:%y}년 {when:%m}월)")
                for r in LEDGER_DATA_ROWS:      # 복사돼 온 데이터는 비운다
                    for off in range(LEDGER_WIDTH):
                        if off != LEDGER_OFF["단위"]:
                            sh.write(r, c0 + off, None)
                        sh.write(r + 1, c0 + off, None)
                return n, LEDGER_DATA_ROWS[0]
            if want in str(title).replace("  ", " "):
                return n, LEDGER_DATA_ROWS[0]
        raise ValueError(f"자재수불부에서 {want} 블록을 찾지 못했습니다.")

    def _prev_month_total(self, sh: Any, block: int) -> tuple[int, int]:
        """전월 블록의 마지막 누계 셀 (행, 열). 첫 블록이면 자기 자신을 가리키지 않는다."""
        if block <= 1:
            return LEDGER_DATA_ROWS[0], 1 + LEDGER_OFF["합격_누계"]
        pc0 = 1 + (block - 2) * LEDGER_WIDTH
        used = [r for r in LEDGER_DATA_ROWS if _nonempty(sh.read(r, pc0 + LEDGER_OFF["반입일"]))]
        last = used[-1] if used else LEDGER_DATA_ROWS[0]
        return last, pc0 + LEDGER_OFF["합격_누계"]

    # =================================================================
    # 사후 검증 (§5.3) — 저장된 파일을 다시 읽어 계산값 확인
    # =================================================================
    def verify_files(self, data: InspectionRound) -> list[str]:
        p: list[str] = []
        try:
            cover = read_book(self.cfg.path("request_cover"), data_only=True,
                              only=[COVER_SHEET]).sheet(COVER_SHEET)
            c0 = 1 + (갑지_블록순번(data.차수) - 1) * COVER_WIDTH
            반입합 = as_number(cover.cell(9, c0 + 6))
            if 반입합 is not None and int(반입합) != data.반입수량합계:
                p.append(f"갑지 합계 반입수량이 {반입합} 인데 입력은 {data.반입수량합계} 입니다.")
            누계합 = as_number(cover.cell(9, c0 + 7))
            전일합 = as_number(cover.cell(9, c0 + 5)) or 0
            if 누계합 is not None and 반입합 is not None and 누계합 != 전일합 + 반입합:
                p.append(f"갑지 누계({누계합}) != 전일({전일합}) + 반입({반입합})")
        except Exception as e:
            p.append(f"갑지 사후 검증을 못 했습니다: {e}")

        try:
            check = read_book(self.cfg.path("supply_check"), data_only=True,
                              only=[CHECK_SHEET]).sheet(CHECK_SHEET)
            last = check.last_filled_row(CHECK_COLS["송장일자"], CHECK_FIRST_ROW)
            for r in range(last - len(data.송장목록) + 1, last + 1):
                m = as_number(check.cell(r, CHECK_COLS["규격_m"]))
                b = as_number(check.cell(r, CHECK_COLS["수량_본"]))
                j = as_number(check.cell(r, CHECK_COLS["규격x본"]))
                if None not in (m, b, j) and abs(j - m * b) > 0.001:
                    p.append(f"★수불부 체크용 J{r} = {j} 인데 규격×본 = {m * b} 입니다.")
        except Exception as e:
            p.append(f"★수불부 체크용 사후 검증을 못 했습니다: {e}")

        # 도형 유실 감시 (§5.3 마지막 항목)
        if not has_zip_entry(self.cfg.path("ledger_phc"), "xl/media/image1.emf"):
            p.append("자재수불부에서 xl/media/image1.emf 가 사라졌습니다 — 도형 유실 의심. "
                     "openpyxl 로 저장된 경로가 없는지 확인하세요.")
        return p


def _is_formula(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("=")


def _nonempty(v: Any) -> bool:
    return v is not None and str(v).strip() != ""
