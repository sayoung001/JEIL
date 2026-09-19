"""문서 투입 — 원본을 넣으면 알아서 갈라 보낸다.

한 폴더에 원본을 넣으면 **종류에 따라 세 갈래**로 처리한다.

======== ===================================== ==========================
레인     대상                                   처리
======== ===================================== ==========================
압축분류  각종시험(BSCW·JSP·물시멘트비·겉모양)   메타데이터 제거 + 압축 + 분류
         · 자재검수 사진
원본분류  의뢰시험 자료 (재하·MT·일반)           **원본 그대로** 보존 + 분류
성적서    성적서·보고서 PDF                      글자 추출 -> 문서 자동 완성 + 분류
======== ===================================== ==========================

**의뢰시험만 원본을 보존하는 이유** — 외부 기관이 발급한 증빙이라 나중에
원본성이 문제가 될 수 있다. 우리가 찍은 현장 사진은 감리 제출·보관이 목적이라
압축해도 되지만, 남의 성적서·증빙은 손대지 않는다.

.. warning::
   **읽기가 먼저, 압축이 나중이다.** 카카오톡으로 받은 사진은 이미 압축돼
   글자가 뭉개져 있다. 그래서 원본을 넣어야 하고, 이 파이프라인은 항상
   **원본에서 먼저 읽고(OCR/추출) 그 다음에 압축**한다. 순서를 바꾸면
   읽을 수 있던 것도 못 읽는다.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from core.config import Config
from core.documents import ParsedDocument, parse_file
from core.extract import ExtractedText
from core.paths import as_path

log = logging.getLogger(__name__)

DOC_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
IGNORE_NAMES = ("Thumbs.db", "desktop.ini", ".DS_Store")


class Lane(str, Enum):
    압축분류 = "압축분류"      # 메타 제거 + 압축 + 분류
    원본분류 = "원본분류"      # 원본 그대로 + 분류
    성적서 = "성적서"          # 글자 추출 + 자동 완성 + 분류


@dataclass
class IntakeCategory:
    """투입 폴더 한 칸."""

    name: str
    lane: Lane
    dest: Path
    #: 날짜 폴더 형식. ``None`` 이면 뜻이 두 가지다.
    #:  · ``require_sub=True``  -> 사용자가 만든 하위폴더 이름을 그대로 쓴다
    #:  · ``require_sub=False`` -> 하위폴더 없이 목적지에 바로 넣는다 (성적서)
    folder_fmt: str | None = "%m%d"
    require_sub: bool = False
    #: 성적서 레인에서 이 칸에 들어온 문서가 어느 대장으로 가는지
    ledger: str | None = None

    @property
    def 날짜폴더없음(self) -> bool:
        return self.folder_fmt is None and not self.require_sub


@dataclass
class IntakeItem:
    """파일 하나에 대한 계획."""

    src: Path
    category: str
    lane: Lane
    target_folder: str
    dest: Path
    src_bytes: int = 0
    parsed: ParsedDocument | None = None
    extracted: ExtractedText | None = None

    @property
    def 처리(self) -> str:
        return {Lane.압축분류: "압축+메타제거", Lane.원본분류: "원본 보존",
                Lane.성적서: "글자 추출"}[self.lane]

    @property
    def 요약(self) -> str:
        if self.parsed is not None and self.parsed.읽힘:
            return self.parsed.요약()
        if self.parsed is not None:
            return "읽지 못함 — 직접 확인"
        return ""


@dataclass
class IntakeResult:
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    parsed: list[IntakeItem] = field(default_factory=list)
    saved_bytes: int = 0

    @property
    def 요약(self) -> str:
        mb = self.saved_bytes / (1024 * 1024)
        parts = [f"{len(self.moved)}건 처리"]
        if self.saved_bytes:
            parts.append(f"{mb:.1f}MB 절감")
        if self.parsed:
            읽힘 = sum(1 for i in self.parsed if i.parsed and i.parsed.읽힘)
            parts.append(f"성적서 {읽힘}/{len(self.parsed)}건 읽음")
        if self.failed:
            parts.append(f"실패 {len(self.failed)}건")
        if self.blocked:
            parts.append(f"보류 {len(self.blocked)}건")
        return ", ".join(parts)


# ---------------------------------------------------------------------
def load_categories(cfg: Config) -> list[IntakeCategory]:
    """config 의 ``documents.categories`` 를 읽는다."""
    out: list[IntakeCategory] = []
    for c in (cfg.get("documents.categories") or []):
        try:
            lane = Lane(c["lane"])
        except (KeyError, ValueError):
            log.warning("모르는 레인이라 건너뜁니다: %r", c)
            continue
        out.append(IntakeCategory(
            name=c["name"], lane=lane, dest=as_path(c["dest"]),
            folder_fmt=c.get("folder_fmt"),
            require_sub=bool(c.get("require_sub", False)),
            ledger=c.get("ledger"),
        ))
    return out


class DocumentIntake:
    """투입 폴더를 훑어 계획을 세우고(scan), 실행한다(run)."""

    def __init__(self, cfg: Config, today: date | None = None):
        self.cfg = cfg
        self.today = today or date.today()
        self.root = as_path(cfg.path("intake_root"))
        self.categories = load_categories(cfg)
        self.photo = _photo_settings(cfg)

    # =================================================================
    # 스캔 — 파일을 건드리지 않는다. 성적서는 여기서 **원본 그대로** 읽는다.
    # =================================================================
    def scan(self, *, read_documents: bool = True) -> tuple[list[IntakeItem], list[str]]:
        items: list[IntakeItem] = []
        blocked: list[str] = []

        for cat in self.categories:
            folder = self.root / cat.name
            if not folder.is_dir():
                continue

            for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
                for f in self._files(sub, recursive=True):
                    rel = f.parent.relative_to(folder)
                    items.append(self._item(f, cat, str(rel), cat.dest / rel))

            loose = list(self._files(folder, recursive=False))
            if not loose:
                continue
            if cat.require_sub:
                blocked.append(
                    f"[{cat.name}] 하위폴더 없이 {len(loose)}건이 있습니다. "
                    f"{_hint(cat.name)} 이름의 폴더를 만들어 넣으세요.")
                continue
            if cat.날짜폴더없음:
                # 성적서는 목적지에 바로 넣는다. 날짜로 또 나누면 찾기만 어려워진다.
                for f in loose:
                    items.append(self._item(f, cat, "", cat.dest))
            else:
                name = self.today.strftime(cat.folder_fmt or "%m%d")
                for f in loose:
                    items.append(self._item(f, cat, name, cat.dest / name))

        if read_documents:
            for item in items:
                if item.lane is Lane.성적서:
                    # 원본에서 읽는다. 압축 전이라 글자가 살아 있다.
                    item.parsed, item.extracted = parse_file(
                        item.src, vendors=self.cfg.vendors,
                        ocr_engine=self.cfg.get("documents.ocr_engine"))
        return items, blocked

    def _item(self, f: Path, cat: IntakeCategory, folder: str, dest: Path) -> IntakeItem:
        return IntakeItem(src=f, category=cat.name, lane=cat.lane,
                          target_folder=folder, dest=dest,
                          src_bytes=f.stat().st_size)

    def _files(self, folder: Path, *, recursive: bool):
        it = folder.rglob("*") if recursive else folder.iterdir()
        allowed = IMAGE_SUFFIXES | DOC_SUFFIXES | {".hwp", ".xlsx", ".xls", ".docx"}
        for p in sorted(it):
            if not p.is_file() or p.name in IGNORE_NAMES or p.name.startswith("~$"):
                continue
            if p.suffix.lower() in allowed:
                yield p

    # =================================================================
    # 실행
    # =================================================================
    def run(self, items: list[IntakeItem], blocked: list[str] | None = None, *,
            dry_run: bool = False) -> IntakeResult:
        result = IntakeResult(blocked=list(blocked or []))
        for item in items:
            try:
                if dry_run:
                    result.moved.append((item.src, item.dest / item.src.name))
                    continue
                dst, saved = self._handle(item)
                result.moved.append((item.src, dst))
                result.saved_bytes += saved
                if item.lane is Lane.성적서:
                    result.parsed.append(item)
            except Exception as e:
                log.warning("문서 처리 실패: %s", item.src, exc_info=True)
                result.failed.append((item.src, str(e)))
        return result

    def _handle(self, item: IntakeItem) -> tuple[Path, int]:
        item.dest.mkdir(parents=True, exist_ok=True)
        if item.lane is Lane.압축분류 and item.src.suffix.lower() in IMAGE_SUFFIXES:
            return self._compress(item)
        return self._move_original(item)

    def _move_original(self, item: IntakeItem) -> tuple[Path, int]:
        """원본 그대로 옮긴다. 의뢰시험 증빙·성적서 PDF 가 여기로 온다."""
        dst = _unique(item.dest / item.src.name)
        shutil.move(str(item.src), str(dst))
        return dst, 0

    def _compress(self, item: IntakeItem) -> tuple[Path, int]:
        """메타데이터를 지우고 압축한다. 원본은 백업 폴더로 옮긴다."""
        from .photo_sorter import PhotoSorter, PlannedMove

        sorter = PhotoSorter(self.photo, today=self.today)
        plan = PlannedMove(src=item.src, category=item.category,
                           target_folder=item.target_folder, dest=item.dest,
                           src_bytes=item.src_bytes)
        dst, saved = sorter._process(plan)
        sorter._archive(plan)
        return dst, saved


def _photo_settings(cfg: Config) -> Any:
    from .photo_sorter import PhotoConfig, load_config as _load

    base = _load(cfg)
    base.input_root = as_path(cfg.path("intake_root"))
    return base


def _hint(category: str) -> str:
    return {"BSCW": "타설일(0822)", "JSP": "타설일(0822)",
            "물시멘트비": "시험 회차(01, 02)",
            "의뢰시험_재하": "시험일과 동-번호(0824 113-152)",
            "의뢰시험_MT": "시험일(0916)"}.get(category, "구분")


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1
