"""문서 투입 세 갈래 — 압축분류 · 원본분류 · 성적서."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from PIL import Image

from core.config import Config
from core.util import sha256
from tasks.document_intake import DocumentIntake, Lane
from tests.fixtures import cfg as base_cfg

pymupdf = pytest.importorskip("pymupdf")

재하_TEXT = """시험성적서
발급 번호 IS-2026-156157-00      접수 일자 2026.08.24
시험명 시항타 / 동재하 (KS F 2591)
결과   전체지지력(초기항타) : 2815 (kN/본)
       ·시험검사: 2026-08-24
       ·채취장소: 113동 No.152
       ·허용지지력(안전율2.5적용): 1126.0kN/본
       ·설계지지력: 1300.0kN/본"""


def _사진(path: Path, size=(4000, 3000)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size)
    for x in range(0, size[0], 91):
        for y in range(0, size[1], 87):
            im.putpixel((x, y), ((x * 7) % 256, (y * 13) % 256, (x + y) % 256))
    ex = Image.Exif()
    ex[271], ex[272] = "Apple", "iPhone 15 Pro"
    ex[306] = "2026:09:04 09:14:26"
    im.save(path, exif=ex, quality=95)
    return path


def _pdf(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 60), text, fontsize=9, fontname="korea")
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def 환경(tmp_path):
    """실제 config.example.yaml 의 documents 절을 그대로 쓰되 경로만 임시로."""
    root = Path(__file__).resolve().parent.parent
    raw = yaml.safe_load((root / "config.example.yaml").read_text(encoding="utf-8"))
    raw["paths"] = {"quality_root": str(tmp_path / "품질_전체"),
                    "intake_root": str(tmp_path / "서류투입"),
                    "backup_root": str(tmp_path / "백업"),
                    "photo_sort_root": str(tmp_path / "서류투입"),
                    "photo_backup_root": str(tmp_path / "사진백업"),
                    "state_dir": str(tmp_path / "상태"),
                    "photo_inbox": str(tmp_path / "임시")}
    table = dict(raw["paths"])
    import re

    def expand(node):
        if isinstance(node, str):
            return re.sub(r"\{(\w+)\}", lambda m: table.get(m.group(1), m.group(0)), node)
        if isinstance(node, dict):
            return {k: expand(v) for k, v in node.items()}
        if isinstance(node, list):
            return [expand(v) for v in node]
        return node

    raw = expand(raw)
    raw["paths"] = table
    return Config(raw=raw)


def _intake(환경) -> DocumentIntake:
    return DocumentIntake(환경, today=date(2026, 9, 19))


# =====================================================================
# 레인 배정
# =====================================================================
def test_카테고리가_세_갈래로_나뉜다(환경):
    lanes = {c.name: c.lane for c in _intake(환경).categories}
    assert lanes["BSCW"] is Lane.압축분류
    assert lanes["물시멘트비"] is Lane.압축분류
    assert lanes["자재검수"] is Lane.압축분류
    assert lanes["의뢰시험_재하"] is Lane.원본분류
    assert lanes["의뢰시험_MT"] is Lane.원본분류
    assert lanes["성적서_재하"] is Lane.성적서
    assert lanes["송장"] is Lane.성적서


# =====================================================================
# 압축분류 — 각종시험·자재검수
# =====================================================================
def test_각종시험_사진은_압축되고_메타가_지워진다(환경, tmp_path):
    _사진(tmp_path / "서류투입" / "BSCW" / "0731" / "a.jpg")
    intake = _intake(환경)
    items, blocked = intake.scan()
    assert blocked == [] and len(items) == 1
    원본크기 = items[0].src_bytes
    result = intake.run(items)

    out = tmp_path / "품질_전체" / "Q. 각종시험" / "03. 토목가시설 관련" / "BSCW" / "0731" / "a.jpg"
    assert out.exists()
    with Image.open(out) as im:
        assert max(im.size) <= 1600
        assert dict(im.getexif()) == {}          # 촬영일시·기종 전부 제거
    assert out.stat().st_size < 원본크기
    assert result.saved_bytes > 0


def test_자재검수_사진도_압축된다(환경, tmp_path):
    _사진(tmp_path / "서류투입" / "자재검수" / "b.jpg")
    intake = _intake(환경)
    items, _ = intake.scan()
    intake.run(items)
    out = tmp_path / "품질_전체" / "00. 사진관리" / "자재검수" / "01.PHC파일" / "0919" / "b.jpg"
    assert out.exists()
    with Image.open(out) as im:
        assert dict(im.getexif()) == {}


# =====================================================================
# 원본분류 — 의뢰시험은 손대지 않는다
# =====================================================================
def test_의뢰시험_사진은_원본_그대로_옮겨진다(환경, tmp_path):
    src = _사진(tmp_path / "서류투입" / "의뢰시험_재하" / "0824 113-152" / "c.jpg")
    원본해시 = sha256(src)
    원본크기 = src.stat().st_size

    intake = _intake(환경)
    items, blocked = intake.scan()
    assert blocked == [] and items[0].lane is Lane.원본분류
    intake.run(items)

    out = (tmp_path / "품질_전체" / "N. 의뢰시험" / "03. 의뢰시험 사진" / "06. 재하"
           / "0824 113-152" / "c.jpg")
    assert out.exists()
    assert sha256(out) == 원본해시              # 바이트 단위로 동일
    assert out.stat().st_size == 원본크기
    with Image.open(out) as im:
        assert im.getexif().get(272) == "iPhone 15 Pro"   # 메타도 그대로


def test_의뢰시험_MT도_원본보존(환경, tmp_path):
    src = _사진(tmp_path / "서류투입" / "의뢰시험_MT" / "0916" / "d.jpg", size=(3000, 2000))
    해시 = sha256(src)
    intake = _intake(환경)
    intake.run(_intake(환경).scan()[0])
    out = (tmp_path / "품질_전체" / "N. 의뢰시험" / "03. 의뢰시험 사진" / "05. MT"
           / "0916" / "d.jpg")
    assert sha256(out) == 해시


def test_의뢰시험도_하위폴더가_필요하다(환경, tmp_path):
    _사진(tmp_path / "서류투입" / "의뢰시험_재하" / "loose.jpg", size=(800, 600))
    items, blocked = _intake(환경).scan()
    assert items == []
    assert len(blocked) == 1 and "동-번호" in blocked[0]


# =====================================================================
# 성적서 — 원본에서 읽고, 원본으로 보관
# =====================================================================
def test_성적서는_원본에서_읽힌다(환경, tmp_path):
    _pdf(tmp_path / "서류투입" / "성적서_재하" / "IS-2026-156157-00.pdf", 재하_TEXT)
    items, _ = _intake(환경).scan()
    assert len(items) == 1
    item = items[0]
    assert item.lane is Lane.성적서
    assert item.extracted.방식 == "pdf-text"      # OCR 없이 읽었다
    assert item.parsed.종류 == "재하성적서"
    assert item.parsed.get("허용지지력") == 1126.0
    assert item.parsed.get("동") == "113"


def test_성적서_PDF는_원본으로_보관된다(환경, tmp_path):
    src = _pdf(tmp_path / "서류투입" / "성적서_재하" / "a.pdf", 재하_TEXT)
    해시 = sha256(src)
    intake = _intake(환경)
    items, _ = intake.scan()
    result = intake.run(items)
    out = tmp_path / "품질_전체" / "N. 의뢰시험" / "02. 의뢰시험 성적서" / "a.pdf"
    assert sha256(out) == 해시
    assert len(result.parsed) == 1


def test_스캔은_파일을_건드리지_않는다(환경, tmp_path):
    src = _pdf(tmp_path / "서류투입" / "성적서_MT" / "m.pdf", 재하_TEXT)
    before = src.stat().st_mtime_ns, sha256(src)
    _intake(환경).scan()
    assert (src.stat().st_mtime_ns, sha256(src)) == before
    assert not (tmp_path / "품질_전체").exists()


def test_읽기가_압축보다_먼저다(환경, tmp_path):
    """카카오톡 사진 대응 — 원본에서 읽어야 하므로 scan 단계에서 추출한다."""
    _pdf(tmp_path / "서류투입" / "성적서_재하" / "a.pdf", 재하_TEXT)
    items, _ = _intake(환경).scan()
    # run() 전에 이미 파싱이 끝나 있다
    assert items[0].parsed is not None
    assert items[0].parsed.읽힘


def test_읽기를_끄면_추출하지_않는다(환경, tmp_path):
    _pdf(tmp_path / "서류투입" / "성적서_재하" / "a.pdf", 재하_TEXT)
    items, _ = _intake(환경).scan(read_documents=False)
    assert items[0].parsed is None


# =====================================================================
# 공통 안전 규칙
# =====================================================================
def test_이름충돌은_리네임(환경, tmp_path):
    dest = tmp_path / "품질_전체" / "N. 의뢰시험" / "02. 의뢰시험 성적서"
    dest.mkdir(parents=True)
    기존 = _pdf(dest / "a.pdf", "다른 내용")
    기존해시 = sha256(기존)
    _pdf(tmp_path / "서류투입" / "성적서_재하" / "a.pdf", 재하_TEXT)
    intake = _intake(환경)
    intake.run(intake.scan()[0])
    assert (dest / "a_2.pdf").exists()
    assert sha256(기존) == 기존해시             # 기존 파일은 그대로


def test_한건_실패해도_나머지는_진행(환경, tmp_path):
    folder = tmp_path / "서류투입" / "자재검수"
    _사진(folder / "good.jpg", size=(800, 600))
    (folder / "broken.jpg").write_text("이미지가 아님", encoding="utf-8")
    intake = _intake(환경)
    result = intake.run(intake.scan()[0])
    assert len(result.moved) == 1 and len(result.failed) == 1
    assert (folder / "broken.jpg").exists()


def test_임시파일과_무시목록은_건너뛴다(환경, tmp_path):
    folder = tmp_path / "서류투입" / "자재검수"
    folder.mkdir(parents=True)
    (folder / "Thumbs.db").write_bytes(b"x")
    (folder / "~$문서.xlsx").write_text("잠금", encoding="utf-8")
    _사진(folder / "ok.jpg", size=(800, 600))
    items, _ = _intake(환경).scan()
    assert len(items) == 1 and items[0].src.name == "ok.jpg"


def test_dry_run은_아무것도_바꾸지_않는다(환경, tmp_path):
    src = _사진(tmp_path / "서류투입" / "자재검수" / "a.jpg", size=(800, 600))
    intake = _intake(환경)
    items, blocked = intake.scan()
    result = intake.run(items, blocked, dry_run=True)
    assert len(result.moved) == 1
    assert src.exists()
    assert not (tmp_path / "품질_전체").exists()
