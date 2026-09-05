"""품질 업무 자동화 — 진입점.

    python main.py            GUI
    python main.py --dump     읽기 전용 현황 덤프 (S1 완료 확인용, Excel 불필요)
    python main.py --check    시험 도래 판정만 (배지 내용)
    python main.py --verify   정합성 검사 (§21.3)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.config import load_config              # noqa: E402
from core.state import State                     # noqa: E402


def setup_logging(level: int = logging.INFO) -> None:
    folder = ROOT / "logs"
    folder.mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(folder / f"{date.today():%Y%m%d}.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


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
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
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
        return 2
    state = State(ROOT / "state.json")

    if args.dump:
        return cmd_dump(cfg)
    if args.check:
        return cmd_check(cfg, state)
    if args.verify:
        return cmd_verify(cfg, state)
    return cmd_gui(cfg, state)


if __name__ == "__main__":
    raise SystemExit(main())
