"""시험 입력 폼 — T-03 겉모양 / T-04 밀크 / T-05 BSCW·JSP (SPEC §16.1, §17.1, §18.1).

세 시험이 입력 항목만 다르고 흐름은 같아서 한 폼에서 종류를 고르게 했다.
"""
from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from core.config import Config
from core.context import PreviewContext
from core.models import (CompressiveTest, CompStage, MilkSpecimen, MilkTest, Series,
                         ShapeSample, ShapeTest)
from tasks.bscw_jsp import CompressiveTask
from tasks.phc_milk import PhcMilkTask
from tasks.phc_shape import PhcShapeTask

log = logging.getLogger(__name__)

종류목록 = [("PHC 겉모양·치수 (Q-Q-02)", Series.PHC_SHAPE),
            ("PHC 밀크 (Q-Q-01)", Series.PHC_MILK),
            ("BSCW 압축강도 (Q-Q-03)", Series.BSCW),
            ("JSP 압축강도 (Q-Q-04)", Series.JSP)]


def _num(minimum=0.0, maximum=1e6, decimals=2, value=0.0) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(minimum, maximum)
    w.setDecimals(decimals)
    w.setValue(value)
    return w


class TestForm(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        layout = QVBoxLayout(self)

        top = QFormLayout()
        self.combo_종류 = QComboBox()
        self.combo_종류.addItems([label for label, _ in 종류목록])
        self.combo_종류.currentIndexChanged.connect(self._on_kind)
        self.spin_번호 = QSpinBox()
        self.spin_번호.setRange(1, 999)
        self.btn_auto = QPushButton("번호 자동")
        self.btn_auto.clicked.connect(self.autofill)
        row = QHBoxLayout()
        row.addWidget(self.spin_번호, 1)
        row.addWidget(self.btn_auto)
        top.addRow("시험 종류", self.combo_종류)
        top.addRow("시험번호", row)
        layout.addLayout(top)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._shape_page())
        self.stack.addWidget(self._milk_page())
        self.stack.addWidget(self._comp_page())
        layout.addWidget(self.stack, 1)
        layout.addStretch(1)

    # -----------------------------------------------------------------
    def _shape_page(self) -> QWidget:
        page = QWidget()
        f = QFormLayout(page)
        self.s_채취일 = QDateEdit(QDate.currentDate())
        self.s_채취일.setCalendarPopup(True)
        self.s_채취일.setDisplayFormat("yyyy-MM-dd")
        self.s_반입일 = QDateEdit(QDate.currentDate())
        self.s_반입일.setCalendarPopup(True)
        self.s_반입일.setDisplayFormat("yyyy-MM-dd")
        self.s_업체 = QComboBox()
        self.s_업체.addItems(self.cfg.vendors.canonical_names)
        self.s_A = QSpinBox()
        self.s_A.setRange(100, 2000)
        self.s_A.setValue(500)
        self.s_m = QSpinBox()
        self.s_m.setRange(1, 30)
        self.s_m.setValue(15)
        self.s_반입량 = QSpinBox()
        self.s_반입량.setRange(0, 9999)
        self.s_길이 = _num(0, 100000, 0, 15017)
        self.s_지름 = _num(0, 10000, 0, 503)
        self.s_두께 = _num(0, 1000, 0, 84)
        self.s_모양 = QComboBox()
        self.s_모양.addItems(["이상없음", "이상있음"])
        self.s_겉모양 = QComboBox()
        self.s_겉모양.addItems(["이상없음", "이상있음"])
        self.s_감리 = QComboBox()
        self.s_감리.addItems([str(n) for n in self.cfg.people.get("감리원_건축", ["김운종"])])
        for label, w in [("시료채취일 (=시험일자)", self.s_채취일), ("시료반입일", self.s_반입일),
                         ("생산업체", self.s_업체), ("규격 A", self.s_A), ("규격 m", self.s_m),
                         ("시료반입량 (본)", self.s_반입량), ("길이 (㎜)", self.s_길이),
                         ("바깥지름 (㎜)", self.s_지름), ("두께 (㎜)", self.s_두께),
                         ("모양", self.s_모양), ("겉모양", self.s_겉모양), ("감리원", self.s_감리)]:
            f.addRow(label, w)
        f.addRow(QLabel("판정은 허용차로 자동 계산됩니다 (§16.3)."))
        return page

    def _milk_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        f = QFormLayout()
        self.m_채취일 = QDateEdit(QDate.currentDate())
        self.m_채취일.setCalendarPopup(True)
        self.m_채취일.setDisplayFormat("yyyy-MM-dd")
        self.m_시험일 = QDateEdit(QDate.currentDate())
        self.m_시험일.setCalendarPopup(True)
        self.m_시험일.setDisplayFormat("yyyy-MM-dd")
        self.m_업체 = QComboBox()
        self.m_업체.setEditable(True)
        self.m_업체.addItem(str(self.cfg.defaults.get("밀크_시공업체", "이산지반건설")))
        f.addRow("시료채취일", self.m_채취일)
        f.addRow("시험일자", self.m_시험일)
        f.addRow("시공업체", self.m_업체)
        v.addLayout(f)

        self.m_cells: dict[str, QDoubleSpinBox] = {}
        for 시료 in ("S-1", "S-2"):
            box = QGroupBox(시료)
            bf = QFormLayout(box)
            for 항목 in ("총중량", "건조중량", "용기무게"):
                w = _num(0, 100000, 1)
                self.m_cells[f"{시료}{항목}"] = w
                bf.addRow(f"{항목} (g)", w)
            v.addWidget(box)
        v.addWidget(QLabel("물시멘트비·판정은 수식으로 계산됩니다 (기준 83% 이하)."))
        return page

    def _comp_page(self) -> QWidget:
        page = QWidget()
        f = QFormLayout(page)
        self.c_단계 = QComboBox()
        self.c_단계.addItems(["채취 등록 (NEW)", "7일 강도 입력", "28일 강도 입력"])
        self.c_채취일 = QDateEdit(QDate.currentDate())
        self.c_채취일.setCalendarPopup(True)
        self.c_채취일.setDisplayFormat("yyyy-MM-dd")
        self.c_목록번호 = QSpinBox()
        self.c_목록번호.setRange(1, 36)
        self.c_업체 = QComboBox()
        self.c_업체.setEditable(True)
        self.c_업체.addItem(str(self.cfg.defaults.get("토목_시공업체", "한성토건")))
        self.c_감리 = QComboBox()
        self.c_감리.addItems([str(n) for n in self.cfg.people.get("감리원_토목", ["김남일"])])
        f.addRow("단계", self.c_단계)
        f.addRow("채취일 (=타설일)", self.c_채취일)
        f.addRow("시험목록 번호", self.c_목록번호)
        f.addRow("시공업체", self.c_업체)
        f.addRow("감리원", self.c_감리)
        self.c_values: list[QDoubleSpinBox] = []
        for i in range(3):
            w = _num(0, 200, 2)
            self.c_values.append(w)
            f.addRow(f"측정값 S-{i + 1} (MPa)", w)
        f.addRow(QLabel("평균은 소수 2자리로 통일됩니다. 대장 기록은 28일 단계에서만."))
        return page

    # -----------------------------------------------------------------
    @property
    def series(self) -> Series:
        return 종류목록[self.combo_종류.currentIndex()][1]

    def _on_kind(self, index: int) -> None:
        s = 종류목록[index][1]
        self.stack.setCurrentIndex({Series.PHC_SHAPE: 0, Series.PHC_MILK: 1}.get(s, 2))

    def task(self):
        s = self.series
        if s is Series.PHC_SHAPE:
            return PhcShapeTask(self.cfg)
        if s is Series.PHC_MILK:
            return PhcMilkTask(self.cfg)
        return CompressiveTask(self.cfg, s)

    def autofill(self) -> None:
        try:
            task = self.task()
            ctx = PreviewContext(self.cfg, only=task.preview_sheets())
            self.spin_번호.setValue(task.next_number(ctx))
        except Exception as e:
            log.warning("시험번호 자동 채움 실패", exc_info=True)
            self.spin_번호.setToolTip(f"자동 채움 실패: {e}")

    def workflow_file(self) -> str:
        return {Series.PHC_SHAPE: "겉모양치수.yaml",
                Series.PHC_MILK: "밀크.yaml"}.get(self.series, "압축강도.yaml")

    def values(self) -> dict:
        return {"회차": f"{self.spin_번호.value():02d}", "계열": self.series.value}

    def build(self):
        s = self.series
        n = self.spin_번호.value()
        if s is Series.PHC_SHAPE:
            return ShapeTest(
                번호=n, 시료채취일=self.s_채취일.date().toPython(),
                업체명=self.s_업체.currentText(), 규격_A=self.s_A.value(),
                규격_m=self.s_m.value(), 시료반입일=self.s_반입일.date().toPython(),
                시료반입량_본=self.s_반입량.value(), 감리원=self.s_감리.currentText(),
                시료목록=[ShapeSample(1, 길이=self.s_길이.value(),
                                     바깥지름=self.s_지름.value(), 두께=self.s_두께.value(),
                                     모양=self.s_모양.currentText(),
                                     겉모양=self.s_겉모양.currentText())])
        if s is Series.PHC_MILK:
            def spec(prefix: str) -> MilkSpecimen:
                return MilkSpecimen(
                    총중량=self.m_cells[f"{prefix}총중량"].value(),
                    건조중량=self.m_cells[f"{prefix}건조중량"].value(),
                    용기무게=self.m_cells[f"{prefix}용기무게"].value())
            return MilkTest(번호=n, 시료채취일=self.m_채취일.date().toPython(),
                            시험일자=self.m_시험일.date().toPython(),
                            S1=spec("S-1"), S2=spec("S-2"),
                            시공업체=self.m_업체.currentText())
        stage = [CompStage.NEW, CompStage.AWAIT_7D, CompStage.AWAIT_28D][
            self.c_단계.currentIndex()]
        values = [w.value() for w in self.c_values]
        return CompressiveTest(
            series=s, 번호=n, 채취일=self.c_채취일.date().toPython(),
            목록행번호=self.c_목록번호.value(), 시공업체=self.c_업체.currentText(),
            감리원=self.c_감리.currentText(), stage=stage,
            측정_7일=values if stage is CompStage.AWAIT_7D else [],
            측정_28일=values if stage is CompStage.AWAIT_28D else [])
