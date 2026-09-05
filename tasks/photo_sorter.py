"""PART 3 — 사진 분류 시스템 (SPEC §23~§25).

    사진분류\\<카테고리>\\[<폴더명>\\]사진들
       -> 스캔 (파일은 건드리지 않고 계획만)
       -> 압축      긴 변 1600px / JPEG q85 / progressive / optimize
       -> EXIF 제거  촬영일시·기종·렌즈·소프트웨어·GPS 전부
       -> 목적지     <dest>\\<폴더명>\\
       -> 원본       사진백업\\<오늘>\\<카테고리>\\<폴더명>\\ 으로 이동 (삭제 아님)
       -> 정리       30일 지난 백업 삭제, 비워진 입력 하위폴더 삭제

BSCW·JSP·물시멘트비는 **폴더명이 촬영일이 아니다** (타설일 / 시험 회차).
그래서 하위폴더가 필수이고, 없으면 옮기지 않고 경고한다 (§24.3).

.. note::
   SPEC §23 은 이미 배포된 ``사진분류기\\photo_sorter.py`` 를 가져다 쓰라고 한다.
   그 파일이 있으면 이 모듈을 그것으로 교체하면 된다 — GUI 는 §24.7 의
   ``scan()`` / ``run()`` API 만 쓰므로 그대로 붙는다.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

DEFAULT_IGNORE = ("Thumbs.db", "desktop.ini", ".DS_Store")
DEFAULT_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif")


@dataclass
class Category:
    name: str
    dest: Path
    folder_fmt: str | None = "%m%d"
    require_sub: bool = False


@dataclass
class PlannedMove:
    src: Path
    category: str
    target_folder: str
    dest: Path
    src_bytes: int = 0


@dataclass
class SortResult:
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    purged_backups: list[Path] = field(default_factory=list)
    saved_bytes: int = 0

    @property
    def 요약(self) -> str:
        mb = self.saved_bytes / (1024 * 1024)
        return (f"{len(self.moved)}장 처리, {mb:.1f}MB 절감"
                + (f", 실패 {len(self.failed)}건" if self.failed else "")
                + (f", 보류 {len(self.blocked)}건" if self.blocked else ""))


@dataclass
class PhotoConfig:
    input_root: Path
    backup_root: Path
    categories: list[Category]
    max_edge: int = 1600
    jpeg_quality: int = 85
    backup_keep_days: int = 30
    ignore_names: tuple[str, ...] = DEFAULT_IGNORE
    extensions: tuple[str, ...] = DEFAULT_EXT
    log_dir: Path | None = None


def load_config(cfg: Any) -> PhotoConfig:
    """프로그램 config.yaml 의 photo 절을 PhotoConfig 로."""
    if isinstance(cfg, (str, Path)):
        from core.config import load_config as _load

        cfg = _load(cfg)
    photo = cfg.raw.get("photo", {})
    cats = [
        Category(
            name=c["name"],
            dest=Path(c["dest"]),
            folder_fmt=c.get("folder_fmt"),
            require_sub=bool(c.get("require_sub", False)),
        )
        for c in photo.get("categories", [])
    ]
    return PhotoConfig(
        input_root=Path(cfg.path("photo_sort_root")),
        backup_root=Path(cfg.path("photo_backup_root")),
        categories=cats,
        max_edge=int(photo.get("max_edge", 1600)),
        jpeg_quality=int(photo.get("jpeg_quality", 85)),
        backup_keep_days=int(photo.get("backup_keep_days", 30)),
        ignore_names=tuple(photo.get("ignore_names", DEFAULT_IGNORE)),
        extensions=tuple(photo.get("extensions", DEFAULT_EXT)),
    )


class PhotoSorter:
    def __init__(self, config: PhotoConfig, today: date | None = None):
        self.cfg = config
        self.today = today or date.today()

    # =================================================================
    # 스캔 — 파일을 일절 건드리지 않는다 (§24.7)
    # =================================================================
    def scan(self) -> tuple[list[PlannedMove], list[str]]:
        plans: list[PlannedMove] = []
        blocked: list[str] = []
        for cat in self.cfg.categories:
            folder = self.cfg.input_root / cat.name
            if not folder.is_dir():
                continue
            # 1) 하위폴더 안의 사진 — 폴더 이름을 그대로 목적지에 쓴다
            for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
                for f in self._images(sub, recursive=True):
                    rel = f.parent.relative_to(folder)
                    plans.append(PlannedMove(
                        src=f, category=cat.name, target_folder=str(rel),
                        dest=cat.dest / rel, src_bytes=f.stat().st_size))
            # 2) 카테고리 폴더 바로 아래의 사진
            loose = list(self._images(folder, recursive=False))
            if not loose:
                continue
            if cat.require_sub:
                blocked.append(
                    f"[{cat.name}] 하위폴더 없이 사진 {len(loose)}장이 있습니다. "
                    f"{self._require_hint(cat.name)} 이름의 폴더를 만들어 넣으세요 "
                    "— 촬영일로는 맞출 수 없습니다.")
                continue
            name = self.today.strftime(cat.folder_fmt or "%m%d")
            for f in loose:
                plans.append(PlannedMove(
                    src=f, category=cat.name, target_folder=name,
                    dest=cat.dest / name, src_bytes=f.stat().st_size))
        return plans, blocked

    @staticmethod
    def _require_hint(category: str) -> str:
        return {"BSCW": "타설일(0822)", "JSP": "타설일(0822)",
                "물시멘트비": "시험 회차(01, 02)"}.get(category, "구분")

    def _images(self, folder: Path, *, recursive: bool) -> Iterable[Path]:
        it = folder.rglob("*") if recursive else folder.iterdir()
        for p in sorted(it):
            if not p.is_file():
                continue
            if p.name in self.cfg.ignore_names:
                continue
            if p.suffix.lower() not in self.cfg.extensions:
                continue
            yield p

    # =================================================================
    # 실행
    # =================================================================
    def run(self, plans: list[PlannedMove], blocked: list[str] | None = None, *,
            dry_run: bool = False) -> SortResult:
        result = SortResult(blocked=list(blocked or []))
        if not plans:
            # 처리할 사진이 0장이면 목적지 폴더를 만들지 않는다 (§24.6)
            log.info("분류할 사진이 없습니다")
            if not dry_run:
                result.purged_backups = self._purge_backups()
            return result

        for plan in plans:
            try:
                if dry_run:
                    result.moved.append((plan.src, plan.dest / plan.src.name))
                    continue
                out, saved = self._process(plan)
                result.moved.append((plan.src, out))
                result.saved_bytes += saved
                self._archive(plan)
            except Exception as e:                 # 한 장이 실패해도 나머지는 진행
                log.warning("사진 처리 실패: %s", plan.src, exc_info=True)
                result.failed.append((plan.src, str(e)))

        if not dry_run:
            result.purged_backups = self._purge_backups()
            self._clean_empty_dirs()
            self._write_log(result)
        return result

    # -- 압축 + EXIF 제거 (§24.4, §24.5) ----------------------------------
    def _process(self, plan: PlannedMove) -> tuple[Path, int]:
        from PIL import Image, ImageOps

        plan.dest.mkdir(parents=True, exist_ok=True)
        src = plan.src
        out_suffix = ".jpg" if src.suffix.lower() in (".heic", ".heif") else src.suffix
        target = _unique(plan.dest / (src.stem + out_suffix))

        with Image.open(src) as im:
            # 회전 정보를 픽셀에 먼저 반영한다. Orientation 태그가 사라져도 눕지 않는다.
            im = ImageOps.exif_transpose(im)
            icc = im.info.get("icc_profile")       # ICC 는 유지 (개인정보가 아니다)
            resized = im.copy()
            if max(resized.size) > self.cfg.max_edge:
                resized.thumbnail((self.cfg.max_edge, self.cfg.max_edge),
                                  Image.Resampling.LANCZOS)
            kw: dict[str, Any] = {}
            if icc:
                kw["icc_profile"] = icc
            if target.suffix.lower() in (".jpg", ".jpeg"):
                if resized.mode not in ("RGB", "L"):
                    resized = resized.convert("RGB")
                kw.update(quality=self.cfg.jpeg_quality, optimize=True, progressive=True)
            # exif= 를 넘기지 않는다 -> 촬영일시·기종·렌즈·GPS 전부 사라진다
            resized.save(target, **kw)

        원본크기 = src.stat().st_size
        결과크기 = target.stat().st_size
        if 결과크기 >= 원본크기 and max(Image.open(src).size) <= self.cfg.max_edge:
            # 이미 작은 사진이면 리사이즈를 포기하고 EXIF 만 제거한다 (§24.4)
            target.unlink()
            target = _unique(plan.dest / (src.stem + out_suffix))
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)
                kw = {"icc_profile": im.info.get("icc_profile")} if im.info.get("icc_profile") else {}
                if target.suffix.lower() in (".jpg", ".jpeg"):
                    if im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")
                    kw.update(quality=self.cfg.jpeg_quality, optimize=True, progressive=True)
                im.save(target, **kw)
            결과크기 = target.stat().st_size
        return target, max(0, 원본크기 - 결과크기)

    # -- 원본 보관 (삭제하지 않는다) ---------------------------------------
    def _archive(self, plan: PlannedMove) -> None:
        folder = (self.cfg.backup_root / self.today.strftime("%Y%m%d")
                  / plan.category / plan.target_folder)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(plan.src), str(_unique(folder / plan.src.name)))

    def _purge_backups(self) -> list[Path]:
        """30일 지난 백업 폴더 삭제 (§24.1)."""
        out: list[Path] = []
        if not self.cfg.backup_root.is_dir():
            return out
        for day in sorted(self.cfg.backup_root.iterdir()):
            if not day.is_dir() or not day.name.isdigit() or len(day.name) != 8:
                continue
            try:
                d = datetime.strptime(day.name, "%Y%m%d").date()
            except ValueError:
                continue
            if (self.today - d).days > self.cfg.backup_keep_days:
                shutil.rmtree(day, ignore_errors=True)
                out.append(day)
        return out

    def _clean_empty_dirs(self) -> None:
        """비워진 입력 하위폴더를 정리한다. 카테고리 폴더 자체는 남긴다."""
        for cat in self.cfg.categories:
            root = self.cfg.input_root / cat.name
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*"), key=lambda x: -len(x.parts)):
                if p.is_dir() and not any(p.iterdir()):
                    p.rmdir()

    def _write_log(self, result: SortResult) -> None:
        folder = self.cfg.log_dir or (self.cfg.backup_root.parent / "로그")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"사진분류_{self.today:%Y%m%d}.log"
            with path.open("a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} {result.요약}\n")
                for src, dst in result.moved:
                    f.write(f"  {src} -> {dst}\n")
                for src, err in result.failed:
                    f.write(f"  [실패] {src}: {err}\n")
                for b in result.blocked:
                    f.write(f"  [보류] {b}\n")
        except OSError:
            log.warning("사진분류 로그를 남기지 못했습니다", exc_info=True)


def _unique(path: Path) -> Path:
    """덮어쓰기 금지 — 같은 이름이 있으면 '1_2.jpg', '1_3.jpg' (§24.6)."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1
