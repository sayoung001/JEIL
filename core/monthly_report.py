"""월간 품질시험·검사 실적보고서 자동 집계 (진단 PART D 1순위).

**실시대장을 세기만 하면 보고서가 나온다.** 지금은 손으로 세고 있고,
같은 달 보고서가 `(8월)` `(8월)(2)` `8월 수정본` 세 벌 남아 있는 것이
세다가 틀려서 고쳤다는 증거다 (진단 §5, §10).

감리단 제출 의무 문서라 틀리면 곤란하고, 세는 일은 100% 기계적이다.

세는 단위
---------
**행 하나가 아니라 행그룹(시험 1건)** 이다. 겉모양·치수는 한 건이 5행을
차지한다. A열 일련번호가 있는 행이 그룹의 시작이므로 그것을 센다.

시험 1건이 보고서 여러 줄이 되기도 한다
-------------------------------------
겉모양·치수 시험 1건은 보고서에서 **'겉모양 및 모양' 1건 + '치수' 1건**으로
각각 잡힌다. 진단 §10 실측(8월: 겉모양 4, 치수 4)이 이를 보여 준다.
이 대응은 코드가 아니라 ``templates/실적보고서/종목매핑.yaml`` 에 있다.

대장 두 가지 모양
----------------
* **월 시트형** (`Q-01,02`·`Q-03`·`N-02`) — `26.08` 처럼 달마다 시트가 있다.
* **종류 시트형** (`O-01,04`) — `재하시험`·`MT검사` 시트에 전 기간이 쌓이고,
  B열 날짜로 달을 가른다 (진단 PART A §2 ⑤).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import yaml

from .excel_reader import ReadBook, ReadSheet, ReaderError, read_book
from .ledger import COL, FIRST_DATA_ROW
from .numbering import parse_시험번호
from .paths import resource
from .util import as_date

log = logging.getLogger(__name__)

합격표기 = ("합격", "합 격", "합  격", "적합")
불합격표기 = ("불합격", "부적합")


# ---------------------------------------------------------------------
@dataclass
class LedgerEntry:
    """대장에서 읽어낸 시험 1건 (= 행그룹 1개)."""

    대장: str
    시트: str
    행: int
    일련번호: int | None
    날짜: date | None
    구분: str
    대상재료: str
    종목: str
    판정: str
    비고: str

    @property
    def 계열(self) -> str | None:
        """'Q-Q-\\n02-07' -> 'Q-Q-02'."""
        parsed = parse_시험번호(self.구분)
        return parsed[0].rstrip("-") if parsed else None

    @property
    def 합격(self) -> bool:
        납작 = self.판정.replace(" ", "")
        return any(t.replace(" ", "") == 납작 for t in 합격표기)

    @property
    def 불합격(self) -> bool:
        납작 = self.판정.replace(" ", "")
        return any(t.replace(" ", "") == 납작 for t in 불합격표기)

    @property
    def 재시험(self) -> bool:
        """비고에 '재시험' 이 적힌 경우. 표기가 없으면 잡히지 않는다."""
        return "재시험" in f"{self.비고}{self.대상재료}"


@dataclass
class 종목집계:
    종목: str
    실시: int = 0
    합격: int = 0
    불합격: int = 0
    재시험: int = 0
    출처: list[str] = field(default_factory=list)

    def 더하기(self, other: "종목집계") -> "종목집계":
        return 종목집계(
            종목=self.종목, 실시=self.실시 + other.실시, 합격=self.합격 + other.합격,
            불합격=self.불합격 + other.불합격, 재시험=self.재시험 + other.재시험,
            출처=[*self.출처, *other.출처])

    @property
    def 미판정(self) -> int:
        return self.실시 - self.합격 - self.불합격


@dataclass
class MonthlyTally:
    """한 달치 집계."""

    시트명: str                                   # '26.08'
    종목: dict[str, 종목집계] = field(default_factory=dict)
    entries: list[LedgerEntry] = field(default_factory=list)
    경고: list[str] = field(default_factory=list)

    @property
    def 총건수(self) -> int:
        return sum(v.실시 for v in self.종목.values())

    def 표(self) -> list[tuple[str, int, int, int, int]]:
        return [(k, v.실시, v.합격, v.불합격, v.재시험)
                for k, v in sorted(self.종목.items())]

    def 더하기(self, other: "MonthlyTally") -> "MonthlyTally":
        """누계용. 종목별로 합친다."""
        out = MonthlyTally(시트명=f"{self.시트명}+{other.시트명}")
        for key in {*self.종목, *other.종목}:
            a = self.종목.get(key, 종목집계(key))
            b = other.종목.get(key, 종목집계(key))
            out.종목[key] = a.더하기(b)
        out.경고 = [*self.경고, *other.경고]
        return out

    def __str__(self) -> str:
        if not self.종목:
            return f"{self.시트명}: 집계된 시험이 없습니다."
        폭 = max(len(k) for k in self.종목)
        줄 = [f"{'종목':<{폭}}  실시  합격  불합격  재시험"]
        for 이름, 실시, 합격, 불합격, 재시험 in self.표():
            줄.append(f"{이름:<{폭}}  {실시:>4}  {합격:>4}  {불합격:>6}  {재시험:>6}")
        return "\n".join(줄)


# ---------------------------------------------------------------------
@dataclass
class 매핑규칙:
    """시험 1건을 보고서 어느 줄로 셀 것인가."""

    종목: list[str]
    계열: str | None = None            # 'Q-Q-02'
    시트: str | None = None            # '재하시험'
    대상재료: str | None = None        # 부분 일치

    def 맞는가(self, e: LedgerEntry) -> bool:
        if self.계열 and e.계열 != self.계열:
            return False
        if self.시트 and self.시트 != e.시트:
            return False
        if self.대상재료 and self.대상재료 not in e.대상재료.replace("\n", " "):
            return False
        return any((self.계열, self.시트, self.대상재료))


def load_매핑(path: str | Path | None = None) -> list[매핑규칙]:
    p = Path(path) if path else resource("templates", "실적보고서", "종목매핑.yaml")
    if not p.exists():
        log.warning("종목매핑 파일이 없습니다: %s", p)
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: list[매핑규칙] = []
    for row in raw.get("매핑", []):
        종목 = row.get("종목")
        if isinstance(종목, str):
            종목 = [종목]
        out.append(매핑규칙(종목=list(종목 or []), 계열=row.get("계열"),
                           시트=row.get("시트"), 대상재료=row.get("대상재료")))
    return out


# ---------------------------------------------------------------------
class MonthlyReporter:
    """실시대장 4종을 세어 월간 실적을 낸다. **읽기 전용이다.**"""

    #: (config 키, 대장 이름, 종류시트형이면 시트 목록)
    LEDGERS: tuple[tuple[str, str, tuple[str, ...] | None], ...] = (
        ("ledger_pile", "Q-01,02", None),
        ("ledger_civil", "Q-03", None),
        ("ledger_outsrc", "N-02", None),
        ("ledger_load_mt", "O-01,04", ("재하시험", "MT검사")),
    )

    def __init__(self, cfg: Any, 매핑: list[매핑규칙] | None = None):
        self.cfg = cfg
        self.매핑 = 매핑 if 매핑 is not None else load_매핑()

    # -- 읽기 -----------------------------------------------------------
    def entries(self, 월: str) -> tuple[list[LedgerEntry], list[str]]:
        """'26.08' 한 달치 시험 건들."""
        out: list[LedgerEntry] = []
        경고: list[str] = []
        for key, 이름, 시트목록 in self.LEDGERS:
            try:
                path = self.cfg.path(key)
            except KeyError:
                경고.append(f"{이름}: config 에 경로가 없습니다 ({key})")
                continue
            try:
                book = read_book(path)
            except ReaderError as e:
                경고.append(f"{이름}: 읽지 못했습니다 — {e}")
                continue
            if 시트목록:
                out += self._종류시트형(book, 이름, 시트목록, 월, 경고)
            else:
                out += self._월시트형(book, 이름, 월, 경고)
        return out, 경고

    def _월시트형(self, book: ReadBook, 이름: str, 월: str,
                  경고: list[str]) -> list[LedgerEntry]:
        sh = book.sheets.get(월)
        if sh is None:
            달있음 = [n for n in book.sheet_names if _월시트인가(n)]
            if 달있음:
                경고.append(f"{이름}: {월} 시트가 없습니다 (있는 달: {', '.join(달있음)})")
            return []
        return list(self._읽기(sh, 이름, 월))

    def _종류시트형(self, book: ReadBook, 이름: str, 시트목록: Iterable[str],
                    월: str, 경고: list[str]) -> list[LedgerEntry]:
        """O-01,04 — 시트가 달이 아니라 시험 종류다. B열 날짜로 달을 가른다."""
        out: list[LedgerEntry] = []
        for 시트명 in 시트목록:
            sh = book.sheets.get(시트명)
            if sh is None:
                경고.append(f"{이름}: `{시트명}` 시트가 없습니다 "
                            f"(있는 시트: {', '.join(book.sheet_names)})")
                continue
            for e in self._읽기(sh, 이름, 시트명):
                if e.날짜 is None:
                    경고.append(f"{이름}!{시트명} {e.행}행: 날짜를 읽지 못해 건너뜁니다")
                    continue
                if f"{e.날짜:%y}.{e.날짜:%m}" == 월:
                    out.append(e)
        return out

    def _읽기(self, sh: ReadSheet, 대장: str, 시트: str):
        """A열 일련번호가 있는 행 = 행그룹의 시작 = 시험 1건."""
        for r in range(FIRST_DATA_ROW, sh.nrows + 1):
            번호 = sh.cell(r, COL["일련번호"])
            if 번호 is None or str(번호).strip() == "":
                continue
            try:
                일련 = int(float(str(번호).strip()))
            except ValueError:
                continue
            yield LedgerEntry(
                대장=대장, 시트=시트, 행=r, 일련번호=일련,
                날짜=as_date(sh.cell(r, COL["날짜"])),
                구분=_글자(sh.cell(r, COL["구분"])),
                대상재료=_글자(sh.cell(r, COL["대상재료"])),
                종목=_글자(sh.cell(r, COL["종목"])),
                판정=_글자(sh.cell(r, COL["판정"])),
                비고=_글자(sh.cell(r, COL["비고"])),
            )

    # -- 집계 -----------------------------------------------------------
    def tally(self, 월: str) -> MonthlyTally:
        entries, 경고 = self.entries(월)
        return self.집계(entries, 월, 경고)

    def 집계(self, entries: list[LedgerEntry], 시트명: str,
             경고: list[str] | None = None) -> MonthlyTally:
        out = MonthlyTally(시트명=시트명, entries=entries, 경고=list(경고 or []))
        모름: dict[str, int] = defaultdict(int)

        for e in entries:
            종목들 = self._종목찾기(e)
            if not 종목들:
                모름[f"{e.대장}/{e.구분 or e.대상재료}".replace("\n", "")] += 1
                continue
            for 이름 in 종목들:
                칸 = out.종목.setdefault(이름, 종목집계(이름))
                칸.실시 += 1
                if e.합격:
                    칸.합격 += 1
                elif e.불합격:
                    칸.불합격 += 1
                if e.재시험:
                    칸.재시험 += 1
                칸.출처.append(f"{e.대장}!{e.시트}!{e.행}")

        for 무엇, 몇 in sorted(모름.items()):
            # 조용히 빼면 보고서 건수가 모자란 채로 제출된다
            out.경고.append(
                f"종목을 정하지 못해 {몇}건을 세지 못했습니다: {무엇} "
                "— templates/실적보고서/종목매핑.yaml 에 규칙을 추가하세요")
        for 칸 in out.종목.values():
            if 칸.미판정:
                out.경고.append(f"{칸.종목}: 판정이 비어 있는 건이 {칸.미판정}건 있습니다")
        return out

    def _종목찾기(self, e: LedgerEntry) -> list[str]:
        for 규칙 in self.매핑:
            if 규칙.맞는가(e):
                return 규칙.종목
        return []

    # -- 누계 -----------------------------------------------------------
    def 누계(self, 월: str, *, 시작: str | None = None) -> tuple[MonthlyTally, MonthlyTally]:
        """(전월까지 누계, 금월). 둘 다 대장에서 직접 센다.

        지난 보고서를 읽어 이어받지 않는다. 진단 §5 가 보여 주듯 같은 달
        보고서가 여러 벌 남아 있어 무엇이 정본인지 알 수 없기 때문이다.
        대장 하나만 사실로 삼는다.
        """
        달들 = self.있는_달()
        if 시작:
            달들 = [m for m in 달들 if m >= 시작]
        이전 = [m for m in 달들 if m < 월]

        전월 = MonthlyTally(시트명="전월누계")
        for m in 이전:
            전월 = 전월.더하기(self.tally(m))
        전월.시트명 = "전월누계"
        금월 = self.tally(월)

        # 지난 달에 어떤 대장의 시트가 없는 것은 정상이다 (그 달에 그 시험을
        # 안 했을 뿐). 금월 것만 알리고 과거 달의 '시트 없음' 은 걷어낸다.
        전월.경고 = [w for w in dict.fromkeys(전월.경고) if "시트가 없습니다" not in w]
        if 이전:
            전월.경고.insert(0, f"전월누계에 포함한 달: {', '.join(이전)}")
        else:
            전월.경고.insert(0, f"{월} 이전 달 기록이 대장에 없습니다. 누계 = 금월.")
        return 전월, 금월

    def 있는_달(self) -> list[str]:
        """대장들에 실제로 있는 월 시트 목록 (오름차순)."""
        달: set[str] = set()
        for key, _, 시트목록 in self.LEDGERS:
            try:
                book = read_book(self.cfg.path(key))
            except (ReaderError, KeyError):
                continue
            if 시트목록:
                for 시트명 in 시트목록:
                    sh = book.sheets.get(시트명)
                    if sh is None:
                        continue
                    for r in range(FIRST_DATA_ROW, sh.nrows + 1):
                        d = as_date(sh.cell(r, COL["날짜"]))
                        if d:
                            달.add(f"{d:%y}.{d:%m}")
            else:
                달.update(n for n in book.sheet_names if _월시트인가(n))
        return sorted(달)

    def 분기(self, 연: int, 분기: int) -> MonthlyTally:
        """성과총괄표용 분기 누계 (진단 PART D 5순위 — 1순위의 부산물)."""
        달들 = [f"{연 % 100:02d}.{m:02d}"
                for m in range((분기 - 1) * 3 + 1, 분기 * 3 + 1)]
        out = MonthlyTally(시트명=f"{연}년 {분기}분기")
        for m in 달들:
            out = out.더하기(self.tally(m))
        out.시트명 = f"{연}년 {분기}분기"
        return out


def _글자(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _월시트인가(name: str) -> bool:
    return bool(re.fullmatch(r"\d{2}\.\d{2}", name.strip()))
