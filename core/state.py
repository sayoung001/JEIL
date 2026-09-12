"""state.json — 워크플로우 체크 상태와 진행 중 시험 (SPEC §5.4, §18.2).

프로그램을 껐다 켜도 유지돼야 하는 것만 담는다.
**시험 이력 자체는 여기 두지 않는다.** 대장이 곧 사실이고, 사람이 엑셀에서 직접
고쳐도 카운터가 따라가야 하기 때문이다 (§17.0).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import CompStage, Series
from .util import json_default

log = logging.getLogger(__name__)


@dataclass
class PendingTest:
    """진행 중인 BSCW/JSP 시험 (§18.2)."""

    series: str                  # 'BSCW' | 'JSP'
    번호: int
    채취일: str                  # ISO
    목록행번호: int
    stage: str = CompStage.AWAIT_7D.value
    측정_7일: list[float] = field(default_factory=list)
    측정_28일: list[float] = field(default_factory=list)

    @property
    def 시험번호(self) -> str:
        from .numbering import 시험번호

        return 시험번호(Series(self.series), self.번호)

    @property
    def 채취일_date(self) -> date:
        return date.fromisoformat(self.채취일)

    def 예정일(self) -> date:
        from datetime import timedelta

        days = 7 if self.stage == CompStage.AWAIT_7D.value else 28
        return self.채취일_date + timedelta(days=days)

    def 지연일수(self, 기준일: date | None = None) -> int:
        """예정일이 지났으면 양수. 아직이면 음수 (D-n)."""
        return ((기준일 or date.today()) - self.예정일()).days


class State:
    """작은 JSON 저장소. 저장은 임시파일 -> 교체라 중간에 죽어도 깨지지 않는다."""

    def __init__(self, path: str | Path = "state.json"):
        self.path = Path(path)
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"workflows": {}, "pending_tests": [], "meta": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("state.json 을 읽지 못해 새로 시작합니다: %s", self.path, exc_info=True)
            return {"workflows": {}, "pending_tests": [], "meta": {}}
        data.setdefault("workflows", {})
        data.setdefault("pending_tests", [])
        data.setdefault("meta", {})
        return data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2,
                                  default=json_default), encoding="utf-8")
        tmp.replace(self.path)

    # -- 워크플로우 체크 (§5.4) --------------------------------------------
    def workflow_key(self, task: str, 회차: Any) -> str:
        return f"{task}#{회차}"

    def get_checks(self, task: str, 회차: Any) -> dict[str, bool]:
        return self.data["workflows"].get(self.workflow_key(task, 회차), {})

    def set_check(self, task: str, 회차: Any, item_id: str, done: bool) -> None:
        key = self.workflow_key(task, 회차)
        self.data["workflows"].setdefault(key, {})[item_id] = done
        self.save()

    def open_workflows(self) -> list[tuple[str, list[str]]]:
        """미완료 항목이 남은 워크플로우. 메인 화면 배지용."""
        out = []
        for key, checks in self.data["workflows"].items():
            미완 = [k for k, v in checks.items() if not v]
            if 미완:
                out.append((key, 미완))
        return out

    # -- 진행 중 시험 (§18.2) ----------------------------------------------
    @property
    def pending(self) -> list[PendingTest]:
        return [PendingTest(**p) for p in self.data["pending_tests"]]

    def upsert_pending(self, t: PendingTest) -> None:
        rows = [p for p in self.data["pending_tests"]
                if not (p["series"] == t.series and p["번호"] == t.번호)]
        if t.stage != CompStage.DONE.value:
            rows.append(asdict(t))
        self.data["pending_tests"] = rows
        self.save()

    def drop_pending(self, series: str, 번호: int) -> None:
        self.data["pending_tests"] = [
            p for p in self.data["pending_tests"]
            if not (p["series"] == series and p["번호"] == 번호)
        ]
        self.save()

    # -- 기타 ------------------------------------------------------------
    def touch(self, key: str) -> None:
        self.data["meta"][key] = datetime.now().isoformat(timespec="seconds")
        self.save()

    def last(self, key: str) -> datetime | None:
        v = self.data["meta"].get(key)
        return datetime.fromisoformat(v) if v else None
