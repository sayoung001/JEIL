"""config.yaml 로딩 (SPEC §2).

경로 문자열의 ``{quality_root}`` 같은 자리표시자를 재귀적으로 풀어준다.
Windows 경로를 그대로 담고 있으므로 pathlib 변환은 사용하는 쪽에서 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_MAX_DEPTH = 10


def _expand(value: str, table: dict[str, str]) -> str:
    """'{quality_root}\\G. 자재' -> 실제 경로. 중첩 자리표시자도 푼다."""
    for _ in range(_MAX_DEPTH):
        m = _PLACEHOLDER.search(value)
        if not m:
            return value
        new = _PLACEHOLDER.sub(lambda x: str(table.get(x.group(1), x.group(0))), value)
        if new == value:
            return value
        value = new
    raise ValueError(f"경로 자리표시자가 순환합니다: {value!r}")


def _expand_tree(node: Any, table: dict[str, str]) -> Any:
    if isinstance(node, str):
        return _expand(node, table)
    if isinstance(node, dict):
        return {k: _expand_tree(v, table) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_tree(v, table) for v in node]
    return node


class VendorAlias:
    """업체명 표기 계열 5종 변환 (SPEC §4.3).

    파일마다 표기가 다르다. 반드시 이 객체를 거쳐서 쓴다.
    """

    KEYS = ("체크용", "갑지", "수불부", "시험601", "대장")

    def __init__(self, table: dict[str, dict[str, str]]):
        self._table = table
        # 어떤 계열의 표기로 들어와도 표준 키를 찾을 수 있게 역인덱스를 만든다.
        self._reverse: dict[str, str] = {}
        for canonical, forms in table.items():
            self._reverse[canonical.strip()] = canonical
            for form in forms.values():
                self._reverse[str(form).strip()] = canonical

    @property
    def canonical_names(self) -> list[str]:
        return list(self._table)

    def canonical(self, name: str | None) -> str | None:
        """어떤 표기든 표준 키로. 모르는 이름이면 None (§16.0 — 조용히 무시 금지)."""
        if name is None:
            return None
        return self._reverse.get(str(name).strip())

    def form(self, name: str, kind: str) -> str:
        """표준 키(또는 아무 표기) -> 해당 파일 계열의 표기."""
        if kind not in self.KEYS:
            raise KeyError(f"알 수 없는 표기 계열: {kind} (가능: {self.KEYS})")
        canonical = self.canonical(name)
        if canonical is None:
            raise KeyError(f"vendor_alias 에 없는 업체명: {name!r}")
        return self._table[canonical][kind]

    def __contains__(self, name: object) -> bool:
        return self.canonical(str(name)) is not None


@dataclass
class Config:
    raw: dict[str, Any]
    source: Path | None = None
    vendors: VendorAlias = field(init=False)

    def __post_init__(self) -> None:
        self.vendors = VendorAlias(self.raw.get("vendor_alias", {}))

    # -- 편의 접근자 ---------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        """cfg.get('test_rules.phc_shape.threshold_bon', 200)"""
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, key: str) -> str:
        """files.<key> 또는 paths.<key> 의 확장된 경로 문자열."""
        for section in ("files", "paths"):
            table = self.raw.get(section, {})
            if key in table:
                return table[key]
        raise KeyError(f"config 에 경로가 없습니다: {key}")

    @property
    def people(self) -> dict[str, Any]:
        return self.raw.get("people", {})

    @property
    def defaults(self) -> dict[str, Any]:
        return self.raw.get("defaults", {})


def load_config(path: str | Path = "config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"설정 파일이 없습니다: {p}\n"
            "config.example.yaml 을 config.yaml 로 복사한 뒤 경로를 고치세요."
        )
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    table = dict(raw.get("paths", {}))
    raw = _expand_tree(raw, table)
    return Config(raw=raw, source=p)
