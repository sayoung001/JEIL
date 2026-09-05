"""시트 추상화.

쓰기 엔진(§13)이 xlwings API를 직접 부르면 Excel 없이는 한 줄도 검증할 수 없다.
그래서 엔진은 ``SheetPort`` 만 알고, 실제 백엔드는 두 가지다.

* ``XlwingsSheet``  — 실제 쓰기 (core/excel_writer.py). Windows + Excel 필요.
* ``MemorySheet``   — 테스트와 [미리보기]. 파일을 건드리지 않는다.

덕분에 "어느 셀에 무엇이 들어가는가" 를 Excel 없이 그대로 재현할 수 있고,
UI의 [미리보기] 도 실행 경로와 같은 코드를 쓴다 (표시용 별도 구현이 아니다).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

Rect = tuple[int, int, int, int]  # (row1, col1, row2, col2) — 1-based, 양끝 포함


# ---------------------------------------------------------------------
# 열 문자 변환
# ---------------------------------------------------------------------
def col_letter(col: int) -> str:
    """1 -> 'A', 27 -> 'AA', 111 -> 'DG'."""
    if col < 1:
        raise ValueError(f"열 번호는 1 이상이어야 합니다: {col}")
    out = ""
    while col:
        col, rem = divmod(col - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def col_index(letter: str) -> int:
    """'DG' -> 111."""
    n = 0
    for ch in letter.strip().upper():
        if not ch.isalpha():
            raise ValueError(f"열 문자가 아닙니다: {letter!r}")
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def a1(row: int, col: int) -> str:
    return f"{col_letter(col)}{row}"


def rect_a1(rect: Rect) -> str:
    r1, c1, r2, c2 = rect
    return f"{a1(r1, c1)}:{a1(r2, c2)}"


# ---------------------------------------------------------------------
# 포트
# ---------------------------------------------------------------------
class SheetPort(ABC):
    """엔진이 시트에 대해 알아야 하는 최소한."""

    name: str

    @abstractmethod
    def read(self, row: int, col: int) -> Any: ...

    @abstractmethod
    def write(self, row: int, col: int, value: Any, *,
              wrap: bool | None = None, number_format: str | None = None) -> None: ...

    @abstractmethod
    def copy_all(self, src: Rect, dst: Rect) -> None:
        """값·서식·병합·테두리 전부 복사 (xlwings Range.Copy(dst))."""

    @abstractmethod
    def copy_formats(self, src: Rect, dst: Rect) -> None:
        """서식만 복사 (PasteSpecial xlPasteFormats)."""

    @abstractmethod
    def merge(self, rect: Rect) -> None: ...

    @abstractmethod
    def unmerge(self, rect: Rect) -> None: ...

    @abstractmethod
    def set_print_area(self, rect: Rect) -> None: ...

    @abstractmethod
    def get_column_width(self, col: int) -> float: ...

    @abstractmethod
    def set_column_width(self, col: int, width: float) -> None: ...

    @abstractmethod
    def insert_rows(self, row: int, count: int) -> None: ...

    # -- 편의 -----------------------------------------------------------
    def read_row(self, row: int, col_from: int, col_to: int) -> list[Any]:
        """한 행을 한 번에 읽는다.

        xlwings 백엔드는 이걸 단일 Range 호출로 처리한다. 셀 단위로 읽으면
        COM 왕복이 수천 번 일어나 블록 스캔만으로 수 초가 걸린다.
        """
        return [self.read(row, c) for c in range(col_from, col_to + 1)]

    def read_col(self, col: int, row_from: int, row_to: int) -> list[Any]:
        return [self.read(r, col) for r in range(row_from, row_to + 1)]

    def clear_values(self, rect: Rect) -> None:
        """값만 비운다. 병합·테두리는 유지 (§10 #4)."""
        r1, c1, r2, c2 = rect
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                self.write(r, c, None)

    def last_filled_row(self, col: int, start: int, chunk: int = 500,
                        max_row: int = 60000) -> int:
        """col 열이 채워진 마지막 행. 하나도 없으면 start - 1.

        빈 칸이 500행 이어지면 끝으로 본다. 중간에 빈 행이 몇 개 있어도
        (병합 때문에 A열이 비는 경우가 있다) 놓치지 않는다.
        """
        last = start - 1
        row = start
        while row <= max_row:
            end = min(row + chunk - 1, max_row)
            values = self.read_col(col, row, end)
            for i, v in enumerate(values):
                if v is not None and str(v).strip() != "":
                    last = row + i
            if last < row:          # 이번 덩어리가 통째로 비었으면 종료
                break
            row = end + 1
        return last


class WorkbookPort(ABC):
    """통합문서."""

    @property
    @abstractmethod
    def sheet_names(self) -> list[str]: ...

    @abstractmethod
    def sheet(self, name: str) -> SheetPort: ...

    @abstractmethod
    def copy_sheet(self, template: str, new_name: str, after: str | None = None) -> SheetPort: ...

    @abstractmethod
    def save(self) -> None: ...

    def has_sheet(self, name: str) -> bool:
        return name in self.sheet_names


# ---------------------------------------------------------------------
# 메모리 구현 — 테스트 / 미리보기
# ---------------------------------------------------------------------
@dataclass
class WriteRecord:
    """[미리보기] 표 한 줄."""

    sheet: str
    cell: str
    value: Any
    kind: str = "value"        # value | formula | format | merge | print_area | sheet

    @property
    def is_formula(self) -> bool:
        return isinstance(self.value, str) and self.value.startswith("=")


@dataclass
class MemorySheet(SheetPort):
    """딕셔너리 기반 시트. 서식은 흉내만 내고 값·병합·인쇄영역은 정확히 재현한다."""

    name: str = "Sheet1"
    cells: dict[tuple[int, int], Any] = field(default_factory=dict)
    merges: set[Rect] = field(default_factory=set)
    print_area: Rect | None = None
    column_widths: dict[int, float] = field(default_factory=dict)
    number_formats: dict[tuple[int, int], str] = field(default_factory=dict)
    wraps: dict[tuple[int, int], bool] = field(default_factory=dict)
    log: list[WriteRecord] = field(default_factory=list)

    # -- 읽기/쓰기 -------------------------------------------------------
    def read(self, row: int, col: int) -> Any:
        return self.cells.get((row, col))

    def write(self, row, col, value, *, wrap=None, number_format=None) -> None:
        if value is None:
            self.cells.pop((row, col), None)
        else:
            self.cells[(row, col)] = value
        if wrap is not None:
            self.wraps[(row, col)] = wrap
        if number_format is not None:
            self.number_formats[(row, col)] = number_format
        kind = "formula" if isinstance(value, str) and value.startswith("=") else "value"
        self.log.append(WriteRecord(self.name, a1(row, col), value, kind))

    def read_row(self, row: int, col_from: int, col_to: int) -> list[Any]:
        return [self.cells.get((row, c)) for c in range(col_from, col_to + 1)]

    def read_col(self, col: int, row_from: int, row_to: int) -> list[Any]:
        return [self.cells.get((r, col)) for r in range(row_from, row_to + 1)]

    # -- 복사 ------------------------------------------------------------
    def _shift(self, src: Rect, dst: Rect) -> tuple[int, int]:
        return dst[0] - src[0], dst[1] - src[1]

    def copy_all(self, src: Rect, dst: Rect) -> None:
        dr, dc = self._shift(src, dst)
        r1, c1, r2, c2 = src
        snapshot = {(r, c): self.cells.get((r, c))
                    for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}
        for (r, c), v in snapshot.items():
            tgt = (r + dr, c + dc)
            if v is None:
                self.cells.pop(tgt, None)
            else:
                self.cells[tgt] = _shift_formula(v, dr, dc)
            if (r, c) in self.number_formats:
                self.number_formats[tgt] = self.number_formats[(r, c)]
            if (r, c) in self.wraps:
                self.wraps[tgt] = self.wraps[(r, c)]
        for m in list(self.merges):
            if _inside(m, src):
                self.merges.add((m[0] + dr, m[1] + dc, m[2] + dr, m[3] + dc))
        self.log.append(WriteRecord(self.name, rect_a1(dst),
                                    f"<- {rect_a1(src)} 전체 복사", "format"))

    def copy_formats(self, src: Rect, dst: Rect) -> None:
        dr, dc = self._shift(src, dst)
        for m in list(self.merges):
            if _inside(m, src):
                self.merges.add((m[0] + dr, m[1] + dc, m[2] + dr, m[3] + dc))
        r1, c1, r2, c2 = src
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                if (r, c) in self.number_formats:
                    self.number_formats[(r + dr, c + dc)] = self.number_formats[(r, c)]
                if (r, c) in self.wraps:
                    self.wraps[(r + dr, c + dc)] = self.wraps[(r, c)]
        self.log.append(WriteRecord(self.name, rect_a1(dst),
                                    f"<- {rect_a1(src)} 서식 복사", "format"))

    # -- 병합 / 인쇄영역 --------------------------------------------------
    def merge(self, rect: Rect) -> None:
        self.merges.add(rect)
        self.log.append(WriteRecord(self.name, rect_a1(rect), "병합", "merge"))

    def unmerge(self, rect: Rect) -> None:
        self.merges.discard(rect)

    def set_print_area(self, rect: Rect) -> None:
        self.print_area = rect
        self.log.append(WriteRecord(self.name, rect_a1(rect), "인쇄영역", "print_area"))

    # -- 열 너비 / 행 삽입 ------------------------------------------------
    def get_column_width(self, col: int) -> float:
        return self.column_widths.get(col, 8.43)

    def set_column_width(self, col: int, width: float) -> None:
        self.column_widths[col] = width

    def insert_rows(self, row: int, count: int) -> None:
        moved: dict[tuple[int, int], Any] = {}
        for (r, c), v in self.cells.items():
            moved[(r + count, c) if r >= row else (r, c)] = v
        self.cells = moved
        self.merges = {
            (m[0] + count, m[1], m[2] + count, m[3]) if m[0] >= row else m
            for m in self.merges
        }


def _inside(inner: Rect, outer: Rect) -> bool:
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def _shift_formula(value: Any, dr: int, dc: int) -> Any:
    """메모리 시트에서 상대참조 수식을 옮길 때 대충 맞춰 준다 (테스트용 근사)."""
    if not (isinstance(value, str) and value.startswith("=")) or (dr == 0 and dc == 0):
        return value
    import re

    def repl(m: "re.Match[str]") -> str:
        col_abs, col_s, row_abs, row_s = m.groups()
        col = col_index(col_s) + (0 if col_abs else dc)
        row = int(row_s) + (0 if row_abs else dr)
        if col < 1 or row < 1:
            return "#REF!"
        return f"{col_abs or ''}{col_letter(col)}{row_abs or ''}{row}"

    return re.sub(r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)", repl, value)


@dataclass
class MemoryWorkbook(WorkbookPort):
    """테스트/미리보기용 통합문서."""

    path: str = "<memory>"
    sheets: dict[str, MemorySheet] = field(default_factory=dict)
    saved: int = 0

    @property
    def sheet_names(self) -> list[str]:
        return list(self.sheets)

    def sheet(self, name: str) -> MemorySheet:
        if name not in self.sheets:
            raise KeyError(f"시트가 없습니다: {name} (있는 시트: {self.sheet_names})")
        return self.sheets[name]

    def add_sheet(self, name: str) -> MemorySheet:
        self.sheets[name] = MemorySheet(name=name)
        return self.sheets[name]

    def copy_sheet(self, template: str, new_name: str, after: str | None = None) -> MemorySheet:
        src = self.sheet(template)
        new = MemorySheet(
            name=new_name,
            cells=dict(src.cells),
            merges=set(src.merges),
            print_area=src.print_area,
            column_widths=dict(src.column_widths),
            number_formats=dict(src.number_formats),
            wraps=dict(src.wraps),
        )
        self.sheets[new_name] = new
        return new

    def save(self) -> None:
        self.saved += 1

    # -- 미리보기 --------------------------------------------------------
    def records(self) -> list[WriteRecord]:
        out: list[WriteRecord] = []
        for sh in self.sheets.values():
            out.extend(sh.log)
        return out


def iter_records(books: Iterable[tuple[str, MemoryWorkbook]]) -> list[tuple[str, WriteRecord]]:
    """[미리보기] 표용 — (파일명, 기록) 목록."""
    out: list[tuple[str, WriteRecord]] = []
    for label, wb in books:
        for rec in wb.records():
            out.append((label, rec))
    return out
