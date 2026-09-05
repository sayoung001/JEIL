"""워크플로우 패널 — 자동 처리 결과 + 수동 단계 체크리스트 (SPEC §5.4, §7).

체크 상태는 ``state.json`` 에 회차별로 저장돼 프로그램을 재시작해도 유지된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QVBoxLayout, QWidget

from core.state import State


@dataclass
class Workflow:
    name: str
    auto: list[str] = field(default_factory=list)
    manual: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Workflow":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(name=raw.get("name", Path(path).stem),
                   auto=raw.get("auto", []), manual=raw.get("manual", []))

    def format(self, text: str, values: dict[str, Any]) -> str:
        """{날짜} {차수} 같은 자리표시자를 채운다. 모르는 건 그대로 둔다."""
        out = text
        for k, v in values.items():
            out = out.replace(f"{{{k}}}", str(v))
        return out


class WorkflowPanel(QWidget):
    def __init__(self, state: State, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.workflow: Workflow | None = None
        self.task_name = ""
        self.회차: Any = ""
        self.values: dict[str, Any] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.title = QLabel("워크플로우")
        self.title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self.title)

        self.auto_box = QGroupBox("■ 자동 처리")
        self.auto_layout = QVBoxLayout(self.auto_box)
        layout.addWidget(self.auto_box)

        self.manual_box = QGroupBox("□ 수동 확인")
        self.manual_layout = QVBoxLayout(self.manual_box)
        layout.addWidget(self.manual_box)

        layout.addStretch(1)
        self._checks: dict[str, QCheckBox] = {}

    # -----------------------------------------------------------------
    def load(self, workflow_file: str, task_name: str, 회차: Any,
             values: dict[str, Any] | None = None) -> None:
        base = Path(__file__).resolve().parent.parent / "workflows"
        self.workflow = Workflow.load(base / workflow_file)
        self.task_name, self.회차 = task_name, 회차
        self.values = values or {}
        self.title.setText(f"{self.workflow.name}  ({회차})")
        self._rebuild()

    def _rebuild(self) -> None:
        for layout in (self.auto_layout, self.manual_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._checks.clear()
        if self.workflow is None:
            return

        for step in self.workflow.auto:
            label = QLabel(f"  ☐ {self.workflow.format(step, self.values)}")
            label.setWordWrap(True)
            self.auto_layout.addWidget(label)

        saved = self.state.get_checks(self.task_name, self.회차)
        for item in self.workflow.manual:
            cb = QCheckBox(self.workflow.format(item["text"], self.values))
            cb.setChecked(bool(saved.get(item["id"], False)))
            if item.get("hint"):
                cb.setToolTip(self.workflow.format(item["hint"], self.values))
            cb.stateChanged.connect(
                lambda _s, i=item["id"], c=cb: self._on_check(i, c.isChecked()))
            cb.setStyleSheet("QCheckBox { padding: 2px; }")
            self.manual_layout.addWidget(cb)
            self._checks[item["id"]] = cb

    def _on_check(self, item_id: str, done: bool) -> None:
        self.state.set_check(self.task_name, self.회차, item_id, done)

    def mark_auto_done(self) -> None:
        for i in range(self.auto_layout.count()):
            w = self.auto_layout.itemAt(i).widget()
            if isinstance(w, QLabel):
                w.setText(w.text().replace("☐", "✔"))

    @property
    def 미완료(self) -> list[str]:
        return [cb.text() for cb in self._checks.values() if not cb.isChecked()]
