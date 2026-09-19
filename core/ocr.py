"""OCR 제공자 — **선택 부품이다.**

진단 결과(PART C §7) 성적서 PDF 는 전부 텍스트 레이어를 갖고 있어
**OCR 없이 텍스트 추출만으로 100% 읽힌다.** OCR 은 그 레이어가 없는
스캔 PDF·사진에만 쓰는 보조 수단이다.

그래서 OCR 엔진을 프로그램에 **필수로 묶지 않는다.**

* 엔진이 깔려 있으면 자동으로 찾아 쓴다.
* 없으면 **조용히 빈 결과를 내지 않고**, "OCR 엔진이 없다" 고 분명히 알린다.
  조용히 넘어가면 사람은 글자가 없는 문서라고 착각한다.

권장 엔진은 ``rapidocr-onnxruntime`` 이다. pip 만으로 끝나고(별도 프로그램 설치
불필요), 모델이 수십 MB 라 exe 에 넣어도 감당이 된다. Tesseract 는 별도 설치가
필요해 회사 PC 에 권하지 않는다.

.. warning::
   **원본에서 읽어야 한다.** 카카오톡으로 받은 사진은 이미 압축돼 글자가 뭉개진다.
   그래서 이 프로그램은 **압축하기 전 원본에서 먼저 읽고**, 그 다음에 압축한다
   (``tasks/document_intake.py``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


class OcrUnavailable(RuntimeError):
    """쓸 수 있는 OCR 엔진이 없다. 삼켜서는 안 되는 예외."""


@dataclass
class OcrLine:
    text: str
    confidence: float | None = None
    box: tuple[float, float, float, float] | None = None   # (x1, y1, x2, y2)


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = ""

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    @property
    def mean_confidence(self) -> float | None:
        vals = [ln.confidence for ln in self.lines if ln.confidence is not None]
        return sum(vals) / len(vals) if vals else None

    def numbers(self, min_confidence: float = 0.0) -> list[float]:
        """숫자만 뽑는다. 보드판처럼 '숫자 3개' 만 필요한 곳에 쓴다 (PART C §8)."""
        import re

        out: list[float] = []
        for ln in self.lines:
            if ln.confidence is not None and ln.confidence < min_confidence:
                continue
            for m in re.finditer(r"\d+(?:[.,]\d+)?", ln.text):
                try:
                    out.append(float(m.group().replace(",", ".")))
                except ValueError:
                    continue
        return out


class OcrProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def read(self, image: str | Path) -> OcrResult: ...


# ---------------------------------------------------------------------
class RapidOcr:
    """rapidocr-onnxruntime — pip 만으로 끝난다. 회사 PC 권장."""

    name = "rapidocr"
    install = "pip install rapidocr-onnxruntime"

    def __init__(self) -> None:
        self._engine: Any = None

    def available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True

    def _get(self) -> Any:
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def read(self, image: str | Path) -> OcrResult:
        result, _ = self._get()(str(image))
        lines: list[OcrLine] = []
        for item in result or []:
            box, text, conf = item[0], item[1], item[2]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append(OcrLine(text=str(text), confidence=float(conf),
                                 box=(min(xs), min(ys), max(xs), max(ys))))
        return OcrResult(lines=lines, engine=self.name)


class EasyOcr:
    """easyocr — 진단 문서가 실측한 엔진. torch 를 끌고 와 무겁다."""

    name = "easyocr"
    install = "pip install easyocr"

    def __init__(self, languages: tuple[str, ...] = ("ko", "en")) -> None:
        self.languages = list(languages)
        self._reader: Any = None

    def available(self) -> bool:
        try:
            import easyocr  # noqa: F401
        except ImportError:
            return False
        return True

    def _get(self) -> Any:
        if self._reader is None:
            import easyocr

            self._reader = easyocr.Reader(self.languages, gpu=False, verbose=False)
        return self._reader

    def read(self, image: str | Path) -> OcrResult:
        rows = self._get().readtext(str(image))
        lines = []
        for box, text, conf in rows:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append(OcrLine(text=str(text), confidence=float(conf),
                                 box=(min(xs), min(ys), max(xs), max(ys))))
        return OcrResult(lines=lines, engine=self.name)


class TesseractOcr:
    """pytesseract — **Tesseract 프로그램을 따로 설치**해야 한다. 회사 PC 비권장."""

    name = "tesseract"
    install = "pip install pytesseract + Tesseract-OCR 별도 설치 (한국어 데이터 포함)"

    def available(self) -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
        except Exception:
            return False
        return True

    def read(self, image: str | Path) -> OcrResult:
        import pytesseract
        from PIL import Image

        data = pytesseract.image_to_data(Image.open(image), lang="kor+eng",
                                         output_type=pytesseract.Output.DICT)
        lines: list[OcrLine] = []
        for i, text in enumerate(data["text"]):
            if not str(text).strip():
                continue
            try:
                conf = float(data["conf"][i]) / 100.0
            except (ValueError, TypeError):
                conf = None
            x, y = data["left"][i], data["top"][i]
            lines.append(OcrLine(text=str(text), confidence=conf,
                                 box=(x, y, x + data["width"][i], y + data["height"][i])))
        return OcrResult(lines=lines, engine=self.name)


#: 찾는 순서. 앞의 것이 깔려 있으면 그것을 쓴다.
PROVIDERS: list[OcrProvider] = [RapidOcr(), EasyOcr(), TesseractOcr()]


def get_provider(preferred: str | None = None) -> OcrProvider | None:
    """쓸 수 있는 엔진 하나. 없으면 None (예외를 내지 않는다 — 호출부가 판단)."""
    if preferred:
        for p in PROVIDERS:
            if p.name == preferred:
                return p if p.available() else None
        log.warning("모르는 OCR 엔진 이름입니다: %s", preferred)
        return None
    for p in PROVIDERS:
        if p.available():
            return p
    return None


def require_provider(preferred: str | None = None) -> OcrProvider:
    p = get_provider(preferred)
    if p is None:
        raise OcrUnavailable(
            "OCR 엔진이 설치돼 있지 않습니다.\n"
            "  성적서 PDF 는 대부분 텍스트 레이어가 있어 OCR 없이 읽힙니다.\n"
            "  스캔본·사진을 읽어야 할 때만 아래 중 하나를 설치하세요.\n"
            + "\n".join(f"    · {p.name}: {getattr(p, 'install', '')}" for p in PROVIDERS)
        )
    return p


def describe() -> str:
    """[경로 확인] 화면과 --paths 에 함께 보여 줄 OCR 상태."""
    lines = ["■ OCR 엔진 (선택 — 성적서 PDF 는 없어도 읽힌다)"]
    found = False
    for p in PROVIDERS:
        ok = p.available()
        found = found or ok
        mark = "O" if ok else " "
        lines.append(f"  [{mark}] {p.name:<12}{'' if ok else getattr(p, 'install', '')}")
    if not found:
        lines.append("      -> 없음. 텍스트 레이어가 없는 스캔본은 읽지 못합니다.")
    return "\n".join(lines)
