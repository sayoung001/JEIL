"""서류 투입 화면 — 원본을 넣으면 세 갈래로 갈라 보낸다.

압축분류 · 원본분류 · 성적서 를 색으로 구분해 보여 주고, 성적서는 읽어낸
항목을 그 자리에서 확인할 수 있게 한다. **확인하지 않은 값은 대장에 넣지 않는다.**
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget)

from core.config import Config
from tasks.document_intake import DocumentIntake, IntakeItem, Lane

log = logging.getLogger(__name__)

레인색 = {
    Lane.압축분류: QColor(226, 240, 255),      # 파랑 — 우리가 찍은 사진, 압축해도 된다
    Lane.원본분류: QColor(255, 240, 226),      # 주황 — 남의 증빙, 손대지 않는다
    Lane.성적서:   QColor(230, 250, 230),      # 초록 — 읽어서 채운다
}


class IntakeForm(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self._items: list[IntakeItem] = []
        self._blocked: list[str] = []

        layout = QVBoxLayout(self)
        head = QLabel(
            "원본을 <b>서류투입</b> 폴더에 넣고 [미리보기] 를 누르세요.<br>"
            "<span style='color:#356'>■ 압축분류</span> 각종시험·자재검수 사진 — 메타데이터 제거 + 압축&nbsp;&nbsp;"
            "<span style='color:#853'>■ 원본분류</span> 의뢰시험 증빙 — 원본 그대로&nbsp;&nbsp;"
            "<span style='color:#363'>■ 성적서</span> 글자 추출 + 자동 완성")
        head.setTextFormat(Qt.RichText)
        head.setWordWrap(True)
        layout.addWidget(head)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["처리", "분류", "파일", "읽어낸 내용", "보낼 곳"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemSelectionChanged.connect(self._show_detail)
        layout.addWidget(self.table, 2)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(160)
        layout.addWidget(QLabel("선택한 문서에서 읽어낸 항목"))
        layout.addWidget(self.detail, 1)

        row = QHBoxLayout()
        self.btn_ledger = QPushButton("선택한 성적서를 대장에 기입")
        self.btn_ledger.setToolTip("재하·MT 성적서를 O-01,04 실시대장에 넣습니다.\n"
                                   "읽어낸 값을 먼저 확인하세요.")
        self.btn_ledger.clicked.connect(self.write_ledger)
        self.btn_ledger.setEnabled(False)
        row.addWidget(self.btn_ledger)
        row.addStretch(1)
        layout.addLayout(row)

        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(110)
        layout.addWidget(QLabel("보류 · 경고"))
        layout.addWidget(self.notes)

    # -----------------------------------------------------------------
    def _intake(self) -> DocumentIntake:
        return DocumentIntake(self.cfg)

    def preview(self) -> None:
        try:
            intake = self._intake()
            if not intake.root.exists():
                self.notes.setPlainText(
                    f"투입 폴더가 없습니다: {intake.root}\n"
                    "이 폴더를 만들고 안에 카테고리 폴더를 두세요:\n"
                    + "\n".join(f"  {c.name}  ({c.lane.value})" for c in intake.categories))
                return
            self._items, self._blocked = intake.scan()
        except Exception as e:
            log.exception("서류 훑기 실패")
            QMessageBox.critical(self, "서류 투입", f"훑기에 실패했습니다: {e}")
            return

        self.table.setRowCount(len(self._items))
        for i, item in enumerate(self._items):
            값 = [item.처리, item.category, item.src.name, item.요약, str(item.dest)]
            for j, v in enumerate(값):
                cell = QTableWidgetItem(v)
                cell.setBackground(레인색[item.lane])
                self.table.setItem(i, j, cell)
        self.table.resizeColumnsToContents()

        경고 = list(self._blocked)
        for item in self._items:
            for w in (item.parsed.경고 if item.parsed else []):
                경고.append(f"{item.src.name}: {w}")
        self.notes.setPlainText("\n".join(경고)
                                or ("넣을 서류가 없습니다." if not self._items else "이상 없음"))

    def _selected(self) -> IntakeItem | None:
        rows = {i.row() for i in self.table.selectedItems()}
        if len(rows) != 1:
            return None
        row = rows.pop()
        return self._items[row] if 0 <= row < len(self._items) else None

    def _show_detail(self) -> None:
        item = self._selected()
        self.btn_ledger.setEnabled(
            item is not None and item.parsed is not None
            and item.parsed.종류 in ("재하성적서", "MT성적서"))
        if item is None or item.parsed is None:
            self.detail.clear()
            return
        doc = item.parsed
        줄 = [f"종류: {doc.종류}   확신도: {doc.확신도:.2f}",
              f"읽은 방식: {item.extracted}" if item.extracted else ""]
        줄 += [f"  {k} = {v}" for k, v in doc.항목.items() if v not in (None, "", [])]
        if doc.경고:
            줄 += ["", "확인 필요:"] + [f"  ! {w}" for w in doc.경고]
        self.detail.setPlainText("\n".join(x for x in 줄 if x))

    def run(self) -> None:
        if not self._items and not self._blocked:
            self.preview()
        if not self._items:
            QMessageBox.information(self, "서류 투입",
                                    "\n".join(self._blocked) or "넣을 서류가 없습니다.")
            return
        갈래 = {l: sum(1 for i in self._items if i.lane is l) for l in Lane}
        if QMessageBox.question(
                self, "서류 투입",
                f"{len(self._items)}건을 처리합니다.\n\n"
                f"  압축+메타제거 {갈래[Lane.압축분류]}건\n"
                f"  원본 보존     {갈래[Lane.원본분류]}건\n"
                f"  글자 추출     {갈래[Lane.성적서]}건") != QMessageBox.Yes:
            return
        result = self._intake().run(self._items, self._blocked)
        줄 = [result.요약]
        줄 += [f"[실패] {p.name}: {e}" for p, e in result.failed]
        줄 += [f"[보류] {b}" for b in result.blocked]
        self.notes.setPlainText("\n".join(줄))
        QMessageBox.information(self, "서류 투입", result.요약)
        self.preview()

    # -----------------------------------------------------------------
    def write_ledger(self) -> None:
        """읽어낸 성적서를 O-01,04 실시대장에 넣는다."""
        item = self._selected()
        if item is None or item.parsed is None:
            return
        from tasks.outsourced_report import OutsourcedReportTask, ReportEntry

        확인 = QMessageBox.question(
            self, "값 확인",
            "읽어낸 값이 성적서와 맞습니까?\n\n" + self.detail.toPlainText()[:600]
            + "\n\n[Yes] 를 누르면 확인한 것으로 보고 대장에 넣습니다.")
        entry = ReportEntry(doc=item.parsed, 확인함=확인 == QMessageBox.Yes)
        if not entry.확인함:
            return
        task = OutsourcedReportTask(self.cfg)
        result = task.run(entry)
        if result:
            QMessageBox.information(self, "대장 기입", "O-01,04 실시대장에 기록했습니다.")
        else:
            QMessageBox.critical(self, "대장 기입",
                                 result.메시지 + "\n\n" + "\n".join(result.경고))
