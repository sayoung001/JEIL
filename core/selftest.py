"""자가 점검 — 이 PC 에서 프로그램이 제대로 돌 수 있는가.

회사 PC 에는 VS Code 도 파이썬도 없다. exe 하나만 복사해 쓰므로,
문제가 생겼을 때 **exe 스스로 무엇이 빠졌는지 말해야 한다.**

    품질자동화.exe --selftest
"""
from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import Config, check_paths
from .paths import app_dir, describe, is_frozen, resource


@dataclass
class Check:
    이름: str
    통과: bool
    상세: str = ""
    치명적: bool = True          # False 면 없어도 주요 기능은 돈다

    def __str__(self) -> str:
        mark = "O" if self.통과 else ("X" if self.치명적 else "-")
        tail = f"  {self.상세}" if self.상세 else ""
        return f"  [{mark}] {self.이름}{tail}"


def _try(이름: str, fn: Callable[[], str], *, 치명적: bool = True) -> Check:
    try:
        return Check(이름, True, fn(), 치명적)
    except Exception as e:
        return Check(이름, False, str(e).splitlines()[0], 치명적)


def run_selftest(cfg: Config | None = None) -> list[Check]:
    checks: list[Check] = []

    # --- 기본 부품 -------------------------------------------------
    checks.append(Check("파이썬", True, sys.version.split()[0]))
    checks.append(_try("설정 읽기(YAML)", lambda: _ver("yaml")))
    checks.append(_try("엑셀 읽기 .xlsx(openpyxl)", lambda: _ver("openpyxl")))
    checks.append(_try("엑셀 읽기 .xls(xlrd)", lambda: _ver("xlrd")))
    checks.append(_try("사진 처리(Pillow)", lambda: _ver("PIL")))
    checks.append(_try("PDF 글자 추출(PyMuPDF)", lambda: _ver("pymupdf")))
    checks.append(_try("화면(PySide6)", lambda: _ver("PySide6")))

    # --- 엑셀 쓰기 — 이게 없으면 기록을 못 한다 ----------------------
    checks.append(_try("엑셀 쓰기(xlwings + Excel)", _excel))

    # --- 실제로 동작하는지 ------------------------------------------
    checks.append(_try("PDF 에서 글자를 실제로 뽑는가", _pdf_roundtrip))
    checks.append(_try("사진 압축·EXIF 제거가 되는가", _image_roundtrip))

    # --- 선택 부품 ---------------------------------------------------
    from .ocr import get_provider

    p = get_provider()
    checks.append(Check("OCR 엔진(선택)", p is not None,
                        p.name if p else "없음 — 성적서 PDF 는 없어도 읽힌다", 치명적=False))

    # --- 쓰기 권한 ---------------------------------------------------
    checks.append(_try("프로그램 폴더에 쓰기", _writable))

    # --- 내장 자원 ---------------------------------------------------
    for rel in (("workflows", "자재검수.yaml"),
                ("templates", "현장시험", "PHC겉모양치수.yaml"),
                ("templates", "의뢰시험", "재하시험.yaml")):
        path = resource(*rel)
        checks.append(Check(f"내장 자원 {'/'.join(rel)}", path.exists(),
                            "" if path.exists() else str(path)))

    # --- 설정 경로 ---------------------------------------------------
    if cfg is not None:
        _, problems = check_paths(cfg)
        checks.append(Check("설정 경로", not problems,
                            "이상 없음" if not problems else f"{len(problems)}건 확인 필요"))
    return checks


def _ver(module: str) -> str:
    import importlib

    m = importlib.import_module(module)
    return str(getattr(m, "__version__", "") or getattr(m, "VersionBind", "") or "설치됨")


def _excel() -> str:
    import xlwings  # noqa: F401

    if not sys.platform.startswith("win"):
        raise RuntimeError(f"Windows 가 아닙니다 ({sys.platform}) — 쓰기 불가, 읽기는 가능")
    with xlwings.App(visible=False, add_book=False) as app:
        return f"Excel {app.version}"


def _pdf_roundtrip() -> str:
    import pymupdf

    from .extract import extract

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "t.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_text((50, 60), "발급 번호 IS-2026-000000-00",
                                   fontsize=10, fontname="korea")
        doc.save(p)
        doc.close()
        got = extract(p, ocr=False)
        if "IS-2026-000000-00" not in got.text:
            raise RuntimeError("글자를 뽑지 못했습니다")
    return "정상"


def _image_roundtrip() -> str:
    from PIL import Image, ImageOps

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "a.jpg"
        im = Image.new("RGB", (3000, 2000), (120, 130, 140))
        ex = Image.Exif()
        ex[272] = "테스트기기"
        im.save(src, exif=ex, quality=90)

        out = Path(tmp) / "b.jpg"
        with Image.open(src) as o:
            o = ImageOps.exif_transpose(o)
            o.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            o.save(out, quality=85, optimize=True, progressive=True)
        with Image.open(out) as o:
            if dict(o.getexif()):
                raise RuntimeError("EXIF 가 남았습니다")
            if max(o.size) > 1600:
                raise RuntimeError("크기가 줄지 않았습니다")
    return "정상"


def _writable() -> str:
    folder = app_dir()
    probe = folder / ".쓰기확인.tmp"
    probe.write_text("x", encoding="utf-8")
    probe.unlink()
    return str(folder)


def report(cfg: Config | None = None) -> tuple[str, int]:
    """(보고서, 치명적 실패 건수)."""
    checks = run_selftest(cfg)
    치명 = [c for c in checks if not c.통과 and c.치명적]
    선택 = [c for c in checks if not c.통과 and not c.치명적]

    줄 = [describe(), "", "■ 자가 점검"]
    줄 += [str(c) for c in checks]
    줄.append("")
    if 치명:
        줄.append(f"■ 반드시 해결해야 할 것 {len(치명)}건")
        for c in 치명:
            줄.append(f"  - {c.이름}: {c.상세}")
        if any("xlwings" in c.이름 or "Excel" in c.이름 for c in 치명):
            줄.append("    (Excel 이 설치된 Windows 에서만 기록할 수 있습니다. "
                      "읽기·미리보기·판정은 그대로 됩니다.)")
    else:
        줄.append("■ 이 PC 에서 쓸 준비가 됐습니다.")
    if 선택:
        줄.append(f"■ 선택 항목 {len(선택)}건 (없어도 주요 기능은 동작)")
        for c in 선택:
            줄.append(f"  - {c.이름}: {c.상세}")
    if not is_frozen():
        줄.append("(파이썬 소스로 실행 중 — exe 로 만든 뒤에도 한 번 더 확인하세요.)")
    return "\n".join(줄), len(치명)


def make_intake_dirs(cfg: Config) -> list[Path]:
    """서류투입 폴더와 카테고리 칸을 만들어 준다. 회사 PC 첫 준비용."""
    from tasks.document_intake import load_categories
    from .paths import as_path

    root = as_path(cfg.path("intake_root"))
    made: list[Path] = []
    for cat in load_categories(cfg):
        folder = root / cat.name
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            made.append(folder)
        if cat.require_sub:
            안내 = folder / "여기에_폴더를_만들어_넣으세요.txt"
            if not 안내.exists():
                안내.write_text(
                    f"{cat.name} 은(는) 하위폴더가 필요합니다.\n"
                    "폴더 이름이 곧 분류 기준이 됩니다.\n"
                    "  BSCW·JSP  -> 타설일 (예: 0822)\n"
                    "  물시멘트비 -> 시험 회차 (예: 01)\n"
                    "  의뢰시험   -> 시험일과 동-번호 (예: 0824 113-152)\n"
                    "촬영일이 아니라 위 기준으로 묶어야 합니다.\n",
                    encoding="utf-8")
    return made
