"""백업 / 복원 / manifest (SPEC §2.1).

규칙 하나: **백업 실패 = 작업 중단.** 백업 없이 원본을 수정하지 않는다 (§10 #8).
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .util import json_default, sha256


class BackupError(RuntimeError):
    """백업이 실패했다. 호출자는 반드시 작업을 중단해야 한다."""


@dataclass
class BackupSet:
    """한 번의 작업에 대한 백업 묶음."""

    folder: Path
    task: str
    files: dict[str, Path] = field(default_factory=dict)   # 원본경로 -> 백업경로
    created: datetime = field(default_factory=datetime.now)

    @property
    def manifest_path(self) -> Path:
        return self.folder / "manifest.json"

    def restore(self) -> list[Path]:
        """백업본을 원본 위치로 되돌린다. 복원한 원본 경로 목록을 돌려준다."""
        restored: list[Path] = []
        for original, backup in self.files.items():
            target = Path(original)
            if not backup.exists():
                raise BackupError(f"백업본이 없습니다: {backup}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored.append(target)
        return restored


class BackupManager:
    """``{backup_root}\\YYYYMMDD\\HHMMSS_{작업명}\\원본파일명`` 규약."""

    def __init__(self, backup_root: str | Path):
        self.root = Path(backup_root)

    # -- 생성 -----------------------------------------------------------
    def start(self, task: str, when: datetime | None = None) -> BackupSet:
        when = when or datetime.now()
        folder = self.root / when.strftime("%Y%m%d") / f"{when:%H%M%S}_{task}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise BackupError(f"백업 폴더를 만들 수 없습니다: {folder}\n{e}") from e
        return BackupSet(folder=folder, task=task, created=when)

    def add(self, bset: BackupSet, path: str | Path) -> Path:
        """파일을 건드리기 **직전** 에 부른다. mtime 을 보존한다."""
        src = Path(path)
        if not src.exists():
            raise BackupError(f"백업할 원본이 없습니다: {src}")
        dst = bset.folder / src.name
        if dst.exists():                       # 한 작업에서 같은 이름 파일 두 개
            dst = bset.folder / f"{src.stem}_{len(bset.files) + 1}{src.suffix}"
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            raise BackupError(f"백업 복사 실패: {src} -> {dst}\n{e}") from e
        if dst.stat().st_size != src.stat().st_size:
            raise BackupError(f"백업 크기가 원본과 다릅니다: {dst}")
        bset.files[str(src)] = dst
        return dst

    def add_all(self, bset: BackupSet, paths: list[str | Path]) -> None:
        for p in paths:
            self.add(bset, p)

    def write_manifest(self, bset: BackupSet, payload: dict[str, Any]) -> Path:
        data = {
            "ts": bset.created.isoformat(timespec="seconds"),
            "task": bset.task,
            "files": [Path(p).name for p in bset.files],
            "originals": list(bset.files),
            "sha256": {Path(p).name: sha256(b) for p, b in bset.files.items()},
            **payload,
        }
        bset.manifest_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=json_default),
            encoding="utf-8",
        )
        return bset.manifest_path

    # -- 조회 / 복원 ------------------------------------------------------
    def list_backups(self, limit: int = 50) -> list[BackupSet]:
        """최근 백업 목록 (최신 먼저). [되돌리기] 드롭다운용."""
        out: list[BackupSet] = []
        if not self.root.exists():
            return out
        for day in sorted(self.root.iterdir(), reverse=True):
            if not day.is_dir() or not day.name.isdigit():
                continue
            for folder in sorted(day.iterdir(), reverse=True):
                if not folder.is_dir():
                    continue
                bset = self._load(folder)
                if bset:
                    out.append(bset)
                if len(out) >= limit:
                    return out
        return out

    def _load(self, folder: Path) -> BackupSet | None:
        manifest = folder / "manifest.json"
        if not manifest.exists():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        bset = BackupSet(folder=folder, task=data.get("task", folder.name))
        for original in data.get("originals", []):
            candidate = folder / Path(original).name
            if candidate.exists():
                bset.files[original] = candidate
        try:
            bset.created = datetime.fromisoformat(data["ts"])
        except (KeyError, ValueError):
            pass
        return bset
