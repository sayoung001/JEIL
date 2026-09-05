"""시험 도래 판정 — 배지 엔진 (SPEC §16.0, §17.0, §18.2).

**읽기 전용이다.** 원본 파일을 절대 수정하지 않는다.
``.xlsx`` 는 openpyxl, ``.xls`` 는 xlrd 로 읽으므로 엑셀을 띄우지 않고,
사용자가 그 파일을 열어 둔 채여도 방해하지 않는다.

세 가지를 계산한다.

* **겉모양(Q-Q-02)** — 업체별 ① 최초 반입 시 1회 ② 이후 누적 200본 초과마다 1회.
  계산으로 판정된다.
* **밀크(Q-Q-01)** — 판정할 수 없다. 주 3회 목표에 대한 **카운터만** 보여준다.
  시험 안 한 날을 채우는 건 허위 기록이다.
* **BSCW/JSP(Q-Q-03/04)** — ``state.json`` 의 진행 중 시험 중 예정일 초과 건.

.. note::
   SPEC §16.0 은 이미 배포된 ``due_checker.py`` 를 가져다 쓰라고 한다.
   그 파일(``개인\\클로드 자동 연동\\시험도래판정\\``)이 있으면 그것으로 교체하고,
   여기 구현은 같은 API(``DueChecker(cfg).check()`` -> ``due_count/shape/
   all_vendors/warnings``)를 유지한 대체품이다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .excel_reader import ReaderError, read_book
from .numbering import parse_시험번호
from .util import as_date, as_number, json_default

log = logging.getLogger(__name__)

CHECK_SHEET = "파일 (2)"
CHECK_FIRST_ROW = 18
SHAPE_LIST_SHEET = "대장"
MILK_LIST_SHEET = "대장"


@dataclass
class VendorStatus:
    """업체 1곳의 겉모양 시험 현황."""

    업체: str
    level: str                     # 'due' | 'warn' | 'ok'
    누적: int = 0
    마지막시험: date | None = None
    사유: str = ""
    남은본: int | None = None

    def __str__(self) -> str:
        icon = {"due": "🔴", "warn": "🟡", "ok": "  "}[self.level]
        if self.level == "due":
            return f"{icon} {self.업체}\t겉모양 시험 필요 — {self.사유}"
        if self.level == "warn":
            return f"{icon} {self.업체}\t{self.누적}본 ({self.남은본}본 남음)"
        return f"{icon} {self.업체}\t{self.누적}본"


@dataclass
class WeekStatus:
    """밀크 주간 카운터 (§17.0)."""

    실시: int
    목표: int
    남은평일: int
    날짜들: list[date] = field(default_factory=list)

    @property
    def 남은횟수(self) -> int:
        return max(0, self.목표 - self.실시)

    @property
    def 위험(self) -> bool:
        """남은 평일보다 남은 횟수가 많으면 빨간색."""
        return self.남은횟수 > self.남은평일

    def __str__(self) -> str:
        dots = "●" * self.실시 + "○" * max(0, self.목표 - self.실시)
        head = "🔴 " if self.위험 else ""
        return (f"{head}밀크 시험  이번 주 {dots}  {self.실시}/{self.목표}  "
                f"(평일 {self.남은평일}일 남음)")


@dataclass
class PendingStatus:
    """진행 중 BSCW/JSP (§18.2)."""

    시험번호: str
    단계: str
    예정일: date
    지연일수: int

    @property
    def 지연(self) -> bool:
        return self.지연일수 > 0

    def __str__(self) -> str:
        if self.지연:
            return f"🔴 {self.시험번호} {self.단계} 미입력 {self.지연일수}일 지연"
        return (f"⚠ {self.시험번호}  {self.단계} 미입력   "
                f"(예정 {self.예정일:%Y-%m-%d}, D{self.지연일수:+d})")


@dataclass
class Alerts:
    """메인 화면 배지 묶음."""

    shape: list[VendorStatus] = field(default_factory=list)        # due/warn 만
    all_vendors: list[VendorStatus] = field(default_factory=list)  # 현황 표용
    milk: WeekStatus | None = None
    pending: list[PendingStatus] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    생성시각: str = ""

    @property
    def due_count(self) -> int:
        return sum(1 for v in self.shape if v.level == "due") \
            + sum(1 for p in self.pending if p.지연)

    def to_dict(self) -> dict[str, Any]:
        return {
            "생성시각": self.생성시각,
            "due_count": self.due_count,
            "shape": [v.__dict__ for v in self.all_vendors],
            "milk": self.milk.__dict__ if self.milk else None,
            "pending": [p.__dict__ for p in self.pending],
            "warnings": self.warnings,
        }


class DueChecker:
    """``check()`` 는 읽기 전용이다. 원본 두 파일을 수정하지 않는다."""

    def __init__(self, cfg: Config, state: Any = None):
        self.cfg = cfg
        self.state = state

    # =================================================================
    def check(self, 기준일: date | None = None) -> Alerts:
        기준일 = 기준일 or date.today()
        alerts = Alerts(생성시각=str(기준일))
        warnings: list[str] = []

        deliveries, w1 = self._read_deliveries()
        shape_history, w2 = self._read_shape_history()
        warnings += w1 + w2

        if deliveries is not None and shape_history is not None:
            alerts.all_vendors = self._judge_shape(deliveries, shape_history)
            alerts.shape = [v for v in alerts.all_vendors if v.level in ("due", "warn")]

        milk_dates, w3 = self._read_milk_history()
        warnings += w3
        if milk_dates is not None:
            alerts.milk = self.밀크_주간현황(milk_dates, 기준일)

        alerts.pending = self._pending(기준일)
        alerts.warnings = warnings
        self._dump(alerts)
        return alerts

    # -- 읽기 ------------------------------------------------------------
    def _read_deliveries(self) -> tuple[list[dict] | None, list[str]]:
        """★수불부 체크용 `파일 (2)` 의 A(송장일자)·C(업체)·G(수량 본)."""
        warnings: list[str] = []
        try:
            sh = read_book(self.cfg.path("supply_check"),
                           only=[CHECK_SHEET]).sheet(CHECK_SHEET)
        except (ReaderError, KeyError) as e:
            return None, [f"⚠ ★수불부 체크용을 읽지 못했습니다: {e}"]

        rows: list[dict] = []
        for r in range(CHECK_FIRST_ROW, sh.nrows + 1):
            송장일자 = as_date(sh.cell(r, 1))
            업체 = sh.cell(r, 3)
            본 = as_number(sh.cell(r, 7))
            if 송장일자 is None and 업체 is None:
                continue
            canonical = self.cfg.vendors.canonical(업체)
            if canonical is None:
                if 업체 is not None and str(업체).strip():
                    # 조용히 무시하면 그 업체는 영원히 시험 대상에서 누락된다 (§16.0)
                    warnings.append(
                        f"⚠ 모르는 업체명 '{str(업체).strip()}' "
                        f"(수불부 체크용 {r}행) — vendor_alias 에 추가하세요")
                continue
            rows.append({"업체": canonical, "송장일자": 송장일자, "본": int(본 or 0)})
        return rows, warnings

    def _read_shape_history(self) -> tuple[dict[str, date] | None, list[str]]:
        """601 `대장` 의 B(시험일)·C(업체) -> 업체별 마지막 시험일."""
        warnings: list[str] = []
        try:
            sh = read_book(self.cfg.path("test_shape"),
                           only=[SHAPE_LIST_SHEET]).sheet(SHAPE_LIST_SHEET)
        except (ReaderError, KeyError) as e:
            return None, [f"⚠ 601 대장을 읽지 못했습니다: {e}"]

        last: dict[str, date] = {}
        for r in range(5, sh.nrows + 1):
            시험일 = as_date(sh.cell(r, 2))
            canonical = self.cfg.vendors.canonical(sh.cell(r, 3))   # 뒤 공백 처리 포함
            if 시험일 is None or canonical is None:
                if sh.cell(r, 3) and canonical is None:
                    warnings.append(
                        f"⚠ 모르는 업체명 '{str(sh.cell(r, 3)).strip()}' (601 대장 {r}행)")
                continue
            if canonical not in last or 시험일 > last[canonical]:
                last[canonical] = 시험일
        return last, warnings

    def _read_milk_history(self) -> tuple[list[date] | None, list[str]]:
        """612 `대장` B열(날짜). 대장이 곧 사실이다 (§17.0)."""
        try:
            sh = read_book(self.cfg.path("test_milk"),
                           only=[MILK_LIST_SHEET]).sheet(MILK_LIST_SHEET)
        except (ReaderError, KeyError) as e:
            return None, [f"⚠ 612 대장을 읽지 못했습니다: {e}"]
        out = [d for r in range(5, sh.nrows + 1) if (d := as_date(sh.cell(r, 2)))]
        return out, []

    # -- 판정 ------------------------------------------------------------
    def _judge_shape(self, deliveries: list[dict], 마지막시험: dict[str, date]) -> list[VendorStatus]:
        임계 = int(self.cfg.get("test_rules.phc_shape.threshold_bon", 200))
        예고 = int(self.cfg.get("test_rules.phc_shape.warn_at_bon", 임계 - 20))
        out: list[VendorStatus] = []

        업체들 = sorted({d["업체"] for d in deliveries})
        for 업체 in 업체들:
            반입 = [d for d in deliveries if d["업체"] == 업체]
            if 업체 not in 마지막시험:
                out.append(VendorStatus(
                    업체=업체, level="due", 누적=sum(d["본"] for d in 반입),
                    사유=f"최초 반입 {sum(d['본'] for d in 반입)}본, 시험 이력 없음"))
                continue
            기준일 = 마지막시험[업체]
            누적 = sum(d["본"] for d in 반입
                      if d["송장일자"] and d["송장일자"] > 기준일)
            if 누적 > 임계:
                out.append(VendorStatus(
                    업체=업체, level="due", 누적=누적, 마지막시험=기준일,
                    사유=f"마지막 시험 {기준일:%m/%d} 이후 {누적}본 (기준 {임계}본)"))
            elif 누적 >= 예고:
                out.append(VendorStatus(
                    업체=업체, level="warn", 누적=누적, 마지막시험=기준일,
                    남은본=임계 - 누적 + 1))
            else:
                out.append(VendorStatus(업체=업체, level="ok", 누적=누적, 마지막시험=기준일))
        return out

    @staticmethod
    def 밀크_주간현황(대장_이력: list[date], 기준일: date, 목표: int = 3) -> WeekStatus:
        """주는 월~일로 끊는다 (§17.0)."""
        월 = 기준일 - timedelta(days=기준일.weekday())
        일 = 월 + timedelta(days=6)
        실시 = sorted(d for d in 대장_이력 if 월 <= d <= 일)
        남은평일 = sum(1 for i in range((일 - 기준일).days + 1)
                     if (기준일 + timedelta(days=i)).weekday() < 5)
        return WeekStatus(실시=len(실시), 목표=목표, 남은평일=남은평일, 날짜들=실시)

    def _pending(self, 기준일: date) -> list[PendingStatus]:
        if self.state is None:
            return []
        단계이름 = {"AWAIT_7D": "7일 강도", "AWAIT_28D": "28일 강도"}
        out = []
        for p in self.state.pending:
            out.append(PendingStatus(
                시험번호=p.시험번호, 단계=단계이름.get(p.stage, p.stage),
                예정일=p.예정일(), 지연일수=p.지연일수(기준일)))
        return sorted(out, key=lambda x: x.예정일)

    # -- 기록 ------------------------------------------------------------
    def _dump(self, alerts: Alerts) -> None:
        """GUI 가 꺼져 있어도 마지막 판정 결과가 남게 한다 (§16.0)."""
        try:
            folder = Path(self.cfg.path("state_dir"))
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "alerts.json").write_text(
                json.dumps(alerts.to_dict(), ensure_ascii=False, indent=2,
                           default=json_default), encoding="utf-8")
        except OSError:
            log.warning("alerts.json 을 남기지 못했습니다", exc_info=True)


def load_config(path: str = "config.yaml") -> Config:
    """배포된 due_checker.py 와 같은 진입점 이름을 유지한다 (§16.0)."""
    from .config import load_config as _load

    return _load(path)
