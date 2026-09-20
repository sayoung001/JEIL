"""T-01 자재검수 입력 폼 (SPEC §7)."""
from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from core.config import Config
from core.context import PreviewContext
from core.models import DeliveryRow, InspectionRound, MaterialRow
from tasks.material_inspection import (CHECK_COLS, CHECK_FIRST_ROW, CHECK_SHEET,
                                       COVER_SHEET, COVER_WIDTH, 갑지_블록순번)
from core.util import as_number

log = logging.getLogger(__name__)

자재열 = ["품명", "규격", "단위", "전일수량", "반입수량", "비고"]
송장열 = ["송장일자", "업체명", "규격(A)", "규격(m)", "구분", "수량(본)", "500밴드", "600밴드"]


class MaterialInspectionForm(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        layout = QVBoxLayout(self)

        head = QFormLayout()
        self.spin_차수 = QSpinBox()
        self.spin_차수.setRange(1, 999)
        self.date_반입 = QDateEdit(QDate.currentDate())
        self.date_반입.setCalendarPopup(True)
        self.date_반입.setDisplayFormat("yyyy-MM-dd")
        self.combo_공종 = QComboBox()
        self.combo_공종.addItems(["건축", "토목"])
        self.combo_감리 = QComboBox()
        self.combo_감리.addItems([str(n) for n in cfg.people.get("감리원_건축", ["김운종"])])
        self.combo_결과 = QComboBox()
        self.combo_결과.addItems(["적합", "부적합"])
        self.edit_특기 = QLineEdit()
        head.addRow("차수", self.spin_차수)
        head.addRow("반입일자", self.date_반입)
        head.addRow("공종", self.combo_공종)
        head.addRow("담당감리원", self.combo_감리)
        head.addRow("검수결과", self.combo_결과)
        head.addRow("특기사항", self.edit_특기)
        layout.addLayout(head)

        self.자재 = self._table("자재 목록 (최대 4)", 자재열, layout)
        self.송장 = self._table("송장 목록", 송장열, layout)
        self._add_material_row()
        self._add_delivery_row()

        note = QLabel("차수와 전일수량은 [자동 채움] 으로 실제 파일에서 읽어 옵니다.")
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

    def _table(self, title: str, headers: list[str], parent: QVBoxLayout) -> QTableWidget:
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(table)
        row = QHBoxLayout()
        add = QPushButton("+ 행 추가")
        rm = QPushButton("- 행 삭제")
        add.clicked.connect(lambda: self._append(table))
        rm.clicked.connect(lambda: table.removeRow(table.currentRow())
                           if table.currentRow() >= 0 else None)
        if "자재" in title:
            auto = QPushButton("자동 채움")
            auto.clicked.connect(self.autofill)
            row.addWidget(auto)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        v.addLayout(row)
        parent.addWidget(box)
        return table

    def _append(self, table: QTableWidget) -> None:
        r = table.rowCount()
        table.insertRow(r)
        for c in range(table.columnCount()):
            table.setItem(r, c, QTableWidgetItem(""))

    def _add_material_row(self) -> None:
        self._append(self.자재)
        for c, v in enumerate(["PHC파일", "Ø500-15M", "본", "-", "", ""]):
            self.자재.setItem(0, c, QTableWidgetItem(v))

    def _add_delivery_row(self) -> None:
        self._append(self.송장)
        for c, v in enumerate([str(date.today()), "", "500", "15", "상", "", "", ""]):
            self.송장.setItem(0, c, QTableWidgetItem(v))

    # -----------------------------------------------------------------
    def autofill(self) -> None:
        """차수 = ★수불부 K열 최대 + 1, 전일수량 = 갑지 직전 블록 누계 (§5.1)."""
        try:
            ctx = PreviewContext(self.cfg, only={"supply_check": [CHECK_SHEET],
                                                 "request_cover": [COVER_SHEET]})
            check = ctx.book("supply_check").sheet(CHECK_SHEET)
            last = check.last_filled_row(CHECK_COLS["송장일자"], CHECK_FIRST_ROW)
            차수들 = [as_number(v) for v in
                     check.read_col(CHECK_COLS["차수"], CHECK_FIRST_ROW, last)]
            최대 = max((int(v) for v in 차수들 if v is not None), default=0)
            self.spin_차수.setValue(최대 + 1)

            cover = ctx.book("request_cover").sheet(COVER_SHEET)
            c0 = 1 + (갑지_블록순번(최대) - 1) * COVER_WIDTH
            누계 = as_number(cover.read(9, c0 + 7))
            if 누계 is not None and self.자재.rowCount():
                self.자재.setItem(0, 3, QTableWidgetItem(str(int(누계))))
        except Exception as e:
            log.warning("자동 채움 실패", exc_info=True)
            self.자재.setToolTip(f"자동 채움 실패: {e}")

    def 차수(self) -> int:
        return self.spin_차수.value()

    def values(self) -> dict:
        d = self.date_반입.date().toPython()
        return {"차수": self.차수(), "날짜": f"{d:%m%d}",
                "YYYYMMDD": f"{d:%Y%m%d}", "YYMMDD": f"{d:%y%m%d}"}

    def build(self) -> InspectionRound:
        """표를 모델로. 비어 있거나 숫자가 아니면 여기서 막는다."""
        반입일 = self.date_반입.date().toPython()
        자재: list[MaterialRow] = []
        for r in range(self.자재.rowCount()):
            품명 = self._cell(self.자재, r, 0)
            if not 품명:
                continue
            자재.append(MaterialRow(
                품명=품명, 규격=self._cell(self.자재, r, 1),
                단위=self._cell(self.자재, r, 2) or "본",
                전일수량=self._int(self.자재, r, 3, allow_dash=True),
                반입수량=self._int(self.자재, r, 4),
                비고=self._cell(self.자재, r, 5).replace("\\n", "\n")))
        송장: list[DeliveryRow] = []
        for r in range(self.송장.rowCount()):
            업체 = self._cell(self.송장, r, 1)
            if not 업체:
                continue
            송장일 = self._date(self.송장, r, 0) or 반입일
            송장.append(DeliveryRow(
                송장일자=송장일, 반입일자=반입일, 업체명=업체,
                규격_A=self._int(self.송장, r, 2) or 500,
                규격_m=self._int(self.송장, r, 3) or 15,
                구분=self._cell(self.송장, r, 4) or "상",
                수량_본=self._int(self.송장, r, 5),
                밴드500=self._int(self.송장, r, 6) or None,
                밴드600=self._int(self.송장, r, 7) or None))
        if not 자재:
            raise ValueError("자재를 한 건 이상 입력하세요.")
        if not 송장:
            raise ValueError("송장을 한 건 이상 입력하세요.")
        people = self.cfg.people
        return InspectionRound(
            차수=self.차수(), 반입일자=반입일, 공종=self.combo_공종.currentText(),
            검수결과=self.combo_결과.currentText(), 특기사항=self.edit_특기.text(),
            담당자=str(people.get("담당자", "이승현")),
            현장대리인=str(people.get("현장대리인", "이용택")),
            담당감리원=self.combo_감리.currentText(),
            총괄감리원=str(people.get("총괄감리원", "김번환")),
            현장약칭=str(self.cfg.get("site.약칭", "다인영종")),
            첨부물=str(self.cfg.defaults.get("첨부물", "■ 출하송장, ■ 사진대지 등")),
            자재목록=자재, 송장목록=송장)

    # -- 셀 읽기 -------------------------------------------------------
    @staticmethod
    def _cell(table: QTableWidget, r: int, c: int) -> str:
        item = table.item(r, c)
        return item.text().strip() if item else ""

    def _int(self, table: QTableWidget, r: int, c: int, *, allow_dash: bool = False) -> int:
        text = self._cell(table, r, c)
        if not text or (allow_dash and text == "-"):
            return "-" if allow_dash and text == "-" else 0
        v = as_number(text)
        if v is None:
            raise ValueError(f"{table.horizontalHeaderItem(c).text()} "
                             f"{r + 1}행이 숫자가 아닙니다: {text!r}")
        return int(v)

    def _date(self, table: QTableWidget, r: int, c: int) -> date | None:
        from core.util import as_date

        return as_date(self._cell(table, r, c))
