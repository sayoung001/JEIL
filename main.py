"""품질 업무 자동화 — 진입점.

    품질자동화.exe            GUI
    품질자동화.exe --paths    이 PC 에서 어느 폴더를 보고 있는지 (경로 문제 1순위)
    품질자동화.exe --dump     읽기 전용 현황 덤프 (Excel 불필요)
    품질자동화.exe --check    시험 도래 판정만 (배지 내용)
    품질자동화.exe --verify   정합성 검사 (§21.3)

exe 는 **만든 PC 와 쓰는 PC 가 다르다.** 그래서 설정·로그·상태는 exe 안이 아니라
**exe 가 놓인 폴더**에 둔다. 자세한 것은 ``core/paths.py`` 참고.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

# 소스로 실행할 때 core/ 를 찾을 수 있게. exe 는 이미 묶여 있어 영향이 없다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import check_paths, load_config   # noqa: E402
from core.paths import app_dir, config_path, describe, writable  # noqa: E402
from core.state import State                       # noqa: E402


def setup_logging(level: int = logging.INFO) -> None:
    """로그는 exe 옆 ``logs\`` 에 쌓는다. 내장 폴더에 쓰면 실행이 끝나며 사라진다."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        handlers.insert(0, logging.FileHandler(
            writable("logs", f"{date.today():%Y%m%d}.log"), encoding="utf-8"))
    except OSError as e:                    # 읽기 전용 위치(네트워크 드라이브 등)
        print(f"경고: 로그 파일을 열지 못했습니다 ({e}). 화면에만 남깁니다.", file=sys.stderr)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def cmd_paths(cfg) -> int:
    """이 PC 에서 어느 폴더·파일을 보고 있는지. 다른 PC 로 옮겼을 때 제일 먼저 볼 것."""
    lines, problems = check_paths(cfg)
    print("\n".join(lines))
    print()
    if problems:
        print(f"■ 문제 {len(problems)}건")
        for p in problems:
            print(f"  - {p}")
        print(f"\n설정 파일을 고치세요: {cfg.source}")
        return 1
    print("■ 모든 경로를 찾았습니다. 바로 쓸 수 있습니다.")
    return 0


def cmd_dump(cfg) -> int:
    """S1 완료 기준 — 세 파일의 현재 상태를 출력한다 (§9, §12)."""
    from core.dump import dump_state

    dump_state(cfg)
    return 0


def cmd_check(cfg, state) -> int:
    from core.due_checker import DueChecker

    alerts = DueChecker(cfg, state).check()
    print(f"■ 겉모양·치수 (기준 {cfg.get('test_rules.phc_shape.threshold_bon')}본)")
    for v in alerts.all_vendors:
        print("   ", v)
    if alerts.milk:
        print("\n■", alerts.milk)
    if alerts.pending:
        print("\n■ 진행 중 시험")
        for p in alerts.pending:
            print("   ", p)
    if alerts.warnings:
        print("\n■ 경고")
        for w in alerts.warnings:
            print("   ", w)
    print(f"\n도래 {alerts.due_count}건")
    return 0


def cmd_verify(cfg, state) -> int:
    from core.consistency import ConsistencyChecker

    findings = ConsistencyChecker(cfg, state).check_all()
    for f in findings:
        print(f)
    errors = sum(1 for f in findings if f.수준 == "error")
    print(f"\n총 {len(findings)}건 (오류 {errors}건)")
    return 1 if errors else 0


def cmd_gui(cfg, state) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 가 필요합니다:  pip install PySide6", file=sys.stderr)
        return 2
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    win = MainWindow(cfg, state)
    win.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="품질 업무 자동화")
    parser.add_argument("--config", default=None,
                        help=f"설정 파일 (기본: {config_path()})")
    parser.add_argument("--paths", action="store_true", help="보고 있는 폴더·파일 확인")
    parser.add_argument("--dump", action="store_true", help="세 파일의 현재 상태 출력")
    parser.add_argument("--check", action="store_true", help="시험 도래 판정")
    parser.add_argument("--verify", action="store_true", help="정합성 검사")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        print(f"\n{describe()}", file=sys.stderr)
        return 2
    # 상태 파일도 exe 옆에. 내장 폴더에 두면 매번 초기화된다.
    state = State(app_dir() / "state.json")

    if args.paths:
        return cmd_paths(cfg)
    if args.dump:
        return cmd_dump(cfg)
    if args.check:
        return cmd_check(cfg, state)
    if args.verify:
        return cmd_verify(cfg, state)
    return cmd_gui(cfg, state)


if __name__ == "__main__":
    raise SystemExit(main())
