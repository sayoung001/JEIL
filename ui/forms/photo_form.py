"""사진 분류 폼 (SPEC §24.7) — scan() 결과를 표로 보여주고 run() 을 호출한다."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (QHeaderView, QLabel, QMessageBox, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from core.config import Config
from tasks.photo_sorter import PhotoSorter, load_config

log = logging.getLogger(__name__)


class PhotoSortForm(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self._plans: list = []
        self._blocked: list[str] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("사진 분류 — [미리보기] 로 계획을 확인한 뒤 [실행]"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["카테고리", "폴더", "파일", "크기"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(140)
        layout.addWidget(QLabel("보류 · 경고"))
        layout.addWidget(self.notes)

    def _sorter(self) -> PhotoSorter:
        return PhotoSorter(load_config(self.cfg))

    def preview(self) -> None:
        try:
            self._plans, self._blocked = self._sorter().scan()
        except Exception as e:
            log.exception("사진 스캔 실패")
            QMessageBox.critical(self, "사진 분류", f"스캔 실패: {e}")
            return
        self.table.setRowCount(len(self._plans))
        for i, p in enumerate(self._plans):
            values = [p.category, p.target_folder, p.src.name,
                      f"{p.src_bytes / 1024:.0f} KB"]
            for j, v in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(v))
        self.notes.setPlainText("\n".join(self._blocked)
                                or ("분류할 사진이 없습니다." if not self._plans else ""))

    def run(self) -> None:
        if not self._plans and not self._blocked:
            self.preview()
        if not self._plans:
            QMessageBox.information(self, "사진 분류",
                                    "\n".join(self._blocked) or "분류할 사진이 없습니다.")
            return
        result = self._sorter().run(self._plans, self._blocked)
        lines = [result.요약]
        lines += [f"[실패] {p.name}: {e}" for p, e in result.failed]
        lines += [f"[보류] {b}" for b in result.blocked]
        if result.purged_backups:
            lines.append(f"오래된 백업 {len(result.purged_backups)}개 삭제")
        self.notes.setPlainText("\n".join(lines))
        QMessageBox.information(self, "사진 분류", result.요약)
        self.preview()
