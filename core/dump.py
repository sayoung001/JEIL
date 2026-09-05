"""현황 덤프 — SPEC §12 · §22 가 요구하는 확인 출력.

Excel 을 띄우지 않고 읽기만 한다. S1 / S12 완료 확인용.

    python main.py --dump
"""
from __future__ import annotations

from typing import Any

from .config import Config
from .excel_reader import ReaderError, read_book
from .ledger import COL, FIRST_DATA_ROW
from .models import Series
from .numbering import TEST_SERIES, parse_시험번호
from .sheets import col_letter
from .util import as_number


def dump_state(cfg: Config) -> None:
    _part1(cfg)
    print()
    _part2(cfg)


# ---------------------------------------------------------------------
def _part1(cfg: Config) -> None:
    """§12 — 최신 차수 / 갑지 마지막 블록 시작 열 / 수불부 9월 마지막 행·누계."""
    print("=" * 72)
    print("PART 1 — 자재검수")
    print("=" * 72)

    # ★수불부 체크용
    try:
        sh = read_book(cfg.path("supply_check"), only=["파일 (2)"]).sheet("파일 (2)")
        last = sh.last_filled_row(1, 18)
        차수들 = [as_number(sh.cell(r, 11)) for r in range(18, last + 1)]
        최신 = max((int(v) for v in 차수들 if v is not None), default=0)
        print(f"★수불부 체크용 `파일 (2)`")
        print(f"   마지막 데이터 행 : {last}")
        print(f"   최신 차수        : {최신}  ->  다음 회차 {최신 + 1}")
    except (ReaderError, KeyError) as e:
        print(f"★수불부 체크용: 읽지 못했습니다 — {e}")

    # 갑지
    try:
        sh = read_book(cfg.path("request_cover"), only=["자재검수(PHC)"]).sheet("자재검수(PHC)")
        마지막 = 0
        for n in range(1, 200):
            c0 = 1 + (n - 1) * 10
            if c0 > sh.ncols:
                break
            if sh.cell(2, c0 + 2) not in (None, ""):
                마지막 = n
        c0 = 1 + (마지막 - 1) * 10
        print(f"자재검수요청서 갑지 `자재검수(PHC)`")
        print(f"   마지막 블록      : {마지막}번  시작 열 {col_letter(c0)} ({c0})")
        print(f"   문서번호         : {sh.cell(2, c0 + 2)!r}")
        print(f"   합계 누계수량    : {sh.cell(9, c0 + 7)!r}")
        print(f"   다음 회차 블록   : {col_letter(c0 + 10)} ({c0 + 10})")
    except (ReaderError, KeyError) as e:
        print(f"갑지: 읽지 못했습니다 — {e}")

    # 자재수불부
    try:
        sh = read_book(cfg.path("ledger_phc"), data_only=True, only=["500"]).sheet("500")
        for n in range(1, 60):
            c0 = 1 + (n - 1) * 16
            title = sh.cell(1, c0)
            if title in (None, ""):
                break
            rows = [r for r in range(5, 39, 2) if sh.cell(r, c0 + 4) not in (None, "")]
            if not rows:
                continue
            last = rows[-1]
            print(f"JQC304-A 자재수불부 `500` — {str(title).strip()}")
            print(f"   블록 시작 열     : {col_letter(c0)} ({c0})")
            print(f"   마지막 데이터 행 : {last}   (건수 {len(rows)})")
            print(f"   누계(H/X 열)     : {sh.cell(last, c0 + 7)!r}")
    except (ReaderError, KeyError) as e:
        print(f"자재수불부: 읽지 못했습니다 — {e}")


# ---------------------------------------------------------------------
def _part2(cfg: Config) -> None:
    """§22 — 대장 3종의 월 시트·마지막 행·일련번호, 계열별 최신 시험번호."""
    print("=" * 72)
    print("PART 2 — 시험")
    print("=" * 72)

    for key, label in (("ledger_pile", "Q-01,02 (파일)"),
                       ("ledger_civil", "Q-03 (토목)"),
                       ("ledger_outsrc", "N-02 (의뢰시험)")):
        try:
            book = read_book(cfg.path(key))
        except ReaderError as e:
            print(f"{label}: 읽지 못했습니다 — {e}")
            continue
        print(f"{label}  시트: {book.sheet_names}")
        for name, sh in book.sheets.items():
            parts = name.split(".")
            if not (len(parts) == 2 and all(p.isdigit() for p in parts)):
                continue
            last = sh.last_filled_row(COL["일련번호"], FIRST_DATA_ROW)
            일련 = as_number(sh.cell(last, COL["일련번호"])) if last >= FIRST_DATA_ROW else None
            print(f"   {name}  마지막 데이터 행 {last}"
                  f"   마지막 일련번호 {int(일련) if 일련 else '-'}")

    print()
    for series, sheet, row, off, width in (
        (Series.PHC_SHAPE, "일지", 3, 3, 12),
        (Series.BSCW, "BSCW_압축강도_시험일지", 5, 2, 11),
        (Series.JSP, "JSP_압축강도_시험일지", 5, 2, 11),
    ):
        key = TEST_SERIES[series]["journal"]
        try:
            sh = read_book(cfg.path(key), only=[sheet]).sheet(sheet)
        except (ReaderError, KeyError) as e:
            print(f"{series.value}: 읽지 못했습니다 — {e}")
            continue
        numbers = []
        for n in range(1, 200):
            c0 = 1 + (n - 1) * width
            if c0 > sh.ncols:
                break
            parsed = parse_시험번호(sh.cell(row, c0 + off))
            if parsed:
                numbers.append((n, sh.cell(row, c0 + off)))
        if numbers:
            n, text = numbers[-1]
            print(f"{series.value:10s} 마지막 블록 {n}번 "
                  f"(시작 열 {col_letter(1 + (n - 1) * width)})  최신 시험번호 {str(text).strip()!r}")
        else:
            print(f"{series.value:10s} 블록 없음")

    # 612 는 시트 복제형이라 시트 이름이 곧 번호다
    try:
        book = read_book(cfg.path("test_milk"))
        nums = sorted(int(n) for n in book.sheet_names if n.isdigit())
        print(f"PHC_MILK   시트 {book.sheet_names}  최신 번호 "
              f"{f'Q-Q-01-{max(nums):02d}' if nums else '없음'}")
    except ReaderError as e:
        print(f"PHC_MILK: 읽지 못했습니다 — {e}")
