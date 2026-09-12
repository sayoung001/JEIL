"""config.yaml 로딩 (SPEC §2).

경로 문자열의 ``{quality_root}`` 같은 자리표시자를 재귀적으로 풀어준다.
Windows 경로를 그대로 담고 있으므로 pathlib 변환은 사용하는 쪽에서 한다.

**PC 마다 경로가 다른 문제** — 노트북은 ``E:\\품질_전체``, 회사 PC 는
``C:\\Users\\us\\Desktop\\품질_전체`` 에 있다. 그래서 ``paths`` 의 값은
**목록으로 적을 수 있다.** 실행하는 PC 에서 실제로 있는 것을 골라 쓴다.

.. code-block:: yaml

    paths:
      quality_root:
        - 'E:\\품질_전체'                   # 노트북
        - 'C:\\Users\\us\\Desktop\\품질_전체'   # 회사 PC

고르는 규칙은 세 단계다.

1. 실제로 있는 첫 번째 항목
2. 없으면, 상위 폴더가 있는 첫 번째 항목 (아직 안 만든 출력 폴더용)
3. 그것도 없으면 마지막 항목

``{app_dir}`` 를 쓰면 프로그램이 놓인 폴더를 가리킨다. 어느 PC 에서든 반드시
있으므로 백업 폴더처럼 "없으면 만들면 되는" 경로의 마지막 후보로 두면 안전하다.
환경변수 ``QUALITY_ROOT`` 가 있으면 quality_root 후보보다 먼저 쓴다.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import app_dir

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_MAX_DEPTH = 10
ENV_ROOT = "QUALITY_ROOT"


def _pick(candidates: list[str]) -> str:
    """후보 중 이 PC 에서 쓸 것을 고른다 (규칙은 모듈 설명 참고)."""
    usable = [c for c in candidates if str(c).strip()]
    if not usable:
        return ""
    for c in usable:
        if Path(c).exists():
            return c
    for c in usable:                      # 아직 없지만 만들 수 있는 곳
        if Path(c).parent.exists():
            return c
    return usable[-1]


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


@dataclass
class PathChoice:
    """경로 하나를 어떻게 골랐는지. [경로 확인] 화면에 그대로 보여 준다."""

    key: str
    선택: str
    후보: list[str] = field(default_factory=list)
    출처: str = "config"          # 'config' | '환경변수' | '기본값'

    @property
    def 존재(self) -> bool:
        return bool(self.선택) and Path(self.선택).exists()

    def __str__(self) -> str:
        mark = "O" if self.존재 else "X"
        tail = ""
        if len(self.후보) > 1:
            못쓴 = [c for c in self.후보 if c != self.선택]
            tail = f"   (다른 후보: {', '.join(못쓴)})"
        if self.출처 != "config":
            tail += f"   [{self.출처}]"
        return f"  [{mark}] {self.key:<16} {self.선택}{tail}"


def _resolve_paths(raw: dict[str, Any]) -> tuple[dict[str, str], list[PathChoice]]:
    """paths 절의 목록형 값을 이 PC 에 맞는 값 하나로 정한다."""
    table: dict[str, str] = {"app_dir": str(app_dir())}
    choices: list[PathChoice] = []
    for key, value in (raw.get("paths") or {}).items():
        candidates = [str(v) for v in value] if isinstance(value, list) else [str(value)]
        출처 = "config"
        env = os.environ.get(ENV_ROOT) if key == "quality_root" else None
        if env:
            candidates = [env, *candidates]
            출처 = f"환경변수 {ENV_ROOT}"
        # 후보 안의 {app_dir} 등을 먼저 풀어야 존재 여부를 볼 수 있다
        expanded = [_expand(c, table) for c in candidates]
        chosen = _pick(expanded)
        table[key] = chosen
        if 출처.startswith("환경변수") and chosen != expanded[0]:
            출처 = "config"       # 환경변수를 줬지만 다른 후보가 선택된 경우
        choices.append(PathChoice(key=key, 선택=chosen, 후보=expanded, 출처=출처))
    return table, choices


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
    path_choices: list[PathChoice] = field(default_factory=list)
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


def load_config(path: str | Path | None = None) -> Config:
    """설정을 읽어 이 PC 에 맞는 경로로 해석한다.

    ``path`` 를 주지 않으면 프로그램이 놓인 폴더의 ``config.yaml`` 을 쓰고,
    없으면 구워 넣은 예시 파일에서 만들어 준다 (처음 쓰는 PC 대응).
    """
    if path is None:
        from .paths import ensure_config

        p, created = ensure_config()
        if created:
            log.warning("config.yaml 을 새로 만들었습니다: %s — 경로를 확인하세요", p)
    else:
        p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"설정 파일이 없습니다: {p}\n"
            "config.example.yaml 을 config.yaml 로 복사한 뒤 경로를 고치세요."
        )
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    table, choices = _resolve_paths(raw)
    raw = _expand_tree(raw, table)
    raw["paths"] = table
    return Config(raw=raw, source=p, path_choices=choices)


def check_paths(cfg: Config) -> tuple[list[str], list[str]]:
    """모든 경로가 이 PC 에서 실제로 존재하는지 확인한다.

    돌려주는 값은 ``(보고서 줄들, 문제 목록)``. 문제가 비어 있으면 바로 쓸 수 있다.
    다른 PC 에 옮겼을 때 가장 먼저 볼 화면이다.
    """
    from .paths import describe

    lines = [describe(), "", "■ 기준 폴더 (paths)"]
    problems: list[str] = []

    for c in cfg.path_choices:
        lines.append(str(c))
        if c.key == "quality_root" and not c.존재:
            problems.append(
                f"품질 폴더를 찾을 수 없습니다: {c.선택}\n"
                f"    후보: {', '.join(c.후보)}\n"
                f"    config.yaml 의 paths.quality_root 에 이 PC 의 경로를 추가하세요."
            )

    lines.append("")
    lines.append("■ 대상 파일 (files)")
    for key, value in (cfg.raw.get("files") or {}).items():
        exists = Path(value).exists()
        lines.append(f"  [{'O' if exists else 'X'}] {key:<16} {value}")
        if not exists:
            problems.append(f"파일이 없습니다: {key} -> {value}")

    return lines, problems
