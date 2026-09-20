"""Task 추상 클래스 (SPEC §8).

2차 태스크(철근·레미콘·단열재·의뢰시험)를 붙일 자리다.
쓰기 순서·백업·롤백은 ``run()`` 이 공통으로 처리하므로,
새 태스크는 ``execute`` 와 검증 두 개만 채우면 된다.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.backup import BackupError, BackupManager
from core.config import Config
from core.context import LiveContext, PreviewContext, TaskContext, TaskResult
from core.excel_writer import ExcelSession

log = logging.getLogger(__name__)


class Task(ABC):
    name: str = "이름 없는 태스크"
    workflow_file: str | None = None
    #: 이 태스크가 건드리는 config files.<key> 목록. 백업 대상이 된다.
    target_files: tuple[str, ...] = ()

    def __init__(self, cfg: Config):
        self.cfg = cfg

    # -- 하위 클래스가 채우는 부분 ---------------------------------------
    @abstractmethod
    def validate_before(self, data: Any, ctx: TaskContext) -> list[str]:
        """사전 검증. 문제 목록을 돌려준다. 비어 있으면 통과."""

    @abstractmethod
    def execute(self, data: Any, ctx: TaskContext) -> None:
        """실제 쓰기. ctx.book(key) 로 얻은 통합문서에만 쓴다."""

    def validate_after(self, data: Any, ctx: TaskContext) -> list[str]:
        """사후 검증. 기본은 없음. 파일을 다시 읽어 확인하는 것은 ``verify_files``."""
        return []

    def verify_files(self, data: Any) -> list[str]:
        """저장된 파일을 다시 읽어 계산값을 확인한다 (§5.3). 교체 직전에 불린다."""
        return []

    def preview_sheets(self) -> dict[str, list[str]]:
        """미리보기에서 읽을 시트를 좁혀 속도를 올린다. {file_key: [시트명]}"""
        return {}

    # -- 공통 실행 흐름 ---------------------------------------------------
    def preview(self, data: Any) -> TaskResult:
        """파일을 건드리지 않고 '어디에 무엇이 들어가는지' 만 계산한다."""
        ctx = PreviewContext(self.cfg, only=self.preview_sheets())
        problems = self.validate_before(data, ctx)
        if problems:
            return TaskResult(False, self.name, "사전 검증 실패", 경고=problems)
        try:
            self.execute(data, ctx)
        except Exception as e:
            log.exception("미리보기 실패")
            return TaskResult(False, self.name, f"미리보기 중 오류: {e}")
        plans = ctx.plans()
        return TaskResult(True, self.name, f"{len(plans)}건의 변경이 계획됐습니다.",
                          계획=plans, 경고=self.validate_after(data, ctx))

    def run(self, data: Any, *, dry_run: bool = False) -> TaskResult:
        """백업 -> 사전 검증 -> 쓰기 -> 사후 검증 -> 원자적 교체.

        **6~9는 전부 성공하거나 전부 롤백** (§5.1). 커밋 전에 실패하면 원본은
        애초에 손도 대지 않은 상태이고, 커밋 후 검증 실패면 백업본으로 되돌린다.
        """
        manager = BackupManager(self.cfg.path("backup_root"))
        targets = [self.cfg.path(k) for k in self.target_files]

        # 1) 백업 먼저. 실패하면 여기서 끝 (§10 #8)
        try:
            bset = manager.start(self.name.replace(" ", "_"))
            for t in targets:
                if Path(t).exists():
                    manager.add(bset, t)
            manager.write_manifest(bset, {"input": _describe(data)})
        except BackupError as e:
            return TaskResult(False, self.name, f"백업 실패로 중단했습니다.\n{e}")

        try:
            with ExcelSession(dry_run=dry_run) as session:
                ctx = LiveContext(self.cfg, session)
                problems = self.validate_before(data, ctx)
                if problems:
                    return TaskResult(False, self.name, "사전 검증 실패",
                                      경고=problems, 백업폴더=bset.folder)
                self.execute(data, ctx)
                after = self.validate_after(data, ctx)
                if after:
                    return TaskResult(False, self.name,
                                      "사후 검증 실패 — 원본은 수정되지 않았습니다.",
                                      경고=after, 백업폴더=bset.folder)
                ctx.commit()
        except Exception as e:
            log.exception("%s 실행 실패", self.name)
            return TaskResult(False, self.name,
                              f"실행 실패 — 원본은 수정되지 않았습니다.\n{e}",
                              백업폴더=bset.folder)

        # 2) 교체가 끝난 뒤 파일을 다시 읽어 계산값 확인 (§5.3)
        problems = self.verify_files(data)
        if problems:
            restored = bset.restore()
            return TaskResult(
                False, self.name,
                "사후 검증 실패 — 백업본으로 되돌렸습니다.\n"
                + "\n".join(f"  복원: {p.name}" for p in restored),
                경고=problems, 백업폴더=bset.folder,
            )
        return TaskResult(True, self.name, "완료", 백업폴더=bset.folder)


def _describe(data: Any) -> Any:
    """manifest 에 남길 입력값 표현."""
    from dataclasses import asdict, is_dataclass

    if is_dataclass(data) and not isinstance(data, type):
        return asdict(data)
    return data
