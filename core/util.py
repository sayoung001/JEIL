"""작은 공용 도구."""
from __future__ import annotations

import hashlib
import os
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any


def sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Path):
        return str(o)
    if hasattr(o, "__dict__"):
        return o.__dict__
    return str(o)


def is_locked(path: str | Path) -> bool:
    """엑셀이 파일을 열어 두면 같은 폴더에 ``~$이름.xlsx`` 잠금 파일이 생긴다 (§10 #7)."""
    p = Path(path)
    if (p.parent / f"~${p.name}").exists():
        return True
    if not p.exists():
        return False
    try:                                   # 쓰기 모드로 열어 본다 (내용은 안 건드림)
        with open(p, "r+b"):
            return False
    except OSError:
        return True


def atomic_replace(temp: str | Path, target: str | Path) -> None:
    """검증을 통과한 임시 사본을 원본 자리로 원자적 교체 (§2.2)."""
    os.replace(str(temp), str(target))


def has_zip_entry(path: str | Path, entry: str) -> bool:
    """xlsx zip 안에 특정 파트가 남아 있는지. 도형 유실 감시용 (§5.3)."""
    p = Path(path)
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        return False
    try:
        with zipfile.ZipFile(p) as z:
            return entry in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def zip_entries(path: str | Path, prefix: str = "") -> list[str]:
    try:
        with zipfile.ZipFile(Path(path)) as z:
            return [n for n in z.namelist() if n.startswith(prefix)]
    except (OSError, zipfile.BadZipFile):
        return []


def as_date(value: Any) -> date | None:
    """엑셀에서 읽은 값(문자열/datetime/숫자)을 date 로."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d", "%y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    for suffix in ("본", "개", "EA", "m", "%"):
        text = text.replace(suffix, "")
    try:
        return float(text.strip())
    except ValueError:
        return None
