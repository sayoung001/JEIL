"""UI 구성 스모크 테스트.

폼이 실제로 만들어지고, 입력값이 모델로 제대로 변환되는지 본다.
(엑셀 파일이 없어도 화면은 떠야 한다 — 배지만 경고를 표시한다.)
"""
from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from core.models import CompStage, CompressiveTest, MilkTest, Series, ShapeTest
from core.state import State
from tests.fixtures import cfg


@pytest.fixture(scope="module")
def app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_자재검수_폼이_모델을_만든다(app):
    from ui.forms.material_form import MaterialInspectionForm

    form = MaterialInspectionForm(cfg())
    form.spin_차수.setValue(13)
    form.date_반입.setDate(QDate(2026, 9, 5))
    for c, v in enumerate(["PHC파일", "Ø500-15M", "본", "222", "24", "㈜한국파일/\\n아주산업㈜"]):
        form.자재.setItem(0, c, QTableWidgetItem(v))
    for c, v in enumerate(["2026-09-05", "한국파일", "500", "15", "상", "24", "", ""]):
        form.송장.setItem(0, c, QTableWidgetItem(v))

    data = form.build()
    assert data.차수 == 13
    assert data.반입일자 == date(2026, 9, 5)
    assert data.자재목록[0].전일수량 == 222
    assert data.자재목록[0].누계수량 == 246
    assert data.자재목록[0].비고 == "㈜한국파일/\n아주산업㈜"   # \n 은 실제 줄바꿈으로
    assert data.송장목록[0].업체명 == "한국파일"
    assert data.송장본합계 == data.반입수량합계 == 24


def test_자재검수_폼_숫자아닌_입력은_막는다(app):
    from ui.forms.material_form import MaterialInspectionForm

    form = MaterialInspectionForm(cfg())
    form.자재.setItem(0, 4, QTableWidgetItem("스물넷"))
    with pytest.raises(ValueError, match="숫자가 아닙니다"):
        form.build()


def test_시험폼_세_종류_모두_모델을_만든다(app):
    from ui.forms.test_form import TestForm

    form = TestForm(cfg())

    form.combo_종류.setCurrentIndex(0)              # 겉모양
    form.spin_번호.setValue(7)
    data = form.build()
    assert isinstance(data, ShapeTest) and data.번호 == 7
    assert data.시료종류 == "PHC파일-A500-15M"

    form.combo_종류.setCurrentIndex(1)              # 밀크
    form.spin_번호.setValue(4)
    form.m_cells["S-1총중량"].setValue(500)
    form.m_cells["S-1건조중량"].setValue(380)
    form.m_cells["S-1용기무게"].setValue(100)
    form.m_cells["S-2총중량"].setValue(490)
    form.m_cells["S-2건조중량"].setValue(380)
    form.m_cells["S-2용기무게"].setValue(100)
    data = form.build()
    assert isinstance(data, MilkTest)
    assert round(data.결과들[0], 1) == 42.9

    form.combo_종류.setCurrentIndex(2)              # BSCW
    form.spin_번호.setValue(9)
    form.c_단계.setCurrentIndex(1)                  # 7일 강도
    for i, v in enumerate((1.02, 1.00, 1.04)):
        form.c_values[i].setValue(v)
    data = form.build()
    assert isinstance(data, CompressiveTest)
    assert data.series is Series.BSCW
    assert data.stage is CompStage.AWAIT_7D
    assert data.평균_7일 == 1.02
    assert data.측정_28일 == []

    form.combo_종류.setCurrentIndex(3)              # JSP
    assert form.build().series is Series.JSP
    assert form.workflow_file() == "압축강도.yaml"


def test_메인창이_파일없이도_뜬다(app, tmp_path):
    from core.config import Config
    from ui.main_window import MainWindow

    c = cfg()                                    # 상태 파일이 실제 경로로 새지 않게
    raw = dict(c.raw)
    raw["paths"] = dict(raw["paths"])
    raw["paths"]["state_dir"] = str(tmp_path / "상태")
    win = MainWindow(Config(raw=raw), State(tmp_path / "state.json"))
    assert win.task_list.count() > 0
    # 파일이 없으니 배지에 경고가 뜨지만 창은 살아 있어야 한다
    assert win.badge.toPlainText()
    win.task_list.setCurrentRow(2)
    assert win.stack.currentIndex() == 2
    win.close()


def test_워크플로우_체크가_저장된다(app, tmp_path):
    from ui.workflow_panel import WorkflowPanel

    state = State(tmp_path / "state.json")
    panel = WorkflowPanel(state)
    panel.load("자재검수.yaml", "자재검수", 13, {"차수": 13, "날짜": "0905"})
    assert len(panel.미완료) == 6
    panel._checks["photo_paste"].setChecked(True)
    assert len(panel.미완료) == 5
    assert State(tmp_path / "state.json").get_checks("자재검수", 13)["photo_paste"] is True

    panel2 = WorkflowPanel(State(tmp_path / "state.json"))
    panel2.load("자재검수.yaml", "자재검수", 13, {"차수": 13})
    assert panel2._checks["photo_paste"].isChecked()      # 재시작해도 유지


def test_워크플로우_자리표시자가_채워진다(app, tmp_path):
    from ui.workflow_panel import WorkflowPanel

    panel = WorkflowPanel(State(tmp_path / "state.json"))
    panel.load("자재검수.yaml", "자재검수", 13,
               {"차수": 13, "날짜": "0905", "YYYYMMDD": "20260905", "YYMMDD": "260905"})
    texts = [cb.text() for cb in panel._checks.values()]
    hints = [cb.toolTip() for cb in panel._checks.values()]
    assert any("0905 시트" in t for t in texts)
    assert any("QG03-13 260905" in h for h in hints)     # 힌트는 툴팁으로 간다
    assert not any("{" in t for t in texts)
