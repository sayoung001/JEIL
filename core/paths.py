"""실행 위치 판별 — 소스 실행과 PyInstaller exe 를 함께 지원한다.

**exe 는 만드는 PC 와 쓰는 PC 가 다르다.** 노트북에서 빌드해 회사 PC 에서 돌리므로
품질 폴더 경로를 빌드 시점에 굳혀서는 안 된다. 그래서 위치를 두 가지로 나눈다.

``bundle_dir()`` — exe 안에 **구워 넣은** 읽기 전용 자원 (workflows, templates).
    PyInstaller ``--onefile`` 은 실행할 때마다 임시 폴더에 풀어 놓고
    ``sys._MEIPASS`` 로 알려 준다. 프로그램이 끝나면 사라진다.

``app_dir()`` — exe 가 **놓여 있는** 폴더. 사람이 열어서 고칠 수 있는 곳.
    ``config.yaml`` · ``state.json`` · ``logs/`` 가 여기 있어야 한다.
    여기에 쓰지 않고 ``bundle_dir()`` 에 쓰면 **다음 실행 때 전부 사라진다.**

소스로 실행할 때는 둘 다 프로젝트 폴더라 차이가 없다.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

CONFIG_NAME = "config.yaml"
EXAMPLE_NAME = "config.example.yaml"


def is_frozen() -> bool:
    """PyInstaller 로 묶인 exe 로 실행 중인가."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_dir() -> Path:
    """구워 넣은 자원이 풀린 곳. **여기에 쓰면 안 된다** (실행이 끝나면 사라진다)."""
    if is_frozen():
        return Path(sys._MEIPASS)          # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """exe(또는 main.py)가 놓인 폴더. 설정·로그·상태는 전부 여기."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource(*parts: str) -> Path:
    """구워 넣은 자원 경로. exe 옆에 같은 이름이 있으면 **그쪽을 먼저** 쓴다.

    덕분에 exe 를 다시 만들지 않고도 `templates\\현장시험\\새시험.yaml` 을
    옆에 놔두는 것만으로 항목을 추가할 수 있다.
    """
    beside = app_dir().joinpath(*parts)
    if beside.exists():
        return beside
    return bundle_dir().joinpath(*parts)


def writable(*parts: str) -> Path:
    """쓰기용 경로 (exe 옆). 상위 폴더를 만들어 둔다."""
    p = app_dir().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return app_dir() / CONFIG_NAME


def ensure_config() -> tuple[Path, bool]:
    """exe 옆에 ``config.yaml`` 이 없으면 예시 파일에서 만들어 준다.

    돌려주는 값은 ``(경로, 방금_만들었는가)``. 처음 쓰는 PC 에서
    "설정 파일이 없습니다" 로 막히지 않고, 경로만 고치면 되게 한다.
    """
    target = config_path()
    if target.exists():
        return target, False
    example = resource(EXAMPLE_NAME)
    if not example.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(example, target)
    return target, True


def attach_console() -> bool:
    r"""windowed exe 를 부모 콘솔(cmd 창)에 붙인다.

    ``--windowed`` 로 만든 exe 는 콘솔이 없는 프로그램이라, cmd 에서 실행해도
    ``print`` 출력이 **아무 데도 안 나온다.** 그대로 두면 처음설정.bat 이
    빈 화면만 보여 주고, 회사 PC 에서 무엇이 잘못됐는지 알 길이 없어진다.

    Windows 의 ``AttachConsole(-1)`` 로 부모 콘솔에 붙은 뒤 표준 출력을
    다시 연다. 붙을 콘솔이 없으면(탐색기에서 더블클릭) 조용히 False 를 준다.
    """
    if not (is_frozen() and sys.platform.startswith("win")):
        return False
    try:
        import ctypes

        ATTACH_PARENT_PROCESS = -1
        if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return False
        for 이름 in ("stdout", "stderr"):
            try:
                setattr(sys, 이름, open("CONOUT$", "w", encoding="utf-8",
                                        buffering=1))
            except OSError:
                pass
        return True
    except Exception:                       # pragma: no cover - 환경 의존
        return False


def as_path(value: str | Path) -> Path:
    r"""설정에 적힌 경로 문자열을 이 OS 의 Path 로.

    설정은 Windows 기준이라 ``C:\품질_전체\G. 자재`` 처럼 역슬래시를 쓴다.
    Windows 에서는 그대로 쓰면 되지만, 그 밖(테스트·점검용 리눅스)에서는
    역슬래시가 구분자로 취급되지 않아 **전체가 파일명 하나**가 돼 버린다.
    실제 동작은 Windows 에서만 하지만, 검증을 다른 OS 에서도 하려면 여기서 맞춰 준다.
    """
    if isinstance(value, Path):
        return value
    text = str(value)
    if os.sep != "\\":
        text = text.replace("\\", os.sep)
    return Path(text)


def describe() -> str:
    """어디를 보고 있는지 한눈에. 다른 PC 에서 문제가 생겼을 때 첫 번째로 볼 것."""
    lines = [
        f"실행 방식   : {'exe (PyInstaller)' if is_frozen() else '파이썬 소스'}",
        f"프로그램 폴더: {app_dir()}        <- config.yaml · logs · state.json",
    ]
    if is_frozen():
        lines.append(f"내장 자원   : {bundle_dir()}   (임시. 여기 파일을 고쳐도 남지 않는다)")
    lines.append(f"설정 파일   : {config_path()}  {'있음' if config_path().exists() else '없음'}")
    return "\n".join(lines)
