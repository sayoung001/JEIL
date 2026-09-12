"""PC 가 바뀌어도 도는가 — 경로 해석과 실행 위치 (노트북 빌드 → 회사 PC 실행)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

from core import paths
from core.config import check_paths, load_config


def _write(tmp_path: Path, paths_block: dict) -> Path:
    """paths 절만 바꾼 최소 설정 파일."""
    cfg = {
        "paths": paths_block,
        "files": {"supply_check": "{quality_root}/체크용.xlsx"},
        "vendor_alias": {"KCC": {"체크용": "KCC", "갑지": "㈜KCC 글라스",
                                 "수불부": "KCC글라스", "시험601": "㈜KCC글라스",
                                 "대장": "KCC글라스"}},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


# =====================================================================
# 경로 후보 고르기
# =====================================================================
def test_실제로_있는_후보를_고른다(tmp_path):
    """노트북과 회사 PC 경로를 둘 다 적어 두면, 있는 쪽이 선택된다."""
    노트북 = tmp_path / "E_품질_전체"
    회사 = tmp_path / "C_품질_전체"
    노트북.mkdir()                                  # 노트북에만 있다
    cfg = load_config(_write(tmp_path, {"quality_root": [str(회사), str(노트북)]}))
    assert cfg.path("quality_root") == str(노트북)
    assert cfg.raw["files"]["supply_check"] == f"{노트북}/체크용.xlsx"


def test_회사PC에서는_회사_경로가_선택된다(tmp_path):
    노트북 = tmp_path / "E_품질_전체"
    회사 = tmp_path / "C_품질_전체"
    회사.mkdir()                                    # 이번엔 회사에만 있다
    cfg = load_config(_write(tmp_path, {"quality_root": [str(회사), str(노트북)]}))
    assert cfg.path("quality_root") == str(회사)


def test_둘_다_있으면_먼저_적은_쪽(tmp_path):
    첫째 = tmp_path / "첫째"
    둘째 = tmp_path / "둘째"
    첫째.mkdir()
    둘째.mkdir()
    cfg = load_config(_write(tmp_path, {"quality_root": [str(첫째), str(둘째)]}))
    assert cfg.path("quality_root") == str(첫째)


def test_아직_없는_출력폴더는_상위가_있는_후보를_고른다(tmp_path):
    """백업 폴더처럼 없으면 만들면 되는 곳. 상위가 있는 후보를 고른다."""
    없는드라이브 = "/없는드라이브/백업"
    만들수있음 = tmp_path / "백업"                  # tmp_path 는 있다
    cfg = load_config(_write(tmp_path, {
        "quality_root": [str(tmp_path)],
        "backup_root": [없는드라이브, str(만들수있음)],
    }))
    assert cfg.path("backup_root") == str(만들수있음)


def test_하나도_없으면_마지막_후보(tmp_path):
    cfg = load_config(_write(tmp_path, {
        "quality_root": ["/없는곳1/x/y", "/없는곳2/x/y"]}))
    assert cfg.path("quality_root") == "/없는곳2/x/y"


def test_문자열_하나만_적어도_된다(tmp_path):
    """기존 방식(목록 아님)도 그대로 동작해야 한다."""
    cfg = load_config(_write(tmp_path, {"quality_root": str(tmp_path)}))
    assert cfg.path("quality_root") == str(tmp_path)


def test_app_dir_자리표시자(tmp_path):
    """{app_dir} 는 프로그램이 놓인 폴더. 어느 PC 에서든 반드시 있다."""
    cfg = load_config(_write(tmp_path, {
        "quality_root": ["/없는곳/품질"],
        "backup_root": ["/없는곳/백업", "{app_dir}/백업"]}))
    assert cfg.path("backup_root") == f"{paths.app_dir()}/백업"


def test_환경변수가_후보보다_먼저다(tmp_path, monkeypatch):
    """QUALITY_ROOT 로 그 PC 만의 경로를 임시로 덮어쓸 수 있다."""
    후보 = tmp_path / "설정에_적힌곳"
    환경 = tmp_path / "환경변수로_준곳"
    후보.mkdir()
    환경.mkdir()
    monkeypatch.setenv("QUALITY_ROOT", str(환경))
    cfg = load_config(_write(tmp_path, {"quality_root": [str(후보)]}))
    assert cfg.path("quality_root") == str(환경)


# =====================================================================
# 경로 확인 보고
# =====================================================================
def test_경로확인이_문제를_짚어준다(tmp_path):
    cfg = load_config(_write(tmp_path, {"quality_root": ["/없는곳/품질_전체"]}))
    lines, problems = check_paths(cfg)
    assert any("품질 폴더를 찾을 수 없습니다" in p for p in problems)
    assert any("quality_root" in ln for ln in lines)
    assert any("supply_check" in ln for ln in lines)      # files 도 함께 본다


def test_경로가_다_맞으면_문제가_없다(tmp_path):
    (tmp_path / "체크용.xlsx").write_text("x", encoding="utf-8")
    cfg = load_config(_write(tmp_path, {"quality_root": [str(tmp_path)]}))
    _, problems = check_paths(cfg)
    assert problems == []


# =====================================================================
# exe / 소스 실행 위치
# =====================================================================
def test_소스실행에서는_두_위치가_같다():
    assert paths.is_frozen() is False
    assert paths.app_dir() == paths.bundle_dir()


def test_exe에서는_설정이_exe옆_로그도_exe옆(tmp_path, monkeypatch):
    """--onefile 의 함정: 내장 폴더에 쓰면 실행이 끝나며 사라진다."""
    exe_폴더 = tmp_path / "회사PC바탕화면"
    내장 = tmp_path / "_MEI임시"
    exe_폴더.mkdir()
    내장.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(내장), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_폴더 / "품질자동화.exe"))

    assert paths.is_frozen() is True
    assert paths.app_dir() == exe_폴더          # 설정·로그·상태
    assert paths.bundle_dir() == 내장           # 구워 넣은 자원
    assert paths.config_path() == exe_폴더 / "config.yaml"
    assert paths.writable("logs", "a.log").parent == exe_폴더 / "logs"


def test_자원은_내장폴더에서_찾되_exe옆이_우선(tmp_path, monkeypatch):
    exe_폴더 = tmp_path / "exe"
    내장 = tmp_path / "mei"
    (내장 / "templates" / "현장시험").mkdir(parents=True)
    (내장 / "templates" / "현장시험" / "PHC밀크.yaml").write_text("x", encoding="utf-8")
    exe_폴더.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(내장), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_폴더 / "품질자동화.exe"))

    # exe 옆에 없으면 내장에서
    assert paths.resource("templates", "현장시험", "PHC밀크.yaml").parent.parent.parent == 내장

    # exe 옆에 두면 그쪽이 이긴다 (exe 를 다시 만들지 않고 항목 추가)
    옆 = exe_폴더 / "templates" / "현장시험"
    옆.mkdir(parents=True)
    (옆 / "PHC밀크.yaml").write_text("y", encoding="utf-8")
    assert paths.resource("templates", "현장시험", "PHC밀크.yaml").parent.parent.parent == exe_폴더


def test_설정이_없으면_예시에서_만들어_준다(tmp_path, monkeypatch):
    """처음 쓰는 PC 에서 '설정 파일이 없습니다' 로 막히지 않게."""
    exe_폴더 = tmp_path / "exe"
    내장 = tmp_path / "mei"
    exe_폴더.mkdir()
    내장.mkdir()
    (내장 / "config.example.yaml").write_text(
        "paths:\n  quality_root: 'C:\\품질_전체'\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(내장), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_폴더 / "품질자동화.exe"))

    target, created = paths.ensure_config()
    assert created is True
    assert target == exe_폴더 / "config.yaml"
    assert "quality_root" in target.read_text(encoding="utf-8")

    again, created_again = paths.ensure_config()      # 두 번째는 덮어쓰지 않는다
    assert created_again is False
    assert again == target


def test_실제_예시설정에_노트북과_회사경로가_둘_다_있다():
    """빌드 PC 와 실행 PC 가 다르다는 전제가 설정에 실제로 반영돼 있는가."""
    example = paths.bundle_dir() / "config.example.yaml"
    raw = yaml.safe_load(example.read_text(encoding="utf-8"))
    roots = raw["paths"]["quality_root"]
    assert isinstance(roots, list), "quality_root 는 PC 별 후보 목록이어야 한다"
    assert any(r.upper().startswith("E:") for r in roots), "노트북 E 드라이브 경로"
    assert any("Desktop" in r for r in roots), "회사 PC 바탕화면 경로"
