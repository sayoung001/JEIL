"""성적서·송장에서 항목 뽑기 (진단 PART C §7).

진단 문서가 **실제 PDF 를 열어 확인한 문구** 그대로를 기준으로 파싱한다.
추측으로 만든 규칙이 아니라 실측 문자열에 맞췄다.

각 파서는 ``점수(text)`` 로 "이 문서가 내 담당인가" 를 스스로 판단하고,
가장 점수가 높은 파서가 ``파싱(text)`` 을 맡는다. 어느 것도 확신이 없으면
``종류='미상'`` 으로 두고 **사람에게 넘긴다.** 억지로 끼워 맞추지 않는다.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .util import as_date, as_number

log = logging.getLogger(__name__)


@dataclass
class ParsedDocument:
    """읽어낸 문서 한 건."""

    종류: str = "미상"
    항목: dict[str, Any] = field(default_factory=dict)
    확신도: float = 0.0
    경고: list[str] = field(default_factory=list)
    원문: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        return self.항목.get(key, default)

    @property
    def 읽힘(self) -> bool:
        return self.종류 != "미상" and bool(self.항목)

    def 요약(self) -> str:
        if not self.읽힘:
            return "미상 — 사람이 확인해야 합니다"
        주요 = [f"{k}={v}" for k, v in list(self.항목.items())[:4]]
        return f"{self.종류}  " + "  ".join(주요)


# ---------------------------------------------------------------------
# 공용 조각
# ---------------------------------------------------------------------
_DATE = r"(\d{4}[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2})"


def _find(pattern: str, text: str, group: int = 1) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(group).strip() if m else None


def _find_date(pattern: str, text: str) -> date | None:
    raw = _find(pattern, text)
    return as_date(raw.replace(" ", "")) if raw else None


def _업체찾기(text: str, vendors: Any) -> str | None:
    """문서에 적힌 업체명을 vendor_alias 의 표준 키로. 못 찾으면 None.

    '㈜한국파일' 도 '한국파일' 도 같은 업체다. 표기 계열 5종을 모두 본다.
    """
    if vendors is None:
        return None
    납작 = re.sub(r"\s+", "", text)
    for canonical in vendors.canonical_names:
        후보 = {canonical, *(vendors.form(canonical, k) for k in vendors.KEYS)}
        for 표기 in 후보:
            if re.sub(r"\s+", "", str(표기)) in 납작:
                return canonical
    return None


#: PHC 파일 호칭 지름의 현실적인 범위. 날짜(2026-09)를 규격으로 오독하는 것을 막는다.
_지름범위 = (300, 800)
_길이범위 = (5, 30)


def _규격찾기(text: str) -> tuple[int | None, int | None]:
    """'500-15M' -> (500, 15). 날짜·전화번호를 규격으로 읽지 않는다.

    뒤에 M 이 붙거나 '규격' 이라는 말 뒤에 있을 때만 인정하고,
    값이 현실적인 범위(지름 300~800, 길이 5~30m)를 벗어나면 버린다.
    """
    후보 = [
        r"규격[^\n]{0,10}?(\d{3})\s*[-x×]\s*(\d{1,2})",   # '규격 500-15'
        r"(\d{3})\s*[-x×]\s*(\d{1,2})\s*[Mm]\b",          # '500-15M'
        r"[A-Z]\s*-\s*(\d{3})\s*-\s*(\d{1,2})",           # 'A-500-15'
    ]
    for pat in 후보:
        for m in re.finditer(pat, text):
            A, 길이 = int(m.group(1)), int(m.group(2))
            if _지름범위[0] <= A <= _지름범위[1] and _길이범위[0] <= 길이 <= _길이범위[1]:
                return A, 길이
    return None, None


def _동말뚝(text: str) -> tuple[str | None, str | None]:
    """'113동 No.152' / '105동 NO 379' -> ('113', '152')."""
    m = re.search(r"(\d{3})\s*동\s*(?:No\.?|NO\.?|넘버)?\s*(\d+)", text, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)
    return None, None


# ---------------------------------------------------------------------
# 파서들
# ---------------------------------------------------------------------
class Parser:
    종류 = ""
    키워드: tuple[str, ...] = ()

    def 점수(self, text: str) -> float:
        hits = sum(1 for k in self.키워드 if k in text)
        return hits / len(self.키워드) if self.키워드 else 0.0

    def 파싱(self, text: str, vendors: Any = None) -> ParsedDocument:  # pragma: no cover
        raise NotImplementedError


class 자분탐상성적서(Parser):
    """아이텍 MT 성적서 (PART C §7 실측).

    ``발급 번호 IS-2026-163136-00 / 시험명 자분탐상검사 /
    결과 PHC파일 105동 NO 379 : 이상없음``
    """

    종류 = "MT성적서"
    키워드 = ("자분탐상", "발급", "번호")

    def 점수(self, text: str) -> float:
        base = super().점수(text)
        return min(1.0, base + 0.4) if "자분탐상" in text else base * 0.5

    def 파싱(self, text: str, vendors: Any = None) -> ParsedDocument:
        동, 말뚝 = _동말뚝(text)
        항목: dict[str, Any] = {
            "성적서번호": _find(r"(IS-\d{4}-\d+-\d+)", text),
            "접수일자": _find_date(rf"접수\s*일자\s*[:：]?\s*{_DATE}", text),
            "시험명": "자분탐상검사",
            "동": 동,
            "말뚝번호": 말뚝,
            "시험기관": "아이텍",
        }
        결과 = re.search(r"이상\s*없음", text)
        항목["결과"] = "이상없음" if 결과 else (_find(r"결\s*과\s*[:：]\s*(.+)", text) or "")
        항목["판정"] = "합 격" if 결과 else ""
        항목["참관자"] = _find(r"참관자\s*1?\s*[:：]?\s*([가-힣]{2,4})", text)
        항목["책임기술인"] = _find(r"책임기술인\s*[:：]?\s*([가-힣]{2,4})", text)

        경고 = []
        if not 결과:
            경고.append("'이상없음' 문구를 찾지 못했습니다. 판정을 직접 확인하세요.")
        if not 동 or not 말뚝:
            경고.append("동·말뚝번호를 찾지 못했습니다.")
        return ParsedDocument(종류=self.종류, 항목=항목, 경고=경고, 원문=text)


class 재하시험성적서(Parser):
    """아이텍 동재하/시항타 성적서 (PART C §7 실측).

    ``허용지지력(안전율2.5적용): 1126.0kN/본`` — 이 값이 O-01,04 실시대장의
    '시험 결과' 열에 들어간다.
    """

    종류 = "재하성적서"
    키워드 = ("지지력", "발급", "번호")

    def 점수(self, text: str) -> float:
        base = super().점수(text)
        if "동재하" in text or "시항타" in text or "재항타" in text:
            return min(1.0, base + 0.4)
        return base * 0.6

    def 파싱(self, text: str, vendors: Any = None) -> ParsedDocument:
        동, 말뚝 = _동말뚝(text)
        종별 = "시항타" if "시항타" in text else ("재항타" if "재항타" in text else "동재하")
        허용 = as_number(_find(r"허용\s*지지력[^:：\n]*[:：]\s*([\d,.]+)", text))
        설계 = as_number(_find(r"설계\s*지지력[^:：\n]*[:：]\s*([\d,.]+)", text))
        전체 = as_number(_find(r"전체\s*지지력[^:：\n]*[:：]\s*([\d,.]+)", text))

        항목: dict[str, Any] = {
            "성적서번호": _find(r"(IS-\d{4}-\d+-\d+)", text),
            "접수일자": _find_date(rf"접수\s*일자\s*[:：]?\s*{_DATE}", text),
            "시험일자": _find_date(rf"시험\s*검사\s*[:：]?\s*{_DATE}", text),
            "시험명": f"{종별} / 동재하",
            "종별": 종별,
            "동": 동,
            "말뚝번호": 말뚝,
            "전체지지력": 전체,
            "허용지지력": 허용,       # <- 실시대장 '시험 결과'
            "설계지지력": 설계,
            "단위": "kN/본",
            "시험기관": "아이텍",
        }

        경고: list[str] = []
        if 허용 is None:
            경고.append("허용지지력을 찾지 못했습니다. 실시대장 결과값이 비게 됩니다.")
        if 허용 is not None and 설계 is not None:
            # 판정 규칙은 현장 기준에 따라 다르다. 계산만 해서 보여 주고 단정하지 않는다.
            항목["판정_참고"] = "허용 ≥ 설계" if 허용 >= 설계 else "허용 < 설계"
            if 허용 < 설계:
                경고.append(
                    f"허용지지력({허용}) 이 설계지지력({설계}) 보다 작습니다. "
                    "시항타는 판정 대상이 아닐 수 있으니 판정은 직접 정하세요.")
        if not 동 or not 말뚝:
            경고.append("동·말뚝번호를 찾지 못했습니다.")
        return ParsedDocument(종류=self.종류, 항목=항목, 경고=경고, 원문=text)


class PHC생산성적서(Parser):
    """PHC 파일 생산 시험성적서 (PART C §7 실측).

    ``종류및규격 A - 500 - 11 / 로트번호 260914 / 바깥지름 502 / 두께 85 / 길이 11001``
    601 겉모양·치수 일지의 실측치와 **교차 검증**하는 데 쓴다.
    """

    종류 = "PHC생산성적서"
    키워드 = ("바깥지름", "두께", "길이")

    def 점수(self, text: str) -> float:
        base = super().점수(text)
        if re.search(r"A\s*-?\s*\d{3}\s*-?\s*\d{2}", text):
            return min(1.0, base + 0.3)
        return base

    def 파싱(self, text: str, vendors: Any = None) -> ParsedDocument:
        규격 = re.search(r"([A-Z])\s*-\s*(\d{3})\s*-\s*(\d{1,2})", text)
        항목: dict[str, Any] = {
            "종류": 규격.group(1) if 규격 else None,
            "규격_A": int(규격.group(2)) if 규격 else None,
            "규격_m": int(규격.group(3)) if 규격 else None,
            "로트번호": _find(r"로트\s*번호\s*[:：]?\s*(\d+)", text),
            "검사일자": _find_date(rf"검사\s*일자\s*[:：]?\s*{_DATE}", text),
        }
        for 이름, 패턴 in (("바깥지름", r"바깥\s*지름"), ("두께", r"두께"), ("길이", r"길이")):
            값 = re.search(rf"{패턴}\s*[:：]?\s*([\d.]+)\s*/\s*([\d.]+)", text)
            항목[이름] = [as_number(값.group(1)), as_number(값.group(2))] if 값 else []
        항목["판정"] = "합 격" if "합격" in text and "불합격" not in text else ""

        경고 = []
        if not 규격:
            경고.append("종류·규격(A-500-11 형태)을 찾지 못했습니다.")
        if not any(항목[k] for k in ("바깥지름", "두께", "길이")):
            경고.append("치수값을 하나도 찾지 못했습니다.")
        return ParsedDocument(종류=self.종류, 항목=항목, 경고=경고, 원문=text)


class 자재송장(Parser):
    """자재 반입 송장. 업체마다 서식이 달라 **후보 매칭**으로 최선을 다한다.

    한국파일·아이에스는 텍스트 레이어가 있고(100%), 나머지는 스캔이라
    OCR 을 거친다 (PART C §8). 읽은 값은 반드시 사람이 확인하게 한다.
    """

    종류 = "자재송장"
    키워드 = ("송장", "출하", "납품")

    def 점수(self, text: str) -> float:
        base = super().점수(text)
        if re.search(r"PHC|파일|본", text):
            base += 0.2
        return min(1.0, base)

    def 파싱(self, text: str, vendors: Any = None) -> ParsedDocument:
        항목: dict[str, Any] = {
            "일자": _find_date(rf"{_DATE}", text),
            "수량_본": as_number(_find(r"([\d,]+)\s*본", text)),
        }
        A, m = _규격찾기(text)
        if A is not None:
            항목["규격_A"], 항목["규격_m"] = A, m
        항목["업체"] = _업체찾기(text, vendors)

        경고 = ["송장은 업체마다 서식이 달라 읽은 값을 반드시 확인하세요."]
        if 항목.get("수량_본") is None:
            경고.append("수량(본)을 찾지 못했습니다.")
        if 항목.get("업체") is None:
            경고.append("업체명을 찾지 못했습니다. vendor_alias 에 있는 이름이 문서에 없습니다.")
        return ParsedDocument(종류=self.종류, 항목=항목, 경고=경고, 원문=text)


PARSERS: list[Parser] = [자분탐상성적서(), 재하시험성적서(), PHC생산성적서(), 자재송장()]

#: 이 점수 밑이면 '미상' 으로 두고 사람에게 넘긴다.
MIN_SCORE = 0.5


def parse(text: str, *, vendors: Any = None, min_score: float = MIN_SCORE) -> ParsedDocument:
    """글자에서 문서 종류를 알아내고 항목을 뽑는다."""
    if not text or not text.strip():
        return ParsedDocument(경고=["읽어낸 글자가 없습니다."])
    순위 = sorted(((p.점수(text), p) for p in PARSERS), key=lambda x: x[0], reverse=True)
    점수, 파서 = 순위[0]
    if 점수 < min_score:
        return ParsedDocument(
            원문=text, 확신도=점수,
            경고=[f"문서 종류를 알 수 없습니다 (최고 점수 {점수:.2f}). 직접 분류하세요."])
    doc = 파서.파싱(text, vendors)
    doc.확신도 = 점수
    return doc


def parse_file(path: str | Path, *, vendors: Any = None,
               **kw: Any) -> tuple[ParsedDocument, Any]:
    """파일 -> (파싱 결과, 추출 정보). 추출 방식과 경고를 함께 돌려준다."""
    from .extract import extract

    got = extract(path, **kw)
    doc = parse(got.text, vendors=vendors)
    doc.경고 = [*got.warnings, *doc.경고]
    if got.방식.startswith("ocr"):
        doc.확신도 *= 0.8        # OCR 로 읽은 것은 확신도를 낮춰 잡는다
    return doc, got
