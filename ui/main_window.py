"""메인 화면 (SPEC §7).

    ┌──────────────┬──────────────────────┬──────────────────┐
    │  태스크 목록  │      입력 영역        │  워크플로우 패널  │
    └──────────────┴──────────────────────┴──────────────────┘
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QSplitter,
                               QStackedWidget, QStatusBar, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from core.backup import BackupManager
from core.config import Config
from core.consistency import ConsistencyChecker
from core.context import TaskResult
from core.due_checker import DueChecker
from core.state import State
from tasks.material_inspection import MaterialInspectionTask

from .forms.material_form import MaterialInspectionForm
from .forms.photo_form import PhotoSortForm
from .forms.test_form import TestForm
from .workflow_panel import WorkflowPanel

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, state: State):
        super().__init__()
        self.cfg = cfg
        self.state = state
        self.setWindowTitle("품질 업무 자동화")
        self.resize(1280, 800)

        self._build_ui()
        self.refresh_alerts()

        # 매일 07:00 자동 재판정 (§16.0). 프로그램이 꺼져 있었으면 다음 실행 때 갱신된다.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._maybe_refresh)
        self._timer.start(60_000)

    # =================================================================
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # --- 좌: 태스크 목록 ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("태스크"))
        self.task_list = QListWidget()
        for label, enabled in [
            ("▸ 자재검수 (PHC파일)", True),
            ("▸ 사진 분류", True),
            ("▸ 시험 (겉모양·밀크·압축강도)", True),
            ("── 2차 예정 ──", False),
            ("▹ 철근", False),
            ("▹ 레미콘", False),
            ("▹ 단열재", False),
        ]:
            item = QListWidgetItem(label)
            if not enabled:
                item.setFlags(Qt.NoItemFlags)
            self.task_list.addItem(item)
        self.task_list.currentRowChanged.connect(self._on_task_changed)
        lv.addWidget(self.task_list, 1)

        self.badge = QTextEdit()
        self.badge.setReadOnly(True)
        self.badge.setMaximumHeight(220)
        self.badge.setStyleSheet("font-family: monospace; font-size: 11px;")
        lv.addWidget(QLabel("시험 도래 현황"))
        lv.addWidget(self.badge)

        row = QHBoxLayout()
        refresh = QPushButton("새로고침")
        refresh.clicked.connect(self.refresh_alerts)
        check = QPushButton("정합성 검사")
        check.clicked.connect(self.run_consistency)
        row.addWidget(refresh)
        row.addWidget(check)
        lv.addLayout(row)
        splitter.addWidget(left)

        # --- 중: 입력 영역 ---
        center = QWidget()
        cv = QVBoxLayout(center)
        self.stack = QStackedWidget()
        self.material_form = MaterialInspectionForm(self.cfg)
        self.photo_form = PhotoSortForm(self.cfg)
        self.test_form = TestForm(self.cfg)
        self.stack.addWidget(self.material_form)
        self.stack.addWidget(self.photo_form)
        self.stack.addWidget(self.test_form)
        cv.addWidget(self.stack, 1)

        self.preview_table = QTableWidget(0, 5)
        self.preview_table.setHorizontalHeaderLabels(["파일", "시트", "셀", "종류", "값"])
        self.preview_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        cv.addWidget(QLabel("미리보기 — 실제로 어느 셀에 무엇이 들어가는가"))
        cv.addWidget(self.preview_table, 1)

        buttons = QHBoxLayout()
        self.btn_preview = QPushButton("미리보기")
        self.btn_preview.clicked.connect(self.on_preview)
        self.btn_run = QPushButton("실행")
        self.btn_run.clicked.connect(self.on_run)
        self.btn_undo = QPushButton("되돌리기 ▾")
        self.btn_undo.clicked.connect(self.on_undo)
        buttons.addWidget(self.btn_preview)
        buttons.addWidget(self.btn_run)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_undo)
        cv.addLayout(buttons)
        splitter.addWidget(center)

        # --- 우: 워크플로우 ---
        self.workflow = WorkflowPanel(self.state)
        splitter.addWidget(self.workflow)
        splitter.setSizes([260, 720, 300])
        self.setCentralWidget(splitter)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        status = QStatusBar()
        status.addPermanentWidget(self.progress)
        self.setStatusBar(status)
        self.status("대기 중")
        self.task_list.setCurrentRow(0)

    def status(self, text: str) -> None:
        self.statusBar().showMessage(f"상태:  {text}")

    # =================================================================
    #: 태스크 목록 행 -> 입력 폼
    ROW_MATERIAL, ROW_PHOTO, ROW_TEST = 0, 1, 2

    def _on_task_changed(self, row: int) -> None:
        self.stack.setCurrentIndex(min(max(row, 0), 2))
        if row == self.ROW_MATERIAL:
            self.workflow.load("자재검수.yaml", "자재검수",
                               self.material_form.차수(), self.material_form.values())
        elif row == self.ROW_TEST:
            self.workflow.load(self.test_form.workflow_file(),
                               self.test_form.series.value,
                               self.test_form.spin_번호.value(),
                               self.test_form.values())

    # -- 배지 (§16.0 §17.0 §18.2) ----------------------------------------
    def refresh_alerts(self) -> None:
        try:
            alerts = DueChecker(self.cfg, self.state).check()
        except Exception as e:
            log.exception("배지 갱신 실패")
            self.badge.setPlainText(f"⚠ 판정에 실패했습니다: {e}")
            return
        lines: list[str] = []
        for v in alerts.shape:
            lines.append(str(v))
        if not alerts.shape:
            lines.append("겉모양 시험 도래 업체 없음")
        if alerts.milk:
            lines.append("")
            lines.append(str(alerts.milk))
        if alerts.pending:
            lines.append("")
            lines += [str(p) for p in alerts.pending]
        미완 = self.state.open_workflows()
        if 미완:
            lines.append("")
            for key, items in 미완[:5]:
                lines.append(f"⚠ {key} 수동 단계 {len(items)}건 미완료")
        if alerts.warnings:
            lines.append("")
            lines += alerts.warnings          # 조용히 무시하지 않는다
        self.badge.setPlainText("\n".join(lines))
        self.state.touch("last_alert_check")

    def _maybe_refresh(self) -> None:
        """설정된 시각(기본 07:00)을 지났고 오늘 아직 안 했으면 재판정."""
        when = str(self.cfg.get("test_rules.phc_shape.refresh_at", "07:00"))
        try:
            h, m = (int(x) for x in when.split(":"))
        except ValueError:
            return
        now = datetime.now()
        if now.time() < time(h, m):
            return
        last = self.state.last("last_alert_check")
        if last and last.date() == now.date() and last.time() >= time(h, m):
            return
        self.refresh_alerts()

    # -- 미리보기 / 실행 ---------------------------------------------------
    def _current(self) -> tuple[Any, Any]:
        row = self.task_list.currentRow()
        if row == self.ROW_MATERIAL:
            return MaterialInspectionTask(self.cfg), self.material_form.build()
        if row == self.ROW_TEST:
            return self.test_form.task(), self.test_form.build()
        raise ValueError("이 태스크에는 미리보기가 없습니다.")

    def on_preview(self) -> None:
        if self.task_list.currentRow() == self.ROW_PHOTO:
            self.photo_form.preview()
            return
        try:
            task, data = self._current()
        except ValueError as e:
            QMessageBox.warning(self, "입력 확인", str(e))
            return
        self.status("미리보기 계산 중…")
        result = task.preview(data)
        self._show_result(result)
        self._fill_preview(result)

    def _fill_preview(self, result: TaskResult) -> None:
        self.preview_table.setRowCount(len(result.계획))
        for i, p in enumerate(result.계획):
            for j, v in enumerate([p.파일, p.시트, p.셀, p.종류, str(p.값)]):
                self.preview_table.setItem(i, j, QTableWidgetItem(v))

    def on_run(self) -> None:
        if self.task_list.currentRow() == self.ROW_PHOTO:
            self.photo_form.run()
            self.refresh_alerts()
            return
        try:
            task, data = self._current()
        except ValueError as e:
            QMessageBox.warning(self, "입력 확인", str(e))
            return
        회차 = getattr(data, "차수", None) or getattr(data, "번호", "")
        if QMessageBox.question(
                self, "실행", f"{task.name} {회차} 를 기록합니다.\n"
                "대상 파일이 모두 닫혀 있는지 확인하세요.") != QMessageBox.Yes:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status("실행 중…")
        try:
            result = task.run(data)
        finally:
            self.progress.setVisible(False)
        self._show_result(result)
        if result:
            if self.task_list.currentRow() == self.ROW_MATERIAL:
                self.workflow.load("자재검수.yaml", "자재검수", data.차수,
                                   self.material_form.values())
            else:
                self._track_pending(data)
                self.workflow.load(self.test_form.workflow_file(),
                                   self.test_form.series.value, data.번호,
                                   self.test_form.values())
            self.workflow.mark_auto_done()
            self.refresh_alerts()          # 누적이 실제로 바뀌는 순간 (§16.0)

    def _track_pending(self, data: Any) -> None:
        """BSCW/JSP 는 다음 단계를 state.json 이 기억한다 (§18.2)."""
        from core.models import CompressiveTest, CompStage
        from core.state import PendingTest

        if not isinstance(data, CompressiveTest):
            return
        다음 = {CompStage.NEW: CompStage.AWAIT_7D,
               CompStage.AWAIT_7D: CompStage.AWAIT_28D,
               CompStage.AWAIT_28D: CompStage.DONE}[data.stage]
        self.state.upsert_pending(PendingTest(
            series=data.series.value, 번호=data.번호,
            채취일=data.채취일.isoformat(), 목록행번호=data.목록행번호 or data.번호,
            stage=다음.value, 측정_7일=data.측정_7일, 측정_28일=data.측정_28일))

    def _show_result(self, result: TaskResult) -> None:
        self.status(result.메시지 or ("완료" if result else "실패"))
        if not result:
            QMessageBox.critical(self, result.태스크,
                                 result.메시지 + ("\n\n- " + "\n- ".join(result.경고)
                                                  if result.경고 else ""))
        elif result.경고:
            QMessageBox.warning(self, result.태스크, "\n- ".join(["확인 필요:", *result.경고]))

    # -- 되돌리기 (§2.1) ---------------------------------------------------
    def on_undo(self) -> None:
        manager = BackupManager(self.cfg.path("backup_root"))
        backups = manager.list_backups(limit=30)
        if not backups:
            QMessageBox.information(self, "되돌리기", "백업이 없습니다.")
            return
        labels = [f"{b.created:%Y-%m-%d %H:%M:%S}  {b.task}  ({len(b.files)}개 파일)"
                  for b in backups]
        box = QComboBox()
        box.addItems(labels)
        dlg = QMessageBox(self)
        dlg.setWindowTitle("되돌리기")
        dlg.setText("복원할 백업을 고르세요.\n선택한 시점의 원본으로 되돌립니다.")
        dlg.layout().addWidget(box, 1, 0, 1, dlg.layout().columnCount())
        dlg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        if dlg.exec() != QMessageBox.Ok:
            return
        bset = backups[box.currentIndex()]
        try:
            restored = bset.restore()
        except Exception as e:
            QMessageBox.critical(self, "되돌리기 실패", str(e))
            return
        QMessageBox.information(self, "되돌리기 완료",
                                "\n".join(f"복원: {p.name}" for p in restored))
        self.refresh_alerts()

    # -- 정합성 검사 (§21.3) -----------------------------------------------
    def run_consistency(self) -> None:
        self.status("정합성 검사 중…")
        findings = ConsistencyChecker(self.cfg, self.state).check_all()
        self.status(f"정합성 검사 완료 — {len(findings)}건")
        if not findings:
            QMessageBox.information(self, "정합성 검사", "어긋난 곳이 없습니다.")
            return
        text = "\n".join(str(f) for f in findings)
        box = QMessageBox(self)
        box.setWindowTitle(f"정합성 검사 — {len(findings)}건")
        box.setText(f"{sum(1 for f in findings if f.수준 == 'error')}건이 오류입니다.")
        box.setDetailedText(text)
        box.exec()
