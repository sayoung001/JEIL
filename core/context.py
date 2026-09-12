"""태스크 실행 문맥.

[실행] 과 [미리보기] 가 **같은 코드**를 타도록 만드는 층이다.
미리보기 전용 표시 코드를 따로 두면 실제 쓰기와 어긋나기 시작한다 (§7).

* ``LiveContext``    — xlwings 세션. 실제로 쓴다.
* ``PreviewContext`` — 원본을 openpyxl/xlrd 로 읽어 메모리 시트에 올려 두고,
                       거기에 쓴다. 원본은 열지도 않는다.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .excel_reader import read_book
from .excel_writer import ExcelSession
from .sheets import MemorySheet, MemoryWorkbook, WorkbookPort, WriteRecord

log = logging.getLogger(__name__)


@dataclass
class PlannedWrite:
    """[미리보기] 표 한 줄."""

    파일: str
    시트: str
    셀: str
    값: Any
    종류: str = "값"

    @classmethod
    def from_record(cls, 파일: str, rec: WriteRecord) -> "PlannedWrite":
        kind = {"formula": "수식", "merge": "병합", "print_area": "인쇄영역",
                "format": "서식", "value": "값", "sheet": "시트"}.get(rec.kind, rec.kind)
        return cls(파일=파일, 시트=rec.sheet, 셀=rec.cell, 값=rec.value, 종류=kind)


class TaskContext(ABC):
    """태스크가 파일을 얻는 통로. 태스크는 실제/미리보기를 구분하지 않는다."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._opened: dict[str, WorkbookPort] = {}

    @property
    @abstractmethod
    def is_preview(self) -> bool: ...

    @abstractmethod
    def _open(self, path: Path) -> WorkbookPort: ...

    def book(self, file_key: str) -> WorkbookPort:
        """config 의 files.<key> 로 통합문서를 연다. 같은 키는 한 번만 연다."""
        if file_key not in self._opened:
            path = Path(self.cfg.path(file_key))
            self._opened[file_key] = self._open(path)
            log.info("열기(%s): %s", "미리보기" if self.is_preview else "쓰기", path.name)
        return self._opened[file_key]

    def path(self, file_key: str) -> Path:
        return Path(self.cfg.path(file_key))

    @property
    def open_keys(self) -> list[str]:
        return list(self._opened)


class LiveContext(TaskContext):
    """실제 쓰기. ``with`` 로 감싸 쓰고, 성공했을 때만 ``commit()`` 한다."""

    def __init__(self, cfg: Config, session: ExcelSession):
        super().__init__(cfg)
        self.session = session

    @property
    def is_preview(self) -> bool:
        return False

    def _open(self, path: Path) -> WorkbookPort:
        return self.session.open(path)

    def commit(self, verify: Any = None) -> None:
        self.session.commit(verify=verify)


class PreviewContext(TaskContext):
    """원본을 읽어 메모리에 올린 뒤 거기에 쓴다. 파일은 절대 건드리지 않는다."""

    def __init__(self, cfg: Config, only: dict[str, list[str]] | None = None):
        super().__init__(cfg)
        # {file_key: [읽을 시트...]} — 큰 파일에서 필요한 시트만 읽어 빠르게 한다
        self.only = only or {}
        self._labels: dict[int, str] = {}

    @property
    def is_preview(self) -> bool:
        return True

    def book(self, file_key: str) -> WorkbookPort:
        wb = super().book(file_key)
        self._labels[id(wb)] = file_key
        return wb

    def _open(self, path: Path) -> WorkbookPort:
        wb = MemoryWorkbook(path=str(path))
        if not path.exists():
            log.warning("미리보기: 파일이 없어 빈 문서로 대체합니다 — %s", path)
            return wb
        key = next((k for k, v in self.cfg.raw.get("files", {}).items()
                    if Path(v) == path), None)
        # 수식을 그대로 읽어야 'J열에 이미 수식이 있는가' 같은 판단이 가능하다 (§4.1)
        rb = read_book(path, data_only=False, only=self.only.get(key or "", None) or None)
        for name, sh in rb.sheets.items():
            ms = MemorySheet(name=name)
            for r, row in sh.iter_rows():
                for i, v in enumerate(row):
                    if v is not None and str(v).strip() != "":
                        ms.cells[(r, i + 1)] = v
            ms.log.clear()                      # 적재는 기록에서 뺀다
            wb.sheets[name] = ms
        return wb

    def plans(self) -> list[PlannedWrite]:
        out: list[PlannedWrite] = []
        for key, wb in self._opened.items():
            label = Path(self.cfg.path(key)).name
            if isinstance(wb, MemoryWorkbook):
                for rec in wb.records():
                    out.append(PlannedWrite.from_record(label, rec))
        return out


@dataclass
class TaskResult:
    """태스크 실행 결과."""

    성공: bool
    태스크: str
    메시지: str = ""
    경고: list[str] = field(default_factory=list)
    계획: list[PlannedWrite] = field(default_factory=list)
    백업폴더: Path | None = None
    상세: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.성공
