"""노트북이 실제로 돌아가는가.

노트북은 조용히 썩는다. 코드를 고쳤는데 노트북은 그대로면 열었을 때 에러가 난다.
그래서 **모든 코드 셀을 순서대로 실제 실행**해 본다.

파일을 고치는 셀은 노트북에서 `실행하기 = False` 처럼 잠가 뒀으므로
이 테스트가 원본을 건드리지 않는다.
"""
from __future__ import annotations

import pathlib
from datetime import date

import openpyxl
import pytest
import yaml

nbformat = pytest.importorskip("nbformat")
pytest.importorskip("IPython")

from core.ledger import COL, FIRST_DATA_ROW

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOTEBOOKS = sorted((ROOT / "notebooks").glob("*.ipynb"))


def _대장(path: pathlib.Path, 시트들: dict) -> None:
    wb = openpyxl.Workbook()
    for 이름, 건수 in 시트들.items():
        ws = wb.create_sheet(이름)
        ws.cell(3, COL["일련번호"], "일련\n번호")
        ws.cell(3, COL["날짜"], "날 짜")
        row = FIRST_DATA_ROW
        for i in range(건수):
            ws.cell(row, COL["일련번호"], i + 1)
            ws.cell(row, COL["날짜"], date(2026, 8, 5 + i))
            ws.cell(row, COL["구분"], f"Q-Q-\n02-{i + 1:02d}")
            ws.cell(row, COL["대상재료"], "PHC 파일 \n겉모양, 치수")
            ws.cell(row, COL["판정"], "합 격")
            row += 5
    del wb["Sheet"]
    wb.save(path)


@pytest.fixture(scope="module")
def 작업폴더(tmp_path_factory):
    """노트북이 돌 수 있는 최소 환경. 실제 품질 폴더는 건드리지 않는다."""
    tmp = tmp_path_factory.mktemp("notebook")
    품질 = tmp / "품질_전체"
    품질.mkdir()
    _대장(품질 / "Q-0102.xlsx", {"26.07": 2, "26.08": 4})
    for 이름 in ("Q-03", "N-02"):
        _대장(품질 / f"{이름}.xlsx", {"26.08": 0})
    _대장(품질 / "O-0104.xlsx", {"재하시험": 0, "MT검사": 0})

    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    raw["paths"] = {"quality_root": str(품질), "intake_root": str(tmp / "서류투입"),
                    "backup_root": str(tmp / "백업"),
                    "photo_sort_root": str(tmp / "서류투입"),
                    "photo_backup_root": str(tmp / "사진백업"),
                    "state_dir": str(tmp / "상태"), "photo_inbox": str(tmp / "임시")}
    raw["files"] = {"ledger_pile": str(품질 / "Q-0102.xlsx"),
                    "ledger_civil": str(품질 / "Q-03.xlsx"),
                    "ledger_outsrc": str(품질 / "N-02.xlsx"),
                    "ledger_load_mt": str(품질 / "O-0104.xlsx"),
                    "report_monthly": str(품질 / "실적총괄.xlsx")}
    (tmp / "config.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True),
                                     encoding="utf-8")
    return tmp


def test_노트북이_있다():
    assert NOTEBOOKS, "notebooks/ 에 ipynb 가 없습니다"
    이름들 = [p.name for p in NOTEBOOKS]
    assert any("시작하기" in n for n in 이름들)
    assert any("월간실적보고서" in n for n in 이름들)


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_노트북_형식(path):
    nb = nbformat.read(path, as_version=4)
    nbformat.validate(nb)
    assert nb.cells, path.name
    코드 = [c for c in nb.cells if c.cell_type == "code"]
    assert 코드, f"{path.name}: 코드 셀이 없습니다"
    # 첫 코드 셀은 프로젝트를 찾는 준비 셀이어야 한다
    assert "sys.path.insert" in 코드[0].source, f"{path.name}: 준비 셀이 없습니다"
    # 출력은 비워서 올린다 (저장소가 무거워지지 않게)
    assert all(not c.get("outputs") for c in 코드), f"{path.name}: 출력이 남아 있습니다"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_노트북이_실제로_돌아간다(path, 작업폴더, monkeypatch):
    """모든 코드 셀을 순서대로 실행한다. 에러가 나면 실패."""
    monkeypatch.chdir(작업폴더)

    nb = nbformat.read(path, as_version=4)
    ns: dict = {"__name__": "__main__"}
    # 노트북은 IPython 의 display 를 쓴다. 터미널에서도 돌게 최소한으로 채운다.
    for i, cell in enumerate(c for c in nb.cells if c.cell_type == "code"):
        # 준비 셀의 ROOT 탐색은 cwd 부터 올라간다 -> 여기서는 프로젝트를 직접 준다
        source = cell.source.replace(
            'ROOT = pathlib.Path.cwd()\nwhile not (ROOT / "main.py").exists() '
            'and ROOT != ROOT.parent:\n    ROOT = ROOT.parent                      '
            '# notebooks/ 에서 열었을 때',
            f'ROOT = pathlib.Path(r"{ROOT}")')
        try:
            exec(compile(source, f"{path.name}[{i}]", "exec"), ns)
        except Exception as e:                       # pragma: no cover - 실패 보고
            pytest.fail(f"{path.name} 코드셀 {i} 에서 실패: {type(e).__name__}: {e}\n"
                        f"--- 셀 내용 ---\n{cell.source[:500]}")


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_파일을_고치는_셀은_잠겨있다(path):
    """실수로 실행해도 원본이 바뀌지 않게 기본값이 False 여야 한다."""
    nb = nbformat.read(path, as_version=4)
    for c in nb.cells:
        if c.cell_type != "code":
            continue
        for 잠금 in ("쓰기", "넣기", "실행하기"):
            if f"{잠금} = " in c.source:
                assert f"{잠금} = False" in c.source, f"{path.name}: {잠금} 기본값"
