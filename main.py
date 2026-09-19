"""품질 업무 자동화 — 진입점.

    품질자동화.exe            GUI
    품질자동화.exe --selftest 이 PC 에서 돌 수 있는지 스스로 점검 (새 PC 첫 실행)
    품질자동화.exe --setup    서류투입 폴더를 만들어 준다
    품질자동화.exe --paths    이 PC 에서 어느 폴더를 보고 있는지 (경로 문제 1순위)
    품질자동화.exe --intake   서류투입 폴더를 훑어 무엇이 어디로 갈지 보여 준다
    품질자동화.exe --intake --run   실제로 분류한다
    품질자동화.exe --monthly 26.08   월간 실적보고서 집계 (Excel 불필요, 읽기 전용)
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
from core.paths import (app_dir, attach_console, config_path, describe,
                        is_frozen, writable)       # noqa: E402
from core.state import State                       # noqa: E402

#: CLI 결과를 파일로도 남긴다. windowed exe 라 콘솔이 없을 때의 보험이자,
#: "이 내용을 그대로 알려 주세요" 라고 할 수 있는 근거가 된다.
진단파일 = "진단결과.txt"


class _양쪽(object):
    """화면과 파일에 동시에 쓴다."""

    def __init__(self, *대상):
        self._대상 = [t for t in 대상 if t is not None]

    def write(self, text):
        for t in self._대상:
            try:
                t.write(text)
            except Exception:
                pass
        return len(text)

    def flush(self):
        for t in self._대상:
            try:
                t.flush()
            except Exception:
                pass


def _기록시작():
    """CLI 모드에서 출력을 진단결과.txt 에도 남긴다. 되돌리는 함수를 돌려준다."""
    try:
        f = open(writable(진단파일), "w", encoding="utf-8")
    except OSError:
        return lambda: None
    원래 = sys.stdout
    sys.stdout = _양쪽(원래, f)

    def 끝():
        sys.stdout = 원래
        try:
            f.close()
        except Exception:
            pass
    return 끝


def _치명오류(제목: str, 본문: str) -> None:
    """창이 뜨기 전에 죽으면 사용자는 아무것도 못 본다. 대화상자로 알린다."""
    print(f"{제목}\n{본문}", file=sys.stderr)
    if not is_frozen():
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, 제목, 본문)
        del app
    except Exception:
        try:                                  # Qt 자체가 안 뜨는 경우
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, 본문, 제목, 0x10)
        except Exception:
            pass


log = logging.getLogger("품질자동화")


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
    from core.ocr import describe as ocr_describe

    lines, problems = check_paths(cfg)
    print("\n".join(lines))
    print()
    print(ocr_describe())
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


def cmd_monthly(cfg, 월: str) -> int:
    """실시대장을 세어 월간 실적을 보여 준다. 파일을 수정하지 않는다."""
    from core.monthly_report import MonthlyReporter

    reporter = MonthlyReporter(cfg)
    있는달 = reporter.있는_달()
    if 월 not in 있는달:
        print(f"대장에 {월} 기록이 없습니다.")
        print(f"  있는 달: {', '.join(있는달) if 있는달 else '없음'}")
        if not 있는달:
            return 1

    전월, 금월 = reporter.누계(월)
    누계 = 전월.더하기(금월)

    print(f"■ {월} 금월 실적")
    print(금월)
    print(f"\n■ 누계 (전월까지 {전월.총건수}건 + 금월 {금월.총건수}건)")
    print(누계)

    경고 = [*dict.fromkeys([*전월.경고, *금월.경고])]
    if 경고:
        print("\n■ 확인 필요")
        for w in 경고:
            print(f"  - {w}")

    print("\n출처 (대장!시트!행)")
    for 이름, 값 in sorted(금월.종목.items()):
        print(f"  {이름}: {', '.join(값.출처[:6])}" + (" …" if len(값.출처) > 6 else ""))
    return 0


def cmd_selftest(cfg) -> int:
    """회사 PC 처럼 아무것도 없는 곳에서 무엇이 빠졌는지 스스로 말한다."""
    from core.selftest import report

    text, 치명 = report(cfg)
    print(text)
    return 1 if 치명 else 0


def cmd_setup(cfg) -> int:
    """서류투입 폴더와 카테고리 칸을 만들어 준다."""
    from core.selftest import make_intake_dirs

    made = make_intake_dirs(cfg)
    root = cfg.path("intake_root")
    if made:
        print(f"서류투입 폴더를 만들었습니다: {root}")
        for p in made:
            print(f"  + {p.name}")
    else:
        print(f"이미 준비돼 있습니다: {root}")
    print("\n원본을 위 폴더에 넣고 [미리보기] 또는 --intake 를 실행하세요.")
    return 0


def cmd_intake(cfg, *, run: bool) -> int:
    """서류투입 폴더를 훑는다. --run 을 주지 않으면 계획만 보여 준다."""
    from tasks.document_intake import DocumentIntake, Lane

    intake = DocumentIntake(cfg)
    if not intake.root.exists():
        print(f"투입 폴더가 없습니다: {intake.root}")
        print("이 폴더를 만들고 안에 카테고리 폴더를 두세요:")
        for c in intake.categories:
            print(f"  {intake.root / c.name}   ({c.lane.value})")
        return 1

    items, blocked = intake.scan()
    if not items and not blocked:
        print(f"투입 폴더가 비어 있습니다: {intake.root}")
        return 0

    for lane in Lane:
        골라낸 = [i for i in items if i.lane is lane]
        if not 골라낸:
            continue
        print(f"\n■ {lane.value}  {len(골라낸)}건")
        for i in 골라낸:
            줄 = f"  {i.category:<12} {i.src.name:<34} -> {i.dest}"
            if i.요약:
                줄 += f"\n      {i.요약}"
            print(줄)
            for w in (i.parsed.경고 if i.parsed else []):
                print(f"      ! {w}")
    if blocked:
        print(f"\n■ 보류 {len(blocked)}건")
        for b in blocked:
            print(f"  - {b}")

    if not run:
        print("\n실제로 옮기려면 --run 을 붙이세요.")
        return 0
    result = intake.run(items, blocked)
    print(f"\n{result.요약}")
    for src, err in result.failed:
        print(f"  [실패] {src.name}: {err}")
    return 1 if result.failed else 0


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
    parser.add_argument("--monthly", metavar="YY.MM",
                        help="월간 실적보고서 집계 (예: 26.08)")
    parser.add_argument("--selftest", action="store_true", help="이 PC 에서 돌 수 있는지 점검")
    parser.add_argument("--setup", action="store_true", help="서류투입 폴더 만들기")
    parser.add_argument("--intake", action="store_true", help="서류투입 폴더 훑기")
    parser.add_argument("--run", action="store_true", help="--intake 와 함께: 실제로 분류")
    parser.add_argument("--dump", action="store_true", help="세 파일의 현재 상태 출력")
    parser.add_argument("--check", action="store_true", help="시험 도래 판정")
    parser.add_argument("--verify", action="store_true", help="정합성 검사")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    # GUI 가 아닌 모드는 콘솔에 붙어야 출력이 보인다 (windowed exe 대응)
    CLI = any((args.selftest, args.setup, args.paths, args.intake,
               args.monthly, args.dump, args.check, args.verify))
    if CLI:
        attach_console()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    기록끝 = _기록시작() if CLI else (lambda: None)
    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        if args.selftest:          # 설정이 없어도 점검은 돼야 한다
            from core.selftest import report

            text, 치명 = report(None)
            print(text)
            print(f"\n설정 파일이 없습니다: {e}")
            기록끝()
            return 1
        기록끝()
        _치명오류("설정 파일을 읽지 못했습니다", f"{e}\n\n{describe()}")
        return 2
    except Exception as e:                    # 설정 형식이 깨진 경우
        기록끝()
        _치명오류("설정 파일이 잘못됐습니다",
                  f"{config_path()}\n\n{type(e).__name__}: {e}\n\n"
                  "메모장으로 열어 형식을 확인하거나, 파일을 지우고 다시 실행하면 "
                  "예시에서 새로 만들어 줍니다.")
        return 2
    # 상태 파일도 exe 옆에. 내장 폴더에 두면 매번 초기화된다.
    state = State(app_dir() / "state.json")

    try:
        if args.monthly:
            return cmd_monthly(cfg, args.monthly)
        if args.selftest:
            return cmd_selftest(cfg)
        if args.setup:
            return cmd_setup(cfg)
        if args.paths:
            return cmd_paths(cfg)
        if args.intake:
            return cmd_intake(cfg, run=args.run)
        if args.dump:
            return cmd_dump(cfg)
        if args.check:
            return cmd_check(cfg, state)
        if args.verify:
            return cmd_verify(cfg, state)
    finally:
        if CLI:
            print(f"\n(이 내용은 {writable(진단파일)} 에도 저장됐습니다)")
            기록끝()

    try:
        return cmd_gui(cfg, state)
    except Exception as e:                    # 창이 뜨기 전에 죽는 경우
        log.exception("프로그램을 시작하지 못했습니다")
        _치명오류("프로그램을 시작하지 못했습니다",
                  f"{type(e).__name__}: {e}\n\n"
                  "자가점검.bat 을 실행해 무엇이 빠졌는지 확인하세요.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
