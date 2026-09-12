"""상시 정합성 검사기 (SPEC §21.3).

§21.1 에서 잡은 것과 같은 어긋남을 앞으로도 계속 잡는다.
**읽기 전용이다.** 고치지 않고 보고만 한다 — [고치기] 는 사람이 누른다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .config import Config
from .excel_reader import ReadBook, ReaderError, read_book
from .ledger import COL, FIRST_DATA_ROW
from .models import Series
from .numbering import TEST_SERIES, parse_시험번호, series_of
from .util import as_date, as_number

log = logging.getLogger(__name__)

TOLERANCE = 0.005          # 평균값 3자 대조 허용 오차 (§21.3)


@dataclass
class Finding:
    """검사 결과 한 줄."""

    수준: str            # 'error' | 'warn'
    파일: str
    위치: str
    내용: str
    고칠수있음: bool = False
    제안값: Any = None

    def __str__(self) -> str:
        icon = "🔴" if self.수준 == "error" else "🟡"
        tail = f"  -> {self.제안값!r} 로 고칠 수 있음" if self.고칠수있음 else ""
        return f"{icon} [{self.파일} {self.위치}] {self.내용}{tail}"


class ConsistencyChecker:
    def __init__(self, cfg: Config, state: Any = None):
        self.cfg = cfg
        self.state = state

    # =================================================================
    def check_all(self, 기준일: date | None = None) -> list[Finding]:
        기준일 = 기준일 or date.today()
        out: list[Finding] = []
        out += self._check_series_continuity()
        out += self._check_journal_vs_ledger()
        out += self._check_average_agreement()
        out += self._check_ledger_sequence()
        out += self._check_ledger_dates()
        out += self._check_verdicts()
        out += self._check_pending_overdue(기준일)
        return out

    # -- 시험번호 연속성 --------------------------------------------------
    def _check_series_continuity(self) -> list[Finding]:
        out: list[Finding] = []
        for series, sheet, width, row, off in (
            (Series.PHC_SHAPE, "일지", 12, 3, 3),
            (Series.BSCW, "BSCW_압축강도_시험일지", 11, 5, 2),
            (Series.JSP, "JSP_압축강도_시험일지", 11, 5, 2),
        ):
            key = TEST_SERIES[series]["journal"]
            try:
                book = read_book(self.cfg.path(key), only=[sheet])
                sh = book.sheet(sheet)
            except (ReaderError, KeyError) as e:
                out.append(Finding("warn", key, sheet, f"읽지 못했습니다: {e}"))
                continue
            numbers: list[tuple[int, int]] = []           # (블록순번, 번호)
            for n in range(1, 200):
                c0 = 1 + (n - 1) * width
                if c0 > sh.ncols:
                    break
                parsed = parse_시험번호(sh.cell(row, c0 + off))
                if parsed is None:
                    continue
                found = series_of(sh.cell(row, c0 + off))
                if found is not series:
                    out.append(Finding(
                        "error", key, f"{sheet} 블록{n}",
                        f"{series.value} 일지에 {found.value if found else '?'} 계열 "
                        f"시험번호가 있습니다: {sh.cell(row, c0 + off)!r}",
                        고칠수있음=found is not None,
                        제안값=f"{TEST_SERIES[series]['prefix']}{parsed[1]:02d}"))
                numbers.append((n, parsed[1]))
            seen: dict[int, int] = {}
            for n, num in numbers:
                if num in seen:
                    out.append(Finding("error", key, f"{sheet} 블록{n}",
                                       f"시험번호 {num} 이(가) 블록 {seen[num]} 과 중복됩니다"))
                seen[num] = n
            if numbers:
                expect = set(range(1, max(v for _, v in numbers) + 1))
                missing = sorted(expect - {v for _, v in numbers})
                if missing:
                    out.append(Finding("warn", key, sheet,
                                       f"빠진 시험번호: {missing}"))
        return out

    # -- 일지 시험번호 <-> 대장 C열 ----------------------------------------
    def _check_journal_vs_ledger(self) -> list[Finding]:
        out: list[Finding] = []
        for series in (Series.PHC_SHAPE, Series.PHC_MILK, Series.BSCW, Series.JSP):
            ledger_key = TEST_SERIES[series]["ledger"]
            prefix = TEST_SERIES[series]["prefix"]
            try:
                book = read_book(self.cfg.path(ledger_key))
            except ReaderError as e:
                out.append(Finding("warn", ledger_key, "-", f"읽지 못했습니다: {e}"))
                continue
            for name, sh in book.sheets.items():
                if not _is_month_sheet(name):
                    continue
                for r in range(FIRST_DATA_ROW, sh.nrows + 1):
                    parsed = parse_시험번호(sh.cell(r, COL["구분"]))
                    if parsed and parsed[0] == prefix and parsed[1] < 1:
                        out.append(Finding("error", ledger_key, f"{name}!C{r}",
                                           f"시험번호가 이상합니다: {sh.cell(r, COL['구분'])!r}"))
        return out

    # -- 일지 평균 <-> 목록표 <-> 실시대장 L열 (3자 일치) --------------------
    def _check_average_agreement(self) -> list[Finding]:
        out: list[Finding] = []
        try:
            book = read_book(self.cfg.path("test_bscw_jsp"), data_only=True)
        except ReaderError as e:
            return [Finding("warn", "test_bscw_jsp", "-", f"읽지 못했습니다: {e}")]
        try:
            목록 = book.sheet("시험목록")
        except ReaderError:
            return out

        cols = {Series.BSCW: (1, 2, 3, 4), Series.JSP: (5, 6, 7, 8)}
        for series, (c번호, c타설, c7, c28) in cols.items():
            sheet_name = TEST_SERIES[series]["sheet"]
            if sheet_name not in book.sheets:
                continue
            일지 = book.sheet(sheet_name)
            블록: dict[int, tuple[float | None, float | None]] = {}
            for n in range(1, 60):
                c0 = 1 + (n - 1) * 11
                if c0 > 일지.ncols:
                    break
                parsed = parse_시험번호(일지.cell(5, c0 + 2))
                if not parsed:
                    continue
                블록[parsed[1]] = (as_number(일지.cell(11, c0 + 6)),
                                  as_number(일지.cell(18, c0 + 6)))
            for r in range(FIRST_DATA_ROW, 목록.nrows + 1):
                번호 = as_number(목록.cell(r, c번호))
                if 번호 is None:
                    continue
                목록7, 목록28 = as_number(목록.cell(r, c7)), as_number(목록.cell(r, c28))
                일지7, 일지28 = 블록.get(int(번호), (None, None))
                for 단계, a, b in (("7일", 일지7, 목록7), ("28일", 일지28, 목록28)):
                    if a is not None and b is not None and abs(a - b) > TOLERANCE:
                        out.append(Finding(
                            "error", "613", f"시험목록!{_L(c7 if 단계 == '7일' else c28)}{r}",
                            f"{series.value} {int(번호)}번 {단계} 평균이 일지({a})와 "
                            f"목록({b})에서 다릅니다",
                            고칠수있음=True, 제안값=round(a, 2)))
        return out

    # -- 대장 A열 일련번호가 월별로 1부터 연속인가 --------------------------
    def _check_ledger_sequence(self) -> list[Finding]:
        out: list[Finding] = []
        for key in ("ledger_pile", "ledger_civil", "ledger_outsrc"):
            try:
                book = read_book(self.cfg.path(key))
            except ReaderError as e:
                out.append(Finding("warn", key, "-", f"읽지 못했습니다: {e}"))
                continue
            for name, sh in book.sheets.items():
                if not _is_month_sheet(name):
                    continue
                seen: list[tuple[int, int]] = []
                for r in range(FIRST_DATA_ROW, sh.nrows + 1):
                    v = as_number(sh.cell(r, COL["일련번호"]))
                    if v is not None:
                        seen.append((r, int(v)))
                for i, (r, v) in enumerate(seen, start=1):
                    if v != i:
                        out.append(Finding(
                            "error", key, f"{name}!A{r}",
                            f"일련번호가 {v} 인데 {i} 여야 합니다 (월별로 1부터 연속)",
                            고칠수있음=True, 제안값=i))
        return out

    # -- 대장 B열 날짜가 완료일 규칙에 맞는가 (§15.2) ------------------------
    def _check_ledger_dates(self) -> list[Finding]:
        out: list[Finding] = []
        try:
            book = read_book(self.cfg.path("ledger_civil"))
        except ReaderError as e:
            return [Finding("warn", "ledger_civil", "-", f"읽지 못했습니다: {e}")]
        타설일 = self._pour_dates()
        for name, sh in book.sheets.items():
            if not _is_month_sheet(name):
                continue
            for r in range(FIRST_DATA_ROW, sh.nrows + 1):
                parsed = parse_시험번호(sh.cell(r, COL["구분"]))
                날짜 = as_date(sh.cell(r, COL["날짜"]))
                if not parsed or 날짜 is None:
                    continue
                series = series_of(sh.cell(r, COL["구분"]))
                if series not in (Series.BSCW, Series.JSP):
                    continue
                pour = 타설일.get((series, parsed[1]))
                if pour is None:
                    continue
                expect = pour + timedelta(days=28)
                if 날짜 != expect:
                    out.append(Finding(
                        "error", "ledger_civil", f"{name}!B{r}",
                        f"{series.value} {parsed[1]}번 날짜가 {날짜} 인데 "
                        f"채취일({pour})+28 = {expect} 여야 합니다 (§15.2)",
                        고칠수있음=True, 제안값=expect))
                if f"{expect:%y}.{expect:%m}" != name:
                    out.append(Finding(
                        "warn", "ledger_civil", f"{name}!A{r}",
                        f"28일 강도일({expect})은 `{expect:%y}.{expect:%m}` 시트에 있어야 합니다"))
        return out

    def _pour_dates(self) -> dict[tuple[Series, int], date]:
        try:
            목록 = read_book(self.cfg.path("test_bscw_jsp"),
                            only=["시험목록"]).sheet("시험목록")
        except (ReaderError, KeyError):
            return {}
        out: dict[tuple[Series, int], date] = {}
        for series, (c번호, c타설) in ((Series.BSCW, (1, 2)), (Series.JSP, (5, 6))):
            for r in range(FIRST_DATA_ROW, 목록.nrows + 1):
                번호, 타설 = as_number(목록.cell(r, c번호)), as_date(목록.cell(r, c타설))
                if 번호 is not None and 타설 is not None:
                    out[(series, int(번호))] = 타설
        return out

    # -- 판정과 측정값이 모순되지 않는가 -----------------------------------
    def _check_verdicts(self) -> list[Finding]:
        out: list[Finding] = []
        기준 = float(self.cfg.get("test_rules.compressive.criterion_mpa", 1.5))
        for key in ("ledger_civil", "ledger_pile"):
            try:
                book = read_book(self.cfg.path(key))
            except ReaderError:
                continue
            for name, sh in book.sheets.items():
                if not _is_month_sheet(name):
                    continue
                for r in range(FIRST_DATA_ROW, sh.nrows + 1):
                    결과 = as_number(sh.cell(r, COL["결과"]))
                    기준문구 = str(sh.cell(r, COL["기준"]) or "")
                    판정 = str(sh.cell(r, COL["판정"]) or "").replace(" ", "")
                    if 결과 is None or not 판정:
                        continue
                    if "이상" in 기준문구:
                        한계 = as_number(기준문구.split("이상")[0]) or 기준
                        if 결과 < 한계 and 판정.startswith("합격"):
                            out.append(Finding(
                                "error", key, f"{name}!L{r}",
                                f"결과 {결과} 가 기준({기준문구})에 못 미치는데 판정이 '합격' 입니다"))
                    elif "이하" in 기준문구:
                        한계 = as_number(기준문구.split("이하")[0])
                        if 한계 is not None and 결과 > 한계 and 판정.startswith("합격"):
                            out.append(Finding(
                                "error", key, f"{name}!L{r}",
                                f"결과 {결과} 가 기준({기준문구})을 넘는데 판정이 '합격' 입니다"))
        return out

    # -- 진행 중 BSCW/JSP 예정일 초과 --------------------------------------
    def _check_pending_overdue(self, 기준일: date) -> list[Finding]:
        if self.state is None:
            return []
        out = []
        for p in self.state.pending:
            지연 = p.지연일수(기준일)
            if 지연 > 0:
                out.append(Finding("error", "state.json", p.시험번호,
                                   f"{p.stage} 예정일({p.예정일()})이 {지연}일 지났습니다"))
        return out


def _is_month_sheet(name: str) -> bool:
    """'26.08' 같은 월 시트인가."""
    parts = name.split(".")
    return len(parts) == 2 and all(p.isdigit() for p in parts)


def _L(col: int) -> str:
    from .sheets import col_letter

    return col_letter(col)
