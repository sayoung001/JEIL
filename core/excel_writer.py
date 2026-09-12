"""쓰기 백엔드 — xlwings 전용 (SPEC §1.1, §2.2, §20.1).

**openpyxl 로 저장하지 않는다.** 저장하는 순간 EMF 이미지와 VML 도형이 조용히 사라진다.
Excel 이 없거나 COM 이 실패하면 **작업을 중단하고 사용자에게 알린다.** 폴백 저장은 없다.

작업 1건 = ``ExcelSession`` 1개 = Excel 프로세스 1개.

    with ExcelSession() as sess:
        book = sess.open(갑지경로)      # 임시 사본을 열어 준다
        ...                            # 엔진으로 사본을 수정
        sess.commit()                  # 저장 -> 검증 -> 원본 자리로 원자적 교체

``commit()`` 전에 예외가 나면 사본만 버려지고 **원본은 손도 대지 않은 상태로 남는다.**
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from .sheets import Rect, SheetPort, WorkbookPort, rect_a1
from .util import atomic_replace, is_locked

log = logging.getLogger(__name__)

# Excel 상수 (COM)
XL_PASTE_FORMATS = -4122
XL_PASTE_ALL = -4104


class ExcelUnavailable(RuntimeError):
    """Excel 또는 xlwings 를 쓸 수 없다. 조용히 폴백하지 말고 이걸 그대로 띄운다."""


class FileLocked(RuntimeError):
    """대상 파일이 다른 프로세스에서 열려 있다 (§10 #7)."""


def require_excel() -> None:
    """실행 전 점검. 실패하면 사람이 읽을 수 있는 메시지로 중단시킨다."""
    try:
        import xlwings  # noqa: F401
    except ImportError as e:
        raise ExcelUnavailable(
            "xlwings 를 불러올 수 없습니다.\n"
            "  pip install xlwings\n"
            "이 프로그램은 서식·도형 보존을 위해 Excel 로만 씁니다. "
            "openpyxl 로 저장하면 EMF·VML 도형이 사라집니다."
        ) from e
    import sys

    if not sys.platform.startswith("win"):
        raise ExcelUnavailable(
            f"쓰기 작업은 Windows + Excel 에서만 가능합니다 (현재: {sys.platform}).\n"
            "읽기·판정·미리보기는 이 환경에서도 됩니다."
        )


# =====================================================================
# SheetPort 구현
# =====================================================================
class XlwingsSheet(SheetPort):
    def __init__(self, ws: Any, book: "XlwingsWorkbook"):
        self._ws = ws
        self._book = book
        self.name = ws.name

    # -- 읽기 -----------------------------------------------------------
    def read(self, row: int, col: int) -> Any:
        return self._ws.range((row, col)).value

    def read_row(self, row: int, col_from: int, col_to: int) -> list[Any]:
        if col_to < col_from:
            return []
        if col_to == col_from:
            return [self._ws.range((row, col_from)).value]
        return list(self._ws.range((row, col_from), (row, col_to)).value)

    def read_col(self, col: int, row_from: int, row_to: int) -> list[Any]:
        if row_to < row_from:
            return []
        if row_to == row_from:
            return [self._ws.range((row_from, col)).value]
        return list(self._ws.range((row_from, col), (row_to, col)).value)

    # -- 쓰기 -----------------------------------------------------------
    def write(self, row: int, col: int, value: Any, *,
              wrap: bool | None = None, number_format: str | None = None) -> None:
        rng = self._ws.range((row, col))
        if value is None:
            rng.clear_contents()
        else:
            # 병합 셀은 좌상단에만 쓴다 (xlwings 가 알아서 하지만 명시해 둔다)
            rng.value = value
        if number_format:
            rng.number_format = number_format
        if wrap is not None:
            rng.api.WrapText = wrap
        self._book.touch()

    # -- 복사 -----------------------------------------------------------
    def _range(self, rect: Rect) -> Any:
        r1, c1, r2, c2 = rect
        return self._ws.range((r1, c1), (r2, c2))

    def copy_all(self, src: Rect, dst: Rect) -> None:
        """값·서식·병합·테두리 전부. 갑지/일지 블록 복제의 핵심."""
        self._range(src).api.Copy(self._range(dst).api)
        self._book.touch()

    def copy_formats(self, src: Rect, dst: Rect) -> None:
        self._range(src).api.Copy()
        self._range(dst).api.PasteSpecial(Paste=XL_PASTE_FORMATS)
        self._book.app.api.CutCopyMode = False
        self._book.touch()

    # -- 병합 / 인쇄영역 --------------------------------------------------
    def merge(self, rect: Rect) -> None:
        rng = self._range(rect)
        if not rng.api.MergeCells:
            rng.api.Merge()
        self._book.touch()

    def unmerge(self, rect: Rect) -> None:
        self._range(rect).api.UnMerge()
        self._book.touch()

    def set_print_area(self, rect: Rect) -> None:
        r1, c1, r2, c2 = rect
        from .sheets import col_letter

        self._ws.api.PageSetup.PrintArea = (
            f"${col_letter(c1)}${r1}:${col_letter(c2)}${r2}"
        )
        self._book.touch()

    # -- 열 너비 / 행 --------------------------------------------------
    def get_column_width(self, col: int) -> float:
        return float(self._ws.api.Columns(col).ColumnWidth)

    def set_column_width(self, col: int, width: float) -> None:
        self._ws.api.Columns(col).ColumnWidth = width
        self._book.touch()

    def insert_rows(self, row: int, count: int) -> None:
        self._ws.api.Rows(f"{row}:{row + count - 1}").Insert()
        self._book.touch()


class XlwingsWorkbook(WorkbookPort):
    def __init__(self, wb: Any, app: Any, original: Path, temp: Path):
        self._wb = wb
        self.app = app
        self.original = original
        self.temp = temp
        self.dirty = False
        self._cache: dict[str, XlwingsSheet] = {}

    def touch(self) -> None:
        self.dirty = True

    @property
    def sheet_names(self) -> list[str]:
        return [s.name for s in self._wb.sheets]

    def sheet(self, name: str) -> XlwingsSheet:
        if name not in self._cache:
            if name not in self.sheet_names:
                raise KeyError(
                    f"시트가 없습니다: {name!r} in {self.original.name} "
                    f"(있는 시트: {self.sheet_names})"
                )
            self._cache[name] = XlwingsSheet(self._wb.sheets[name], self)
        return self._cache[name]

    def copy_sheet(self, template: str, new_name: str, after: str | None = None) -> XlwingsSheet:
        """템플릿 시트를 복사한다. 템플릿 자체는 수정하지 않는다 (§10 #11)."""
        if new_name in self.sheet_names:
            raise ValueError(f"이미 있는 시트 이름입니다: {new_name}")
        tpl = self._wb.sheets[template]
        anchor = self._wb.sheets[after] if after else self._wb.sheets[-1]
        tpl.api.Copy(After=anchor.api)
        created = self._wb.sheets[anchor.index]  # 방금 복사된 시트가 anchor 바로 뒤에 온다
        created.name = new_name
        self._cache.pop(new_name, None)
        self.touch()
        return self.sheet(new_name)

    def save(self) -> None:
        """확장자를 절대 바꾸지 않는다. FileFormat 을 건드리지 않는 것이 핵심 (§20.1)."""
        self._wb.save()

    def close(self) -> None:
        try:
            self._wb.close()
        except Exception:                        # pragma: no cover - COM 정리
            log.warning("통합문서 닫기 실패: %s", self.original.name, exc_info=True)


# =====================================================================
# 세션
# =====================================================================
class ExcelSession:
    """작업 1건당 Excel 1회 기동 (§1.1)."""

    def __init__(self, *, visible: bool = False, dry_run: bool = False):
        self.visible = visible
        self.dry_run = dry_run
        self.app: Any = None
        self.books: list[XlwingsWorkbook] = []
        self._tempdir: tempfile.TemporaryDirectory | None = None
        self._committed = False

    # -- 수명 -----------------------------------------------------------
    def __enter__(self) -> "ExcelSession":
        require_excel()
        import xlwings as xw

        self._tempdir = tempfile.TemporaryDirectory(prefix="품질자동화_")
        try:
            self.app = xw.App(visible=self.visible, add_book=False)
        except Exception as e:                    # pragma: no cover - COM
            self._cleanup_tempdir()
            raise ExcelUnavailable(
                f"Excel 을 시작할 수 없습니다: {e}\n"
                "Excel 이 설치돼 있는지, 다른 창이 대화상자를 띄운 채 멈춰 있지 않은지 확인하세요."
            ) from e
        self.app.display_alerts = False
        self.app.screen_updating = False
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        for book in self.books:
            book.close()
        if self.app is not None:
            try:
                self.app.quit()
            except Exception:                     # pragma: no cover
                log.warning("Excel 종료 실패", exc_info=True)
        self._cleanup_tempdir()

    def _cleanup_tempdir(self) -> None:
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None

    # -- 열기 -----------------------------------------------------------
    def open(self, path: str | Path) -> XlwingsWorkbook:
        """원본을 임시 사본으로 복사한 뒤 사본을 연다 (§2.2)."""
        original = Path(path)
        if not original.exists():
            raise FileNotFoundError(f"파일이 없습니다: {original}")
        if is_locked(original):
            raise FileLocked(
                f"'{original.name}' 이(가) 열려 있습니다.\n"
                "엑셀에서 닫은 뒤 다시 실행하세요. 열린 채로는 안전하게 쓸 수 없습니다."
            )
        assert self._tempdir is not None
        temp = Path(self._tempdir.name) / original.name   # 확장자 유지 (.xls 그대로)
        shutil.copy2(original, temp)
        wb = self.app.books.open(str(temp), update_links=False)
        book = XlwingsWorkbook(wb, self.app, original, temp)
        self.books.append(book)
        return book

    # -- 커밋 -----------------------------------------------------------
    def commit(self, verify: Callable[[list[XlwingsWorkbook]], list[str]] | None = None) -> None:
        """저장 -> (선택) 검증 -> 원본 자리로 원자적 교체.

        ``verify`` 가 문제 목록을 돌려주면 교체하지 않고 예외를 낸다.
        원본은 아직 손대지 않은 상태이므로 되돌릴 것도 없다.
        """
        for book in self.books:
            book.save()
        if verify:
            problems = verify(self.books)
            if problems:
                raise ValueError("사후 검증 실패:\n- " + "\n- ".join(problems))
        for book in self.books:
            book.close()
        if self.dry_run:
            log.info("dry_run: 원본을 교체하지 않았습니다")
            self._committed = True
            return
        for book in self.books:
            if is_locked(book.original):
                raise FileLocked(f"교체 직전에 '{book.original.name}' 이 열렸습니다. 중단합니다.")
        for book in self.books:
            atomic_replace(book.temp, book.original)
            log.info("교체 완료: %s", book.original)
        self._committed = True

    @property
    def committed(self) -> bool:
        return self._committed


def describe_rect(rect: Rect) -> str:
    return rect_a1(rect)
