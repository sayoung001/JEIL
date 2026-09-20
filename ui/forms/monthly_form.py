"""월간 실적보고서 화면.

집계 결과와 **어디서 나온 숫자인지(출처)** 를 함께 보여 준다.
감리 제출 문서라 "왜 4건인가" 를 바로 짚을 수 있어야 한다.
"""
from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from core.config import Config
from core.monthly_report import MonthlyReporter, MonthlyTally

log = logging.getLogger(__name__)


class MonthlyForm(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self._전월: MonthlyTally | None = None
        self._금월: MonthlyTally | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>실시대장을 세어 보고서를 채웁니다.</b> 손으로 세지 않습니다.<br>"
            "숫자가 이상하면 대장이 이상한 것입니다. 출처 열에서 바로 확인하세요."))

        top = QHBoxLayout()
        self.combo_월 = QComboBox()
        self.combo_월.setEditable(True)
        self.btn_달목록 = QPushButton("대장에서 달 찾기")
        self.btn_달목록.clicked.connect(self.load_months)
        self.chk_누계 = QCheckBox("누계도 쓰기")
        self.chk_누계.setChecked(True)
        self.chk_경고무시 = QCheckBox("경고 무시하고 진행")
        self.chk_경고무시.setToolTip("세지 못한 종목이 있어도 그대로 씁니다.\n"
                                     "보고서 건수가 모자라게 되니 권하지 않습니다.")
        top.addWidget(QLabel("대상 월"))
        top.addWidget(self.combo_월, 1)
        top.addWidget(self.btn_달목록)
        top.addWidget(self.chk_누계)
        top.addWidget(self.chk_경고무시)
        layout.addLayout(top)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["종목", "금월 실시", "합격", "불합격", "재시험", "누계 실시", "출처"])
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        layout.addWidget(self.table, 2)

        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(130)
        layout.addWidget(QLabel("확인 필요"))
        layout.addWidget(self.notes)

        self.load_months()

    # -----------------------------------------------------------------
    def _reporter(self) -> MonthlyReporter:
        return MonthlyReporter(self.cfg)

    def load_months(self) -> None:
        try:
            달들 = self._reporter().있는_달()
        except Exception as e:
            log.warning("달 목록을 읽지 못했습니다", exc_info=True)
            self.notes.setPlainText(f"대장을 읽지 못했습니다: {e}")
            return
        현재 = self.combo_월.currentText()
        self.combo_월.clear()
        self.combo_월.addItems(달들)
        if 현재 in 달들:
            self.combo_월.setCurrentText(현재)
        elif 달들:
            self.combo_월.setCurrentText(달들[-1])
        else:
            today = date.today()
            self.combo_월.setCurrentText(f"{today:%y}.{today:%m}")
            self.notes.setPlainText("대장에서 월 시트를 찾지 못했습니다. 경로를 확인하세요.")

    @property
    def 월(self) -> str:
        return self.combo_월.currentText().strip()

    def preview(self) -> None:
        try:
            self._전월, self._금월 = self._reporter().누계(self.월)
        except Exception as e:
            log.exception("집계 실패")
            QMessageBox.critical(self, "실적보고서", f"집계에 실패했습니다: {e}")
            return
        누계 = self._전월.더하기(self._금월)

        이름들 = sorted(self._금월.종목)
        self.table.setRowCount(len(이름들))
        for i, 이름 in enumerate(이름들):
            값 = self._금월.종목[이름]
            누 = 누계.종목.get(이름)
            출처 = ", ".join(값.출처[:4]) + (" …" if len(값.출처) > 4 else "")
            for j, v in enumerate([이름, 값.실시, 값.합격, 값.불합격, 값.재시험,
                                   누.실시 if 누 else "", 출처]):
                cell = QTableWidgetItem(str(v))
                if j and j < 6:
                    cell.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, j, cell)
        self.table.resizeColumnsToContents()

        경고 = [*dict.fromkeys([*self._전월.경고, *self._금월.경고])]
        self.notes.setPlainText(
            "\n".join(경고) if 경고
            else f"{self.월}: {self._금월.총건수}건. 이상 없음.")

    def run(self) -> None:
        if self._금월 is None:
            self.preview()
        if self._금월 is None or not self._금월.종목:
            QMessageBox.information(self, "실적보고서",
                                    f"{self.월} 에 집계된 시험이 없습니다.")
            return
        from tasks.monthly_report import MonthlyInput, MonthlyReportTask

        data = MonthlyInput(월=self.월, 누계쓰기=self.chk_누계.isChecked(),
                            경고무시=self.chk_경고무시.isChecked(),
                            전월=self._전월, 금월=self._금월)
        미리 = "\n".join(f"  {k}: {v.실시}건" for k, v in sorted(self._금월.종목.items()))
        if QMessageBox.question(
                self, "실적보고서",
                f"{self.월} 실적을 보고서에 씁니다.\n\n{미리}") != QMessageBox.Yes:
            return
        result = MonthlyReportTask(self.cfg).run(data)
        if result:
            QMessageBox.information(self, "실적보고서", "보고서에 기입했습니다.")
        else:
            QMessageBox.critical(self, "실적보고서",
                                 result.메시지 + "\n\n" + "\n".join(result.경고))
