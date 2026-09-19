"""월간 실적보고서 시트에서 쓸 자리 찾기.

다른 파일들과 달리 이 보고서는 **셀 좌표를 실측하지 못했다.**
그래서 좌표를 코드에 박지 않고, 시트를 읽어 **글자로 찾는다.**

* 헤더 행 = `실시` 와 `합격` 이 같이 있는 행
* 금월/누계 = 헤더 위쪽 행의 `금월`·`누계` 라벨
* 종목 열 = `종목` 이라 적힌 열, 없으면 데이터가 들어 있는 가장 왼쪽 열
* 종목 행 = 종목 열에서 이름이 일치하는 행

못 찾으면 **아무 데나 쓰지 않고 무엇을 찾았는지 보고하며 멈춘다.**
감리 제출 문서라 엉뚱한 칸에 숫자가 들어가는 것이 빈칸보다 나쁘다.

실제 파일을 열어 좌표를 확인했다면 이 추론을 걷어내고 고정 좌표로 바꾸면 된다.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

HEADER_SCAN_ROWS = 20        # 헤더는 보통 윗쪽 몇 행 안에 있다
MAX_SCAN_COLS = 40
집계칸 = ("실시", "합격", "불합격", "재시험")


class LayoutError(RuntimeError):
    """보고서에서 쓸 자리를 찾지 못했다. 추측해서 쓰지 않는다."""


def 납작(v: Any) -> str:
    return re.sub(r"\s+", "", str(v)) if v is not None else ""


@dataclass
class ReportLayout:
    """찾아낸 자리."""

    헤더행: int
    종목열: int
    #: {'금월': {'실시': 5, '합격': 6, ...}, '누계': {...}}
    묶음: dict[str, dict[str, int]] = field(default_factory=dict)
    #: {납작한 종목명: 행번호}
    종목행: dict[str, int] = field(default_factory=dict)
    경고: list[str] = field(default_factory=list)

    def 칸(self, 묶음이름: str, 항목: str, 종목: str) -> tuple[int, int] | None:
        """(행, 열). 없으면 None."""
        열 = self.묶음.get(묶음이름, {}).get(항목)
        행 = self.찾기(종목)
        return (행, 열) if (열 and 행) else None

    def 찾기(self, 종목: str) -> int | None:
        """종목 이름으로 행 찾기. 공백을 무시하고, 부분 일치도 본다."""
        key = 납작(종목)
        if key in self.종목행:
            return self.종목행[key]
        for 있는, 행 in self.종목행.items():
            if key and (key in 있는 or 있는 in key):
                return 행
        return None

    def 요약(self) -> str:
        묶음들 = ", ".join(f"{k}({','.join(v)})" for k, v in self.묶음.items())
        return (f"헤더 {self.헤더행}행 · 종목 {self.종목열}열 · 묶음 {묶음들} · "
                f"종목 {len(self.종목행)}개")


def find_layout(sheet: Any, *, read=None) -> ReportLayout:
    """시트에서 자리를 찾는다.

    ``sheet`` 는 ``cell(row, col)`` 또는 ``read(row, col)`` 를 가진 무엇이든 된다
    (읽기 전용 `ReadSheet` 와 쓰기용 `SheetPort` 둘 다 받기 위함).
    """
    get = read or getattr(sheet, "cell", None) or getattr(sheet, "read")
    nrows = getattr(sheet, "nrows", 0) or 200

    헤더행 = _헤더행찾기(get)
    if 헤더행 is None:
        raise LayoutError(
            "보고서에서 헤더 행을 찾지 못했습니다 "
            f"(위 {HEADER_SCAN_ROWS}행에서 '실시' 와 '합격' 이 같이 있는 행을 찾음).\n"
            "시트가 맞는지, 표 머리글이 다른 말로 적혀 있는지 확인하세요.")

    항목열 = _항목열찾기(get, 헤더행)
    묶음 = _묶음나누기(get, 헤더행, 항목열)
    종목열 = _종목열찾기(get, 헤더행, 묶음)
    종목행, 경고 = _종목행찾기(get, 헤더행, 종목열, nrows)

    layout = ReportLayout(헤더행=헤더행, 종목열=종목열, 묶음=묶음,
                          종목행=종목행, 경고=경고)
    if not layout.묶음:
        raise LayoutError(
            f"헤더({헤더행}행)는 찾았지만 '실시/합격' 칸의 열을 정하지 못했습니다.")
    if not layout.종목행:
        raise LayoutError(
            f"헤더({헤더행}행) 아래에서 종목 이름을 하나도 찾지 못했습니다 "
            f"(종목 열 = {종목열}).")
    return layout


# ---------------------------------------------------------------------
def _헤더행찾기(get) -> int | None:
    for r in range(1, HEADER_SCAN_ROWS + 1):
        값 = [납작(get(r, c)) for c in range(1, MAX_SCAN_COLS + 1)]
        if any("실시" in v for v in 값) and any("합격" == v for v in 값):
            return r
    return None


def _항목열찾기(get, 헤더행: int) -> list[tuple[int, str]]:
    """헤더 행에서 실시/합격/불합격/재시험 칸의 열 번호."""
    out: list[tuple[int, str]] = []
    for c in range(1, MAX_SCAN_COLS + 1):
        v = 납작(get(헤더행, c))
        if not v:
            continue
        # '불합격' 이 '합격' 을 포함하므로 긴 것부터 본다
        for 이름 in sorted(집계칸, key=len, reverse=True):
            if v == 이름:
                out.append((c, 이름))
                break
    return out


def _묶음나누기(get, 헤더행: int, 항목열: list[tuple[int, str]]) -> dict[str, dict[str, int]]:
    """각 항목 열이 '금월' 쪽인지 '누계' 쪽인지 가른다.

    헤더 위 두 행에서 '금월'·'누계' 라벨을 찾아, 그 열 이후의 항목을 그 묶음으로 본다.
    라벨이 없으면 항목이 한 벌뿐인 것으로 보고 '금월' 으로 둔다.
    """
    라벨: list[tuple[int, str]] = []
    for r in (헤더행 - 1, 헤더행 - 2):
        if r < 1:
            continue
        for c in range(1, MAX_SCAN_COLS + 1):
            v = 납작(get(r, c))
            if not v:
                continue
            if "금월" in v or "당월" in v:
                라벨.append((c, "금월"))
            elif "누계" in v or "누적" in v:
                라벨.append((c, "누계"))
        if 라벨:
            break
    라벨.sort()

    묶음: dict[str, dict[str, int]] = {}
    for 열, 이름 in 항목열:
        속한 = "금월"
        for 라벨열, 라벨이름 in 라벨:
            if 라벨열 <= 열:
                속한 = 라벨이름
        묶음.setdefault(속한, {})
        묶음[속한].setdefault(이름, 열)      # 같은 이름이 또 나오면 첫 것을 쓴다
    return 묶음


def _종목열찾기(get, 헤더행: int, 묶음: dict[str, dict[str, int]]) -> int:
    """'종목' 이라 적힌 열. 없으면 집계 칸들보다 왼쪽에서 가장 오른쪽 글자 열."""
    첫집계 = min((c for 칸 in 묶음.values() for c in 칸.values()), default=MAX_SCAN_COLS)
    for r in (헤더행, 헤더행 - 1, 헤더행 - 2):
        if r < 1:
            continue
        for c in range(1, 첫집계):
            v = 납작(get(r, c))
            if "종목" in v or "시험명" in v or "검사항목" in v:
                return c
    후보 = [c for c in range(1, 첫집계) if 납작(get(헤더행, c))]
    return 후보[-1] if 후보 else 1


def _종목행찾기(get, 헤더행: int, 종목열: int,
                nrows: int) -> tuple[dict[str, int], list[str]]:
    종목행: dict[str, int] = {}
    경고: list[str] = []
    빈행 = 0
    for r in range(헤더행 + 1, max(헤더행 + 120, nrows + 1)):
        v = 납작(get(r, 종목열))
        if not v:
            빈행 += 1
            if 빈행 >= 15:
                break
            continue
        빈행 = 0
        if v in ("계", "합계", "소계", "총계"):
            continue
        if v in 종목행:
            경고.append(f"종목 '{v}' 이 {종목행[v]}행과 {r}행에 중복됩니다. 첫 행에 씁니다.")
            continue
        종목행[v] = r
    return 종목행, 경고
