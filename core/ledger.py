"""감리단 실시대장 기록기 (SPEC §14.4, §15.2, §19.3).

대장 3종(`Q-01,02` / `Q-03` / `N-02`)은 **열 구성이 100% 같다.**
다른 것은 행그룹의 높이와 H~L 병합 패턴뿐이라, 그 차이를 YAML 템플릿으로 뺐다.
새 시험 종류가 생기면 **코드가 아니라 templates/ 에 YAML 한 장**을 더 넣는다.
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .engines import MergeSpec, RowGroupWriter, vertical_spans
from .numbering import 대장_시트명, 이전_대장_시트명
from .sheets import SheetPort, WorkbookPort, col_index, col_letter

log = logging.getLogger(__name__)

FIRST_DATA_ROW = 4          # 데이터는 4행부터 (헤더 2~3행)
LEDGER_WIDTH = 18           # A~R

COL = {"일련번호": 1, "날짜": 2, "구분": 3, "대상재료": 4, "규격": 5, "공장": 6,
       "장소": 7, "종목": 8, "세부": 9, "단위": 10, "기준": 11, "결과": 12,
       "판정": 13, "기술인성명": 14, "기술인서명": 15, "감리원성명": 16,
       "감리원서명": 17, "비고": 18}

# 그룹 전체를 세로 병합하는 열: A~G 와 M~R (§14.4)
VERTICAL_COLS = [*range(COL["일련번호"], COL["장소"] + 1),
                 *range(COL["판정"], COL["비고"] + 1)]

_RANGE_RE = re.compile(
    r"^\s*([A-Za-z]+)\{r(?:\s*([+-])\s*(\d+))?\}\s*:\s*([A-Za-z]+)\{r(?:\s*([+-])\s*(\d+))?\}\s*$"
)


def parse_range(expr: str) -> tuple[int, int, int, int]:
    """'H{r}:I{r+1}' -> (0, 8, 1, 9) — (행오프셋1, 열1, 행오프셋2, 열2)."""
    m = _RANGE_RE.match(expr)
    if not m:
        raise ValueError(f"병합 범위 표기를 읽을 수 없습니다: {expr!r} (예: 'H{{r}}:I{{r+1}}')")
    c1, s1, n1, c2, s2, n2 = m.groups()
    off1 = int(f"{s1 or '+'}{n1}") if n1 else 0
    off2 = int(f"{s2 or '+'}{n2}") if n2 else 0
    return (off1, col_index(c1), off2, col_index(c2))


_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
                  ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                  ast.Mod, ast.Pow, ast.USub, ast.UAdd)


def safe_eval(expr: str, variables: dict[str, Any]) -> Any:
    """'규격m*3' 같은 산술식만 계산한다. 함수 호출·속성 접근은 허용하지 않는다."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"허용되지 않는 식입니다: {expr!r} ({type(node).__name__})")
        if isinstance(node, ast.Name) and node.id not in variables:
            raise ValueError(f"식에 모르는 변수가 있습니다: {node.id} (가능: {list(variables)})")
    return eval(compile(tree, "<기준식>", "eval"), {"__builtins__": {}}, dict(variables))


def render(text: Any, variables: dict[str, Any]) -> Any:
    """'±0.3%\\n(±{규격m*3})' 의 {식} 부분을 계산해 채운다."""
    if not isinstance(text, str) or "{" not in text:
        return text

    def repl(m: "re.Match[str]") -> str:
        value = safe_eval(m.group(1), variables)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)

    return re.sub(r"\{([^{}]+)\}", repl, text)


# ---------------------------------------------------------------------
@dataclass
class TemplateItem:
    """대장 행그룹의 한 행."""

    행: int = 0
    세부: str | None = None       # I열
    단위: str = "-"               # J열
    기준: Any = None              # K열 (고정 문자열)
    기준식: str | None = None     # K열 (변수를 쓰는 식)
    종목: str | None = None       # H열을 행마다 따로 쓰는 경우 (의뢰시험)

    def k값(self, variables: dict[str, Any]) -> Any:
        return render(self.기준식, variables) if self.기준식 else self.기준


@dataclass
class LedgerTemplate:
    """실시대장 항목 템플릿 (§19.3)."""

    이름: str
    대상재료: str
    그룹높이: int
    항목: list[TemplateItem] = field(default_factory=list)
    병합: list[dict] = field(default_factory=list)     # [{범위, 값}]
    규격: str | None = None
    비고: str | None = None
    가변높이: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "LedgerTemplate":
        p = Path(path)
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        entries = raw.get("항목", [])
        items = [TemplateItem(**it) for it in entries]
        if all("행" not in it for it in entries):
            for i, item in enumerate(items):      # 행을 안 적었으면 적힌 순서대로
                item.행 = i
        높이 = raw.get("그룹높이") or (max((i.행 for i in items), default=0) + 1)
        return cls(
            이름=p.stem,
            대상재료=raw.get("대상재료", p.stem),
            그룹높이=int(높이),
            항목=items,
            병합=raw.get("병합", []),
            규격=raw.get("규격"),
            비고=raw.get("비고"),
            가변높이=bool(raw.get("가변높이", not raw.get("그룹높이"))),
        )

    def merge_spec(self) -> MergeSpec:
        rects = list(vertical_spans(VERTICAL_COLS, self.그룹높이))
        for m in self.병합:
            rects.append(parse_range(m["범위"]))
        return MergeSpec(height=self.그룹높이, rects_rel=rects)

    def 병합값(self, variables: dict[str, Any]) -> list[tuple[int, int, Any]]:
        """[(행오프셋, 열, 값)] — H{r}:H{r+2} = '치 수' 같은 병합 셀 값."""
        out = []
        for m in self.병합:
            if "값" not in m:
                continue
            r1, c1, _, _ = parse_range(m["범위"])
            out.append((r1, c1, render(m["값"], variables)))
        return out


def load_templates(root: str | Path) -> dict[str, LedgerTemplate]:
    """templates/ 아래 모든 YAML 을 이름으로 색인한다."""
    out: dict[str, LedgerTemplate] = {}
    base = Path(root)
    if not base.exists():
        return out
    for p in sorted(base.rglob("*.yaml")):
        try:
            t = LedgerTemplate.load(p)
            out[t.이름] = t
        except Exception:
            log.warning("템플릿을 읽지 못했습니다: %s", p, exc_info=True)
    return out


# ---------------------------------------------------------------------
@dataclass
class LedgerEntry:
    """실시대장에 들어갈 시험 1건."""

    날짜: date                     # = 완료일 (§15.2)
    구분: str                      # C열 'Q-Q-\n02-07' 또는 '의뢰시험'
    공장: str                      # F열 (업체명 — 대장 표기 계열)
    장소: str = "현장내"           # G열
    규격: str = "-"                # E열
    결과: list[Any] = field(default_factory=list)   # L열, 행 순서대로
    판정: str = "합 격"            # M열
    기술인: str = "윤재웅"         # N열
    감리원: str = "김운종"         # P열
    비고: Any = None               # R열
    변수: dict[str, Any] = field(default_factory=dict)   # 기준식에 쓰는 값
    대상재료: str | None = None    # 템플릿 기본값을 덮어쓸 때


class LedgerWriter:
    """월 시트를 찾아(없으면 만들어) 행그룹 하나를 기록한다."""

    def __init__(self, book: WorkbookPort, template: LedgerTemplate):
        self.book = book
        self.template = template

    # -- 월 시트 (§15.2) -------------------------------------------------
    def sheet_for(self, 완료일: date) -> SheetPort:
        name = 대장_시트명(완료일)
        if self.book.has_sheet(name):
            return self.book.sheet(name)
        prev = 이전_대장_시트명(name)
        if not self.book.has_sheet(prev):
            raise KeyError(
                f"대장에 {name} 시트도 직전 월({prev}) 시트도 없습니다. "
                f"있는 시트: {self.book.sheet_names}"
            )
        log.info("대장에 %s 시트를 만듭니다 (%s 복제)", name, prev)
        sheet = self.book.copy_sheet(prev, name, after=prev)
        self._clear_data(sheet)
        self._retitle(sheet, 완료일)
        return sheet

    def _clear_data(self, sheet: SheetPort, max_row: int = 400) -> None:
        """복제한 시트의 데이터 행만 비운다. 서식·병합은 그대로 둔다."""
        last = sheet.last_filled_row(COL["일련번호"], FIRST_DATA_ROW)
        end = max(last, FIRST_DATA_ROW)
        # 병합 때문에 A열이 비는 꼬리 행까지 넉넉히 지운다
        end = min(end + self.template.그룹높이 + 2, max_row)
        sheet.clear_values((FIRST_DATA_ROW, 1, end, LEDGER_WIDTH))

    def _retitle(self, sheet: SheetPort, 완료일: date) -> None:
        """A1 제목의 월을 갱신한다. 형식을 못 알아보면 경고만 남긴다."""
        title = sheet.read(1, 1)
        if not isinstance(title, str):
            return
        patterns = [
            (r"\d{2}\.\d{2}", f"{완료일:%y}.{완료일:%m}"),
            (r"\d{2}년\s*\d{1,2}월", f"{완료일:%y}년 {완료일:%m}월"),
            (r"\d{4}년\s*\d{1,2}월", f"{완료일:%Y}년 {완료일.month}월"),
        ]
        for pat, rep in patterns:
            if re.search(pat, title):
                sheet.write(1, 1, re.sub(pat, rep, title, count=1))
                return
        log.warning("대장 A1 제목에서 월 표기를 찾지 못했습니다: %r — 직접 확인하세요", title)

    # -- 기록 -------------------------------------------------------------
    def append(self, entry: LedgerEntry) -> int:
        """행그룹을 추가하고 기준행을 돌려준다."""
        t = self.template
        sheet = self.sheet_for(entry.날짜)
        rg = RowGroupWriter(sheet, FIRST_DATA_ROW, t.그룹높이,
                            key_col=COL["일련번호"], width=LEDGER_WIDTH)
        seq = rg.sequence_no()                 # 월별로 1부터 (§15.1)
        row = rg.append_group(t.merge_spec())

        variables = dict(entry.변수)
        rg.set(row, COL["일련번호"], seq)
        rg.set(row, COL["날짜"], entry.날짜, number_format="yyyy-mm-dd")
        rg.set(row, COL["구분"], entry.구분, wrap=True)
        rg.set(row, COL["대상재료"], entry.대상재료 or t.대상재료, wrap=True)
        rg.set(row, COL["규격"], render(entry.규격 or t.규격 or "-", variables), wrap=True)
        rg.set(row, COL["공장"], entry.공장)
        rg.set(row, COL["장소"], entry.장소)
        rg.set(row, COL["판정"], entry.판정)
        rg.set(row, COL["기술인성명"], entry.기술인)
        rg.set(row, COL["감리원성명"], entry.감리원)
        비고 = entry.비고 if entry.비고 is not None else t.비고
        if 비고 is not None:
            rg.set(row, COL["비고"], 비고)

        # 병합 셀 값 (H{r}:H{r+2} = '치 수' 등)
        for off, col, value in t.병합값(variables):
            rg.set(row + off, col, value, wrap=True)

        # 행별 값
        for i, item in enumerate(t.항목):
            r = row + item.행
            if item.종목:
                rg.set(r, COL["종목"], render(item.종목, variables), wrap=True)
            if item.세부:
                rg.set(r, COL["세부"], render(item.세부, variables), wrap=True)
            rg.set(r, COL["단위"], item.단위)
            rg.set(r, COL["기준"], item.k값(variables), wrap=True)
            if i < len(entry.결과):
                rg.set(r, COL["결과"], entry.결과[i])
        return row

    @staticmethod
    def cell_name(row: int, key: str) -> str:
        return f"{col_letter(COL[key])}{row}"
