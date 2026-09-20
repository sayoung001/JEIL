"""PDF·이미지에서 글자 뽑기 (진단 PART C).

**순서가 중요하다.**

1. PDF 안의 **텍스트 레이어**를 먼저 읽는다. 아이텍 성적서·PHC 생산성적서·
   일부 송장은 전부 여기서 끝난다. 정확도 100%, 비용 0원 (PART C §7).
2. 글자가 거의 안 나오면 그때만 **OCR** 로 넘어간다. 스캔 PDF 는 300dpi 로
   그려서 읽고, 사진은 그대로 읽는다.
3. OCR 엔진이 없으면 **빈 결과를 내지 않고 경고를 남긴다.**

.. warning::
   **반드시 원본에서 읽는다.** 카카오톡으로 받은 사진은 이미 압축돼 글자가
   뭉개져 있다. 그래서 문서 투입(``tasks/document_intake.py``)은
   **읽기 → 압축** 순서로 돌아간다. 거꾸로 하면 읽을 수 있던 것도 못 읽는다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .ocr import OcrResult, get_provider

log = logging.getLogger(__name__)

#: 이 글자 수보다 적게 나오면 "텍스트 레이어가 없다" 고 본다.
MIN_TEXT_CHARS = 40
#: 스캔 PDF 를 OCR 할 때 그리는 해상도. 글자가 작아 200dpi 밑은 잘 안 읽힌다.
OCR_DPI = 300
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


@dataclass
class ExtractedText:
    """뽑아낸 글자와 **어떻게 뽑았는지**."""

    text: str = ""
    방식: str = ""                 # 'pdf-text' | 'ocr:rapidocr' | ''
    pages: list[str] = field(default_factory=list)
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    source: Path | None = None

    @property
    def ok(self) -> bool:
        return len(self.text.strip()) >= MIN_TEXT_CHARS

    @property
    def 텍스트레이어(self) -> bool:
        return self.방식 == "pdf-text"

    def __str__(self) -> str:
        head = f"{self.방식 or '실패'}  {len(self.text)}자"
        if self.confidence is not None:
            head += f"  신뢰도 {self.confidence:.2f}"
        return head


# ---------------------------------------------------------------------
def extract(path: str | Path, *, ocr: bool = True, ocr_engine: str | None = None,
            min_chars: int = MIN_TEXT_CHARS) -> ExtractedText:
    """파일 하나에서 글자를 뽑는다. 실패해도 예외 대신 경고를 담아 돌려준다."""
    p = Path(path)
    out = ExtractedText(source=p)
    if not p.exists():
        out.warnings.append(f"파일이 없습니다: {p}")
        return out

    suffix = p.suffix.lower()
    if suffix == ".pdf":
        out = _from_pdf(p, min_chars=min_chars)
        if not out.ok and ocr:
            out = _pdf_ocr(p, base=out, engine=ocr_engine)
        return out
    if suffix in IMAGE_SUFFIXES:
        if not ocr:
            out.warnings.append("이미지는 OCR 로만 읽을 수 있는데 OCR 이 꺼져 있습니다.")
            return out
        return _image_ocr(p, engine=ocr_engine)

    out.warnings.append(f"글자를 뽑을 수 없는 형식입니다: {p.suffix}")
    return out


# -- PDF 텍스트 레이어 --------------------------------------------------
def _from_pdf(p: Path, *, min_chars: int) -> ExtractedText:
    pages, engine, warnings = _pdf_pages(p)
    text = "\n".join(pages).strip()
    out = ExtractedText(text=text, pages=pages, source=p, warnings=warnings)
    if text and len(text) >= min_chars:
        out.방식 = "pdf-text"
    elif not warnings:
        out.warnings.append(
            f"PDF 에 텍스트 레이어가 거의 없습니다 ({len(text)}자). 스캔본으로 보입니다.")
    return out


def _pdf_pages(p: Path) -> tuple[list[str], str, list[str]]:
    """pymupdf 를 먼저 쓰고, 없으면 pypdf. 둘 다 없으면 경고."""
    try:
        import pymupdf                                    # type: ignore

        with pymupdf.open(p) as doc:
            return [page.get_text() or "" for page in doc], "pymupdf", []
    except ImportError:
        pass
    except Exception as e:
        return [], "", [f"PDF 를 열지 못했습니다 (pymupdf): {e}"]

    try:
        from pypdf import PdfReader                       # type: ignore

        reader = PdfReader(str(p))
        return [(page.extract_text() or "") for page in reader.pages], "pypdf", []
    except ImportError:
        return [], "", ["PDF 를 읽으려면 pymupdf 가 필요합니다: pip install pymupdf"]
    except Exception as e:
        return [], "", [f"PDF 를 열지 못했습니다 (pypdf): {e}"]


# -- OCR 폴백 -----------------------------------------------------------
def _pdf_ocr(p: Path, *, base: ExtractedText, engine: str | None) -> ExtractedText:
    """스캔 PDF — 페이지를 300dpi 로 그려서 읽는다."""
    provider = get_provider(engine)
    if provider is None:
        base.warnings.append(
            "텍스트 레이어가 없고 OCR 엔진도 없어 읽지 못했습니다. "
            "rapidocr-onnxruntime 을 설치하면 읽을 수 있습니다.")
        return base
    try:
        import pymupdf                                    # type: ignore
    except ImportError:
        base.warnings.append("스캔 PDF 를 OCR 하려면 pymupdf 가 필요합니다.")
        return base

    import tempfile

    pages: list[str] = []
    confs: list[float] = []
    try:
        with pymupdf.open(p) as doc, tempfile.TemporaryDirectory() as tmp:
            for i, page in enumerate(doc):
                png = Path(tmp) / f"{i:03d}.png"
                page.get_pixmap(dpi=OCR_DPI).save(png)
                r = provider.read(png)
                pages.append(r.text)
                if r.mean_confidence is not None:
                    confs.append(r.mean_confidence)
    except Exception as e:
        base.warnings.append(f"스캔 PDF OCR 에 실패했습니다: {e}")
        return base

    return ExtractedText(
        text="\n".join(pages).strip(), pages=pages, source=p,
        방식=f"ocr:{provider.name}",
        confidence=(sum(confs) / len(confs)) if confs else None,
        warnings=[*base.warnings, "텍스트 레이어가 없어 OCR 로 읽었습니다. 값을 확인하세요."],
    )


def _image_ocr(p: Path, *, engine: str | None) -> ExtractedText:
    provider = get_provider(engine)
    if provider is None:
        return ExtractedText(source=p, warnings=[
            "OCR 엔진이 없어 사진에서 글자를 읽지 못했습니다. "
            "rapidocr-onnxruntime 을 설치하세요."])
    try:
        r = provider.read(p)
    except Exception as e:
        return ExtractedText(source=p, warnings=[f"OCR 에 실패했습니다: {e}"])
    return ExtractedText(text=r.text, pages=[r.text], source=p,
                         방식=f"ocr:{provider.name}", confidence=r.mean_confidence)


def read_numbers(path: str | Path, *, min_confidence: float = 0.5,
                 engine: str | None = None) -> tuple[list[float], OcrResult | None]:
    """사진에서 숫자만. BSCW·JSP 보드판처럼 숫자 3개만 필요한 곳에 쓴다.

    한글 손글씨는 읽지 않는다 (PART C §8 — 공종·업체명은 값이 고정이고
    날짜는 폴더명에, 시험번호는 프로그램이 매긴다).
    """
    provider = get_provider(engine)
    if provider is None:
        return [], None
    try:
        r = provider.read(path)
    except Exception:
        log.warning("보드판 숫자 읽기 실패: %s", path, exc_info=True)
        return [], None
    return r.numbers(min_confidence=min_confidence), r
