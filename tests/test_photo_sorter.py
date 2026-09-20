"""사진 분류기 검증 (SPEC §24). §24.8 검증 항목을 그대로 재현한다."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from tasks.photo_sorter import Category, PhotoConfig, PhotoSorter


def _photo(path: Path, size=(5712, 4284), exif: bool = True) -> Path:
    """iPhone 원본 크기의 사진을 만든다. exif=True 면 GPS·기종 태그를 심는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size)
    for x in range(0, size[0], 97):              # 압축이 되도록 무늬를 넣는다
        for y in range(0, size[1], 89):
            im.putpixel((x, y), ((x * 7) % 256, (y * 13) % 256, (x + y) % 256))
    if exif:
        from fractions import Fraction

        ex = Image.Exif()
        ex[271] = "Apple"                        # Make
        ex[272] = "iPhone 15 Pro"                # Model
        ex[305] = "26.6"                         # Software
        ex[306] = "2026:09:04 09:14:26"          # DateTime
        ex[274] = 1                              # Orientation
        gps = ex.get_ifd(0x8825)                 # 실제 사진의 GPS 15개 항목 중 대표값
        gps[1] = "N"
        gps[2] = (Fraction(37), Fraction(28), Fraction(5055, 100))
        gps[3] = "E"
        gps[4] = (Fraction(126), Fraction(31), Fraction(391, 100))
        im.save(path, exif=ex, quality=95)
    else:
        im.save(path, quality=95)
    return path


def _cfg(tmp_path: Path) -> PhotoConfig:
    return PhotoConfig(
        input_root=tmp_path / "사진분류",
        backup_root=tmp_path / "사진백업",
        categories=[
            Category("자재검수", tmp_path / "목적지" / "자재검수", "%m%d", False),
            Category("PHC_겉모양", tmp_path / "목적지" / "겉모양", "%Y%m%d", False),
            Category("시료채취", tmp_path / "목적지" / "시료채취", "%Y%m%d", False),
            Category("물시멘트비", tmp_path / "목적지" / "밀크", None, True),
            Category("BSCW", tmp_path / "목적지" / "BSCW", None, True),
            Category("JSP", tmp_path / "목적지" / "JSP", None, True),
        ],
        log_dir=tmp_path / "로그",
    )


@pytest.fixture()
def 정렬기(tmp_path):
    return PhotoSorter(_cfg(tmp_path), today=date(2026, 9, 5))


# =====================================================================
def test_스캔은_파일을_건드리지_않는다(정렬기, tmp_path):
    src = _photo(tmp_path / "사진분류" / "자재검수" / "1.jpg")
    before = src.stat().st_mtime_ns, src.stat().st_size
    plans, blocked = 정렬기.scan()
    assert len(plans) == 1 and blocked == []
    assert (src.stat().st_mtime_ns, src.stat().st_size) == before
    assert not (tmp_path / "목적지").exists()      # 목적지 폴더도 안 만든다


def test_날짜폴더는_카테고리마다_형식이_다르다(정렬기, tmp_path):
    _photo(tmp_path / "사진분류" / "자재검수" / "1.jpg", size=(800, 600))
    _photo(tmp_path / "사진분류" / "PHC_겉모양" / "2.jpg", size=(800, 600))
    plans, _ = 정렬기.scan()
    folders = {p.category: p.target_folder for p in plans}
    assert folders["자재검수"] == "0905"          # %m%d
    assert folders["PHC_겉모양"] == "20260905"    # %Y%m%d


def test_require_sub_카테고리는_폴더없으면_옮기지않고_경고(정렬기, tmp_path):
    """§24.3 — BSCW 사진은 촬영일이 아니라 타설일 폴더로 간다."""
    loose = _photo(tmp_path / "사진분류" / "BSCW" / "1.jpg", size=(800, 600))
    plans, blocked = 정렬기.scan()
    assert plans == []
    assert len(blocked) == 1 and "타설일" in blocked[0]
    정렬기.run(plans, blocked)
    assert loose.exists()                          # 입력 폴더에 그대로 남는다


def test_하위폴더_이름을_그대로_목적지에_쓴다(정렬기, tmp_path):
    _photo(tmp_path / "사진분류" / "BSCW" / "0731" / "a.jpg", size=(800, 600))
    _photo(tmp_path / "사진분류" / "BSCW" / "0801" / "b.jpg", size=(800, 600))
    plans, blocked = 정렬기.scan()
    assert blocked == []
    assert {p.target_folder for p in plans} == {"0731", "0801"}
    정렬기.run(plans)
    assert (tmp_path / "목적지" / "BSCW" / "0731" / "a.jpg").exists()
    assert (tmp_path / "목적지" / "BSCW" / "0801" / "b.jpg").exists()


def test_중첩_하위폴더_구조_보존(정렬기, tmp_path):
    _photo(tmp_path / "사진분류" / "BSCW" / "0807" / "추가" / "c.jpg", size=(800, 600))
    plans, _ = 정렬기.scan()
    정렬기.run(plans)
    assert (tmp_path / "목적지" / "BSCW" / "0807" / "추가" / "c.jpg").exists()


# -- 압축 · EXIF (§24.4, §24.5) ----------------------------------------
def test_압축과_EXIF_전량제거(정렬기, tmp_path):
    src = _photo(tmp_path / "사진분류" / "자재검수" / "1.jpg")
    원본 = src.stat().st_size
    plans, _ = 정렬기.scan()
    result = 정렬기.run(plans)

    out = tmp_path / "목적지" / "자재검수" / "0905" / "1.jpg"
    assert out.exists()
    with Image.open(out) as im:
        assert max(im.size) <= 1600                # 긴 변 1600px
        assert dict(im.getexif()) == {}            # 태그 0개
        assert dict(im.getexif().get_ifd(0x8825)) == {}   # GPS 도 없다
        assert "exif" not in im.info
    assert out.stat().st_size < 원본
    assert result.saved_bytes > 0


def test_백업_원본에는_EXIF가_남아있다(정렬기, tmp_path):
    """대조군 — 원본은 삭제하지 않고 이동만 한다 (§24.6)."""
    _photo(tmp_path / "사진분류" / "자재검수" / "1.jpg")
    plans, _ = 정렬기.scan()
    정렬기.run(plans)
    backup = tmp_path / "사진백업" / "20260905" / "자재검수" / "0905" / "1.jpg"
    assert backup.exists()
    with Image.open(backup) as im:
        exif = im.getexif()
        assert exif.get(272) == "iPhone 15 Pro"
        assert exif.get(306) == "2026:09:04 09:14:26"
        assert dict(exif.get_ifd(0x8825))          # GPS 그대로


def test_이미_작은_사진은_리사이즈_생략(정렬기, tmp_path):
    _photo(tmp_path / "사진분류" / "자재검수" / "small.jpg", size=(1200, 900))
    plans, _ = 정렬기.scan()
    정렬기.run(plans)
    out = tmp_path / "목적지" / "자재검수" / "0905" / "small.jpg"
    with Image.open(out) as im:
        assert im.size == (1200, 900)              # 크기 그대로
        assert dict(im.getexif()) == {}            # EXIF 만 제거


def test_이름충돌은_2_3으로_리네임(정렬기, tmp_path):
    dest = tmp_path / "목적지" / "자재검수" / "0905"
    dest.mkdir(parents=True)
    기존 = _photo(dest / "1.jpg", size=(400, 300), exif=False)
    기존크기 = 기존.stat().st_size
    _photo(tmp_path / "사진분류" / "자재검수" / "1.jpg", size=(800, 600))
    plans, _ = 정렬기.scan()
    정렬기.run(plans)
    assert (dest / "1_2.jpg").exists()
    assert 기존.stat().st_size == 기존크기         # 기존 파일은 그대로


def test_무시목록과_확장자밖_파일은_남는다(정렬기, tmp_path):
    folder = tmp_path / "사진분류" / "자재검수"
    folder.mkdir(parents=True)
    (folder / "Thumbs.db").write_bytes(b"x")
    (folder / "메모.txt").write_text("메모", encoding="utf-8")
    _photo(folder / "1.jpg", size=(800, 600))
    plans, _ = 정렬기.scan()
    assert len(plans) == 1
    정렬기.run(plans)
    assert (folder / "Thumbs.db").exists()
    assert (folder / "메모.txt").exists()


def test_사진이_0장이면_목적지폴더를_만들지_않는다(정렬기, tmp_path):
    (tmp_path / "사진분류" / "JSP").mkdir(parents=True)
    plans, blocked = 정렬기.scan()
    result = 정렬기.run(plans, blocked)
    assert result.moved == []
    assert not (tmp_path / "목적지").exists()


def test_한장이_실패해도_나머지는_진행(정렬기, tmp_path):
    folder = tmp_path / "사진분류" / "자재검수"
    _photo(folder / "good.jpg", size=(800, 600))
    (folder / "broken.jpg").write_text("이건 이미지가 아니다", encoding="utf-8")
    plans, _ = 정렬기.scan()
    result = 정렬기.run(plans)
    assert len(result.moved) == 1 and len(result.failed) == 1
    assert (folder / "broken.jpg").exists()        # 실패한 파일은 입력에 남는다


def test_오래된_백업만_삭제(정렬기, tmp_path):
    오래 = tmp_path / "사진백업" / "20260801"      # 35일 전
    최근 = tmp_path / "사진백업" / "20260831"      # 5일 전
    for p in (오래, 최근):
        p.mkdir(parents=True)
        (p / "x.jpg").write_bytes(b"x")
    정렬기.run([])
    assert not 오래.exists()
    assert 최근.exists()


def test_비워진_입력_하위폴더는_정리된다(정렬기, tmp_path):
    sub = tmp_path / "사진분류" / "BSCW" / "0731"
    _photo(sub / "a.jpg", size=(800, 600))
    plans, _ = 정렬기.scan()
    정렬기.run(plans)
    assert not sub.exists()
    assert (tmp_path / "사진분류" / "BSCW").exists()   # 카테고리 폴더는 남는다


def test_dry_run은_아무것도_바꾸지_않는다(정렬기, tmp_path):
    src = _photo(tmp_path / "사진분류" / "자재검수" / "1.jpg", size=(800, 600))
    plans, blocked = 정렬기.scan()
    result = 정렬기.run(plans, blocked, dry_run=True)
    assert len(result.moved) == 1
    assert src.exists()
    assert not (tmp_path / "목적지").exists()
