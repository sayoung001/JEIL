"""공통 쓰기 엔진 3종 (SPEC §13).

품질 폴더의 모든 엑셀은 이 세 패턴 중 하나다.
새 시험·문서가 추가돼도 엔진 조합으로 끝나야 한다 — 파일마다 새 코드를 쓰지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .sheets import Rect, SheetPort, WorkbookPort, col_letter


# =====================================================================
# 13.1 HorizontalBlockWriter — 가로 블록형
# =====================================================================
class HorizontalBlockWriter:
    """회차 1개 = 고정 폭 열 블록. 직전 블록을 오른쪽으로 복사하고 값만 교체.

    인쇄영역은 항상 최신 블록이다 (§10 #6).

    ==========================  ======  =========  ==========
    파일                        폭      행 범위    시트
    ==========================  ======  =========  ==========
    자재검수요청서 갑지          10      1~20       자재검수(PHC)
    601 PHC 겉모양·치수          12      1~23       일지
    613 BSCW / JSP 압축강도      11      1~26       ..._시험일지
    ==========================  ======  =========  ==========
    """

    def __init__(self, sheet: SheetPort, width: int, row_span: tuple[int, int],
                 first_col: int = 1, title_row: int | None = None):
        self.sheet = sheet
        self.width = width
        self.row_from, self.row_to = row_span
        self.first_col = first_col
        # 블록이 존재하는지 판정할 행. 기본은 블록의 첫 행(제목행).
        self.title_row = title_row if title_row is not None else self.row_from

    # -- 좌표 -----------------------------------------------------------
    def block_col(self, n: int) -> int:
        """n = 1-based 블록 순번 -> 블록 시작 열."""
        if n < 1:
            raise ValueError(f"블록 순번은 1 이상이어야 합니다: {n}")
        return self.first_col + (n - 1) * self.width

    def block_index_of(self, col: int) -> int:
        return (col - self.first_col) // self.width + 1

    def block_rect(self, n: int) -> Rect:
        c0 = self.block_col(n)
        return (self.row_from, c0, self.row_to, c0 + self.width - 1)

    # -- 탐색 -----------------------------------------------------------
    def last_block_index(self, probe_rows: Iterable[int] | None = None,
                         max_blocks: int = 400) -> int:
        """내용이 있는 마지막 블록 순번. 하나도 없으면 0.

        제목행만 보면 병합 때문에 놓치는 경우가 있어 블록 앞부분 몇 행을 함께 훑는다.
        중간에 빈 블록이 있어도 건너뛰고 끝까지 본다 — 조기 종료하면
        블록을 덮어쓰는 사고가 난다. 행 단위 일괄 읽기라 COM 왕복은 행 수만큼뿐이다.
        """
        rows = list(probe_rows) if probe_rows else [
            r for r in range(self.row_from, min(self.row_from + 6, self.row_to + 1))
        ]
        last_col = self.first_col + max_blocks * self.width - 1
        last = 0
        for r in rows:
            values = self.sheet.read_row(r, self.first_col, last_col)
            for i, v in enumerate(values):
                if _nonempty(v):
                    last = max(last, self.block_index_of(self.first_col + i))
        return last

    # -- 생성 -----------------------------------------------------------
    def clone_last(self) -> int:
        """직전 블록을 오른쪽에 복사해 새 블록을 만든다. 새 블록 순번을 돌려준다."""
        prev = self.last_block_index()
        if prev == 0:
            raise ValueError("복사할 직전 블록이 없습니다. 최소 1개 블록이 필요합니다.")
        return self.clone(prev, prev + 1)

    def clone(self, src_idx: int, dst_idx: int) -> int:
        src, dst = self.block_rect(src_idx), self.block_rect(dst_idx)
        self.sheet.copy_all(src, dst)
        # 열 너비도 복사 (§4.2)
        src_c0, dst_c0 = self.block_col(src_idx), self.block_col(dst_idx)
        for i in range(self.width):
            self.sheet.set_column_width(dst_c0 + i, self.sheet.get_column_width(src_c0 + i))
        return dst_idx

    # -- 쓰기 -----------------------------------------------------------
    def set(self, block_idx: int, row: int, off: int, value: Any, *,
            wrap: bool | None = None, number_format: str | None = None) -> None:
        """블록 내부 좌표(행, offset 0-based)로 쓴다."""
        if not (0 <= off < self.width):
            raise ValueError(f"offset 이 블록 폭({self.width})을 벗어납니다: {off}")
        if not (self.row_from <= row <= self.row_to):
            raise ValueError(f"행이 블록 범위({self.row_from}~{self.row_to})를 벗어납니다: {row}")
        self.sheet.write(row, self.block_col(block_idx) + off, value,
                         wrap=wrap, number_format=number_format)

    def get(self, block_idx: int, row: int, off: int) -> Any:
        return self.sheet.read(row, self.block_col(block_idx) + off)

    def clear(self, block_idx: int, row: int, offs: Iterable[int]) -> None:
        """값만 비운다 (병합·테두리 유지). 갑지 5~8행 잔재 제거용 — §10 #4."""
        for off in offs:
            self.set(block_idx, row, off, None)

    def cell_ref(self, block_idx: int, row: int, off: int) -> str:
        """같은 블록 안을 가리키는 수식용 셀 주소 ('DL5')."""
        return f"{col_letter(self.block_col(block_idx) + off)}{row}"

    def update_print_area(self, block_idx: int) -> None:
        self.sheet.set_print_area(self.block_rect(block_idx))


# =====================================================================
# 13.2 SheetCloneWriter — 시트 복제형
# =====================================================================
class SheetCloneWriter:
    """회차 1개 = 새 시트. 템플릿 시트는 절대 수정하지 않는다 (§10 #11)."""

    def __init__(self, book: WorkbookPort, template_name: str = "양식"):
        self.book = book
        self.template_name = template_name

    def unique_name(self, desired: str) -> str:
        """같은 이름이 있으면 '-2', '-3' 을 붙인다."""
        if not self.book.has_sheet(desired):
            return desired
        n = 2
        while self.book.has_sheet(f"{desired}-{n}"):
            n += 1
        return f"{desired}-{n}"

    def clone(self, new_name: str, after: str | None = None,
              template: str | None = None) -> SheetPort:
        tpl = template or self.template_name
        if not self.book.has_sheet(tpl):
            raise KeyError(f"템플릿 시트가 없습니다: {tpl} (있는 시트: {self.book.sheet_names})")
        name = self.unique_name(new_name)
        if after is None:
            after = self.book.sheet_names[-1]
        return self.book.copy_sheet(tpl, name, after=after)

    def next_numeric_name(self, width: int = 2) -> str:
        """'01','02','03' … 형식 시트 중 다음 번호. 612 밀크 일지용."""
        used = [int(n) for n in self.book.sheet_names if n.isdigit()]
        return f"{(max(used) + 1) if used else 1:0{width}d}"

    def next_paired_name(self, base: str = "사진대지") -> str:
        """'사진대지', '사진대지 (2)', '사진대지 (3)' … 다음 이름."""
        if not self.book.has_sheet(base):
            return base
        n = 2
        while self.book.has_sheet(f"{base} ({n})"):
            n += 1
        return f"{base} ({n})"


# =====================================================================
# 13.3 RowGroupWriter — 행 추가형
# =====================================================================
@dataclass
class MergeSpec:
    """행그룹 하나의 병합 규격 (§14.4).

    ``rects`` 는 그룹 기준행 r 을 0 으로 본 상대 좌표
    ``(행오프셋1, 열1, 행오프셋2, 열2)`` 목록이다.
    세로 병합(A~G)도, 가로세로 동시 병합(H{r}:I{r+1})도 같은 형식으로 적는다.
    """

    height: int
    rects_rel: list[tuple[int, int, int, int]] = field(default_factory=list)

    def rects(self, base_row: int) -> list[Rect]:
        return [(base_row + r1, c1, base_row + r2, c2)
                for r1, c1, r2, c2 in self.rects_rel]

    def merge_with(self, other: "MergeSpec") -> "MergeSpec":
        return MergeSpec(height=max(self.height, other.height),
                         rects_rel=[*self.rects_rel, *other.rects_rel])


def vertical_spans(cols: Iterable[int], height: int) -> list[tuple[int, int, int, int]]:
    """A~G, M~R 처럼 그룹 전체를 세로로 병합하는 열들."""
    return [(0, c, height - 1, c) for c in cols]


class RowGroupWriter:
    """행 N개 = 항목 1건. 서식은 직전 그룹에서 복사한다."""

    def __init__(self, sheet: SheetPort, start_row: int, group_height: int = 1,
                 key_col: int = 1, width: int = 18):
        self.sheet = sheet
        self.start_row = start_row
        self.group_height = group_height
        self.key_col = key_col          # 그룹 존재 판정에 쓰는 열 (보통 A)
        self.width = width              # 서식 복사 폭 (실시대장은 A~R = 18)

    # -- 탐색 -----------------------------------------------------------
    def last_filled_row(self) -> int:
        """그룹의 **모든 열** 을 봐서 마지막으로 채워진 행.

        A열만 보면 안 된다. 실시대장은 A~G 가 그룹 전체 세로 병합이라 A에는
        기준행에만 값이 있고, 꼬리 행의 내용은 I·K·L 같은 뒷열에만 있다.
        A만 보고 다음 행을 정하면 **직전 그룹 위에 덮어쓴다.**
        """
        last = self.start_row - 1
        for col in range(self.key_col, self.key_col + self.width):
            last = max(last, self.sheet.last_filled_row(col, self.start_row))
        return last

    def next_row(self) -> int:
        """마지막으로 채워진 그룹 바로 다음 행."""
        return max(self.last_filled_row() + 1, self.start_row)

    def sequence_no(self) -> int:
        """A열 일련번호 다음 값. 실시대장은 월별로 1부터 리셋된다 (§15.1)."""
        best = 0
        r = self.start_row
        blanks = 0
        while blanks < 50 and r < self.start_row + 5000:
            v = self.sheet.read(r, self.key_col)
            if _nonempty(v):
                blanks = 0
                try:
                    best = max(best, int(float(str(v).strip())))
                except ValueError:
                    pass
            else:
                blanks += 1
            r += 1
        return best + 1

    # -- 생성 -----------------------------------------------------------
    def append_group(self, spec: MergeSpec | None = None,
                     copy_format_from: int | None = None) -> int:
        """새 행그룹의 기준행을 확보하고 그 행 번호를 돌려준다."""
        height = spec.height if spec else self.group_height
        row = self.next_row()
        src = copy_format_from
        if src is None:
            src = row - height if row - height >= self.start_row else None
        if src is not None:
            self.sheet.copy_formats(
                (src, self.key_col, src + height - 1, self.key_col + self.width - 1),
                (row, self.key_col, row + height - 1, self.key_col + self.width - 1),
            )
        if spec:
            for rect in spec.rects(row):
                if rect[0] != rect[2] or rect[1] != rect[3]:
                    self.sheet.merge(rect)
        return row

    # -- 쓰기 -----------------------------------------------------------
    def set(self, row: int, col: int, value: Any, *,
            wrap: bool | None = None, number_format: str | None = None) -> None:
        self.sheet.write(row, col, value, wrap=wrap, number_format=number_format)

    def set_row(self, row: int, values: dict[int, Any]) -> None:
        for col, v in values.items():
            self.sheet.write(row, col, v)


def _nonempty(v: Any) -> bool:
    return v is not None and str(v).strip() != ""
