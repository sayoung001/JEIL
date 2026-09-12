"""T-01 자재검수 회차 생성 검증 (SPEC §4, §5).

실측 상태(차수 12, 체크용 54행, 수불부 9월 블록)에서 13차를 만들고
SPEC 이 명시한 셀·수식·인쇄영역이 그대로 나오는지 본다.
"""
from __future__ import annotations

from datetime import date

import pytest

from core.models import DeliveryRow, InspectionRound, MaterialRow
from core.sheets import col_index
from tasks.material_inspection import (CHECK_SHEET, COVER_SHEET, LEDGER_SHEET,
                                       MaterialInspectionTask, 갑지_블록순번)
from tests.fixtures import cfg, full_context


def 회차13() -> InspectionRound:
    return InspectionRound(
        차수=13,
        반입일자=date(2026, 9, 5),
        자재목록=[MaterialRow(규격="Ø500-15M", 전일수량=222, 반입수량=24,
                              비고="㈜한국파일/\n아주산업㈜")],
        송장목록=[
            DeliveryRow(송장일자=date(2026, 9, 5), 반입일자=date(2026, 9, 5),
                        업체명="한국파일", 규격_m=15, 구분="상", 수량_본=12),
            DeliveryRow(송장일자=date(2026, 9, 5), 반입일자=date(2026, 9, 5),
                        업체명="아주산업", 규격_m=15, 구분="하", 수량_본=12),
        ],
    )


@pytest.fixture()
def 실행():
    ctx, books = full_context()
    task = MaterialInspectionTask(cfg())
    data = 회차13()
    assert task.validate_before(data, ctx) == []
    task.execute(data, ctx)
    return books


# =====================================================================
# §4.1 ★수불부 체크용
# =====================================================================
def test_체크용_다음행부터_기입(실행):
    sh = 실행["supply_check"].sheet(CHECK_SHEET)
    assert sh.read(55, 1) == date(2026, 9, 5)
    assert sh.read(56, 1) == date(2026, 9, 5)
    assert sh.read(57, 1) is None            # 2건만 썼다


def test_체크용_반입일자는_수식으로_통일(실행):
    """§4.1 규칙 4 — B열은 '=+A{r}' 로 통일."""
    sh = 실행["supply_check"].sheet(CHECK_SHEET)
    assert sh.read(55, 2) == "=+A55"
    assert sh.read(56, 2) == "=+A56"


def test_체크용_J열_기존수식은_덮어쓰지_않는다(실행):
    """§4.1 규칙 3 — 55·56행에는 이미 수식이 깔려 있다."""
    sh = 실행["supply_check"].sheet(CHECK_SHEET)
    assert sh.read(55, 10) == "=E55*G55"
    assert sh.read(56, 10) == "=E56*G56"
    # 그 수식을 쓴 기록이 없어야 한다 (덮어쓰지 않았다는 뜻)
    assert not [r for r in sh.log if r.cell == "J55"]


def test_체크용_차수와_완은_회차_마지막행에만(실행):
    """§4.1 규칙 5,6 — 묶음 마지막 행에만 차수·완."""
    sh = 실행["supply_check"].sheet(CHECK_SHEET)
    assert sh.read(55, 11) is None and sh.read(55, 12) is None
    assert sh.read(56, 11) == 13
    assert sh.read(56, 12) == "완"


def test_체크용_업체명은_체크용_표기로(실행):
    sh = 실행["supply_check"].sheet(CHECK_SHEET)
    assert sh.read(55, 3) == "한국파일"       # '㈜한국파일'(갑지 표기)이 아니다
    assert sh.read(56, 3) == "아주산업"


# =====================================================================
# §4.2 갑지
# =====================================================================
def test_갑지_13차는_DG열_블록(실행):
    sh = 실행["request_cover"].sheet(COVER_SHEET)
    c0 = col_index("DG")                      # 111
    assert 갑지_블록순번(13) == 12
    assert sh.read(2, c0 + 2) == "Q-G-03(파일)-13"
    assert sh.read(15, c0 + 2) == "다인영종-자검(PHC)26-13"


def test_갑지_인쇄영역이_신규블록으로_이동(실행):
    """§10 #6 — 갑지는 최신 블록만 인쇄영역."""
    sh = 실행["request_cover"].sheet(COVER_SHEET)
    assert sh.print_area == (1, 111, 20, 120)   # DG1:DP20


def test_갑지_남는_자재행은_값을_비운다(실행):
    """§10 #4 — 자재가 1건이면 6~8행의 직전 회차 값이 남으면 안 된다."""
    sh = 실행["request_cover"].sheet(COVER_SHEET)
    c0 = col_index("DG")
    assert sh.read(5, c0 + 1) == "PHC파일"
    for row in (6, 7, 8):
        for off in (0, 1, 3, 4, 5, 6, 7, 8):
            assert sh.read(row, c0 + off) is None, f"{row}행 off{off} 가 남아 있다"


def test_갑지_누계는_수식(실행):
    sh = 실행["request_cover"].sheet(COVER_SHEET)
    c0 = col_index("DG")
    assert sh.read(5, c0 + 7) == "=+DL5+DM5"
    assert sh.read(9, c0 + 5) == "=SUM(DL5:DL8)"
    assert sh.read(9, c0 + 7) == "=SUM(DN5:DN8)"


def test_갑지_서명과_통보일_포맷(실행):
    sh = 실행["request_cover"].sheet(COVER_SHEET)
    c0 = col_index("DG")
    assert sh.read(12, c0 + 8) == "이 승 현   (인)"
    assert sh.read(13, c0 + 8) == "이 용 택   (인)"
    assert sh.read(18, c0 + 9) == "2026 년    9 월  5 일"
    assert sh.read(16, c0 + 2) == "■ 적합,     □ 부적합"


def test_갑지_열너비도_복사된다(실행):
    sh = 실행["request_cover"].sheet(COVER_SHEET)
    for i in range(10):
        assert sh.get_column_width(111 + i) == sh.get_column_width(101 + i)


# =====================================================================
# §4.3 자재수불부
# =====================================================================
def test_수불부_9월블록에_이어쓴다(실행):
    """9월 블록(Q, c0=17)에 이미 3건(5,7,9행)이 있으니 11행부터."""
    sh = 실행["ledger_phc"].sheet(LEDGER_SHEET)
    c0 = col_index("Q")                       # 17
    assert sh.read(11, c0 + 4) == date(2026, 9, 5)
    assert sh.read(13, c0 + 4) == date(2026, 9, 5)


def test_수불부_누계는_직전_데이터행을_참조(실행):
    """§10 #2 — 상수로 박지 않는다. 9행 다음은 11행이 9행을 참조."""
    sh = 실행["ledger_phc"].sheet(LEDGER_SHEET)
    c0 = col_index("Q")
    assert sh.read(11, c0 + 7) == "=+X9+W11"
    assert sh.read(13, c0 + 7) == "=+X11+W13"


def test_수불부_금회는_길이곱반입량(실행):
    sh = 실행["ledger_phc"].sheet(LEDGER_SHEET)
    c0 = col_index("Q")
    assert sh.read(11, c0 + 6) == "=T11*V11"
    assert sh.read(11, c0 + 10) == "=+U11"    # 출고일 = 반입일
    assert sh.read(11, c0 + 11) == "=W11"     # 출고량 = 금회


def test_수불부_비고는_수불부_표기(실행):
    sh = 실행["ledger_phc"].sheet(LEDGER_SHEET)
    c0 = col_index("Q")
    assert sh.read(11, c0 + 15) == "한국파일"
    assert sh.read(13, c0 + 15) == "아주산업"


def test_수불부_월이_바뀌면_새_블록과_전월_누계참조():
    """§10 #3 — 10월 반입이면 AG 블록을 만들고 첫 행은 9월 마지막 누계를 참조."""
    ctx, books = full_context()
    data = 회차13()
    data.반입일자 = date(2026, 10, 2)
    data.송장목록[0].반입일자 = data.반입일자
    data.송장목록[1].반입일자 = data.반입일자
    MaterialInspectionTask(cfg())._write_ledger(data, ctx)

    sh = books["ledger_phc"].sheet(LEDGER_SHEET)
    c0 = col_index("AG")                      # 33
    assert sh.read(1, c0) == "주요자재 검사 및 수불부 (26년 10월)"
    # 9월 마지막 데이터 행은 9행, 누계 열은 X
    assert sh.read(5, c0 + 7) == "=+X9+AM5"
    assert sh.read(7, c0 + 7) == "=+AN5+AM7"


# =====================================================================
# §5.2 사전 검증
# =====================================================================
def test_검증_모르는_업체명은_막는다():
    ctx, _ = full_context()
    data = 회차13()
    data.송장목록[0].업체명 = "없는회사파일"
    problems = MaterialInspectionTask(cfg()).validate_before(data, ctx)
    assert any("vendor_alias" in p for p in problems)


def test_검증_송장합계_불일치를_막는다():
    ctx, _ = full_context()
    data = 회차13()
    data.자재목록[0].반입수량 = 30            # 송장은 24본
    problems = MaterialInspectionTask(cfg()).validate_before(data, ctx)
    assert any("송장 합계" in p for p in problems)


def test_검증_자재가_5건이면_막는다():
    ctx, _ = full_context()
    data = 회차13()
    data.자재목록 = [MaterialRow(반입수량=6) for _ in range(5)]
    problems = MaterialInspectionTask(cfg()).validate_before(data, ctx)
    assert any("1~4건" in p for p in problems)


def test_검증_차수중복을_막는다():
    ctx, _ = full_context()
    data = 회차13()
    data.차수 = 12
    problems = MaterialInspectionTask(cfg()).validate_before(data, ctx)
    assert any("이미 있습니다" in p for p in problems)


def test_검증_반입일자_역행을_막는다():
    ctx, _ = full_context()
    data = 회차13()
    data.반입일자 = date(2026, 8, 1)
    problems = MaterialInspectionTask(cfg()).validate_before(data, ctx)
    assert any("빠릅니다" in p for p in problems)


def test_사진대지_양식이_없으면_단계가_빠진다():
    """§5.1 9번은 선택 단계다. 양식 파일이 없어도 T-01 은 진행돼야 한다."""
    task = MaterialInspectionTask(cfg())      # config 경로는 이 PC 에 없다
    assert task.사진대지 is False
    assert task.target_files == ("supply_check", "request_cover", "ledger_phc")


def test_사진대지_양식이_있으면_백업대상에_들어간다(tmp_path):
    import openpyxl

    from core.config import Config

    tpl = tmp_path / "자재반입 송장 사진대지_양식.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "양식"
    wb.save(tpl)

    c = cfg()
    raw = dict(c.raw)
    raw["files"] = dict(raw["files"])
    raw["files"]["photo_template"] = str(tpl)
    task = MaterialInspectionTask(Config(raw=raw))
    assert task.사진대지 is True
    assert "photo_template" in task.target_files


def test_사진대지_시트가_반입일_이름으로_생긴다(tmp_path):
    from core.config import Config
    from core.sheets import MemoryWorkbook
    from tests.fixtures import FakeContext

    양식 = MemoryWorkbook(path="사진대지_양식.xlsx")
    sh = 양식.add_sheet("사용법")
    sh.write(1, 1, "안내")
    tpl = 양식.add_sheet("양식")
    tpl.write(1, 1, "자 재 반 입 송 장")
    tpl.write(2, 6, "반입일")
    for s in 양식.sheets.values():
        s.log.clear()

    ctx, books = full_context()
    books["photo_template"] = 양식
    ctx2 = FakeContext(cfg(), books)
    data = 회차13()
    task = MaterialInspectionTask(cfg())
    task.사진대지 = True
    task.execute(data, ctx2)

    assert "0905" in 양식.sheet_names
    assert 양식.sheet("0905").read(2, 7) == date(2026, 9, 5)   # G2 = 반입일
    assert 양식.sheet("양식").log == []                        # 템플릿은 그대로
