"""PART 2 시험 파이프라인 검증 (SPEC §14~§18)."""
from __future__ import annotations

from datetime import date

import pytest

from core.ledger import COL, FIRST_DATA_ROW
from core.models import (CompressiveTest, CompStage, MilkSpecimen, MilkTest, Series,
                         ShapeSample, ShapeTest)
from core.sheets import col_index
from tasks.bscw_jsp import CompressiveTask
from tasks.phc_milk import PhcMilkTask
from tasks.phc_shape import PhcShapeTask
from tests.fixtures import cfg, 시험_context


# =====================================================================
# T-03 겉모양·치수 (§16)
# =====================================================================
def 겉모양시험() -> ShapeTest:
    return ShapeTest(
        번호=7, 시료채취일=date(2026, 9, 5), 업체명="동진파일",
        규격_A=500, 규격_m=15, 시료반입일=date(2026, 9, 4), 시료반입량_본=24,
        시료목록=[ShapeSample(1, 길이=15017, 바깥지름=503, 두께=84)],
    )


@pytest.fixture()
def 겉모양실행():
    ctx, books = 시험_context()
    task = PhcShapeTask(cfg())
    data = 겉모양시험()
    assert task.validate_before(data, ctx) == []
    task.execute(data, ctx)
    return books


def test_겉모양_다음번호_제안():
    ctx, _ = 시험_context()
    assert PhcShapeTask(cfg()).next_number(ctx) == 7


def test_겉모양_일지_새블록은_BU열(겉모양실행):
    sh = 겉모양실행["test_shape"].sheet("일지")
    c0 = col_index("BU")                        # 73 = 7번 블록
    assert sh.read(3, c0 + 3) == "Q-Q-02-07"
    assert sh.read(4, c0 + 3) == "PHC파일-A500-15M"
    assert sh.read(4, c0 + 9) == "동진파일㈜"    # 시험601 표기 계열
    assert sh.read(6, c0 + 9) == "24 본"
    assert sh.print_area == (1, 73, 23, 84)     # BU1:CF23


def test_겉모양_시험일자는_채취일_참조수식(겉모양실행):
    """§14.1 — 4.시험일자 = '='+채취일셀."""
    sh = 겉모양실행["test_shape"].sheet("일지")
    c0 = col_index("BU")
    assert sh.read(6, c0 + 3) == "=+BX5"


def test_겉모양_판정과_허용차(겉모양실행):
    sh = 겉모양실행["test_shape"].sheet("일지")
    c0 = col_index("BU")
    assert sh.read(9, c0 + 2) == "±0.3%"
    assert sh.read(9, c0 + 4) == "+5, -2"
    assert sh.read(9, c0 + 6) == "80이상"
    assert sh.read(9, c0 + 11) == "합 격"


def test_겉모양_601대장에_1행_추가(겉모양실행):
    sh = 겉모양실행["test_shape"].sheet("대장")
    assert sh.read(11, 1) == 7                  # 기존 6건 다음
    assert sh.read(11, 2) == date(2026, 9, 5)
    assert sh.read(11, 3) == "동진파일㈜"
    assert sh.read(11, 4) == "500-15"
    assert sh.read(11, 5) == "합  격"           # 공백 2칸
    assert sh.read(11, 6) == "ㅇ"


def test_겉모양_실시대장_h5_행그룹(겉모양실행):
    """§14.4 — 겉모양은 5행 그룹. 26.09 시트에 첫 건."""
    sh = 겉모양실행["ledger_pile"].sheet("26.09")
    r = FIRST_DATA_ROW
    assert sh.read(r, COL["일련번호"]) == 1     # 월별 리셋
    assert sh.read(r, COL["날짜"]) == date(2026, 9, 5)
    assert sh.read(r, COL["구분"]) == "Q-Q-\n02-07"
    assert sh.read(r, COL["대상재료"]) == "PHC 파일 \n겉모양, 치수"
    assert sh.read(r, COL["공장"]) == "동진파일"     # 대장 표기 계열
    assert sh.read(r, COL["종목"]) == "치 수"
    assert sh.read(r + 3, COL["종목"]) == "모양"
    assert sh.read(r + 4, COL["종목"]) == "겉모양"
    assert sh.read(r, COL["세부"]) == "길이"
    assert sh.read(r + 1, COL["세부"]) == "바깥\n지름"
    assert sh.read(r, COL["기준"]) == "±0.3%\n(±45)"    # 15m -> ±45
    assert sh.read(r, COL["결과"]) == 15017
    assert sh.read(r, COL["판정"]) == "합 격"


def test_겉모양_실시대장_병합패턴(겉모양실행):
    sh = 겉모양실행["ledger_pile"].sheet("26.09")
    r = FIRST_DATA_ROW
    assert (r, 1, r + 4, 1) in sh.merges            # A열 5행 세로 병합
    assert (r, 8, r + 2, 8) in sh.merges            # H{r}:H{r+2} = 치 수
    assert (r + 3, 8, r + 3, 9) in sh.merges        # H{r+3}:I{r+3} = 모양
    assert (r, 18, r + 4, 18) in sh.merges          # R열


def test_겉모양_규격불량이면_불합격():
    ctx, books = 시험_context()
    data = 겉모양시험()
    data.시료목록 = [ShapeSample(1, 길이=15017, 바깥지름=503, 두께=78)]  # 두께 80 미만
    PhcShapeTask(cfg()).execute(data, ctx)
    sh = books["test_shape"].sheet("일지")
    assert sh.read(9, col_index("BU") + 11) == "불합격"
    assert books["ledger_pile"].sheet("26.09").read(FIRST_DATA_ROW, COL["판정"]) == "불합격"


# =====================================================================
# T-04 밀크 (§17)
# =====================================================================
def 밀크시험() -> MilkTest:
    return MilkTest(
        번호=4, 시료채취일=date(2026, 9, 4), 시험일자=date(2026, 9, 4),
        S1=MilkSpecimen(총중량=500.0, 건조중량=380.0, 용기무게=100.0),
        S2=MilkSpecimen(총중량=490.0, 건조중량=380.0, 용기무게=100.0),
    )


@pytest.fixture()
def 밀크실행():
    ctx, books = 시험_context()
    task = PhcMilkTask(cfg())
    data = 밀크시험()
    assert task.validate_before(data, ctx) == []
    task.execute(data, ctx)
    return books


def test_밀크_물시멘트비_계산():
    m = 밀크시험()
    assert m.S1.시멘트질량 == 280.0
    assert m.S1.물질량 == 120.0
    assert round(m.S1.물시멘트비, 1) == 42.9
    assert m.합격 is True


def test_밀크_다음시트번호():
    ctx, _ = 시험_context()
    assert PhcMilkTask(cfg()).next_number(ctx) == 4      # 01,02,03 -> 04


def test_밀크_04시트와_짝사진대지_생성(밀크실행):
    names = 밀크실행["test_milk"].sheet_names
    assert "04" in names
    assert "사진대지 (4)" in names               # 사진대지, (2), (3) 다음


def test_밀크_셀맵대로_기입(밀크실행):
    sh = 밀크실행["test_milk"].sheet("04")
    assert sh.read(3, col_index("F")) == " Q-Q-01-04"    # 앞 공백 1칸
    assert sh.read(3, col_index("U")) == " 2026-09-04"
    assert sh.read(8, col_index("I")) == 500.0
    assert sh.read(10, col_index("P")) == 100.0
    assert sh.read(11, col_index("I")) == "=I9-I10"
    assert sh.read(13, col_index("P")) == "=P12/P11*100"
    assert sh.read(8, col_index("AA")) == "합 격"


def test_밀크_템플릿시트는_수정되지_않는다(밀크실행):
    """§10 #11 — `양식` 시트는 복사만 한다."""
    양식 = 밀크실행["test_milk"].sheet("양식")
    assert 양식.log == []
    assert 양식.read(3, col_index("F")) is None


def test_밀크_612대장(밀크실행):
    sh = 밀크실행["test_milk"].sheet("대장")
    assert sh.read(8, 1) == 4
    assert sh.read(8, 3) == 42.9                 # S-1, 소수 1자리
    assert sh.read(8, 5) == "합  격"


def test_밀크_실시대장_h2_L만_행별(밀크실행):
    """§14.4 — H{r}:I{r+1} 은 2행 전체 병합, L 만 S-1/S-2 로 나뉜다."""
    sh = 밀크실행["ledger_pile"].sheet("26.09")
    r = FIRST_DATA_ROW
    assert sh.read(r, COL["종목"]) == "물 · 시멘트비"
    assert sh.read(r, COL["결과"]) == 42.9
    assert sh.read(r + 1, COL["결과"]) == 39.3     # S-2: 110/280*100
    assert (r, 8, r + 1, 9) in sh.merges         # H{r}:I{r+1}
    assert (r, 10, r + 1, 10) in sh.merges       # J 2행 병합
    assert sh.read(r, COL["기준"]) == "83 이하"


def test_밀크_시멘트질량0이면_막는다():
    ctx, _ = 시험_context()
    data = 밀크시험()
    data.S1.건조중량 = 100.0                     # = 용기무게
    problems = PhcMilkTask(cfg()).validate_before(data, ctx)
    assert any("시멘트 질량이 0" in p for p in problems)


# =====================================================================
# T-05 BSCW / JSP (§18)
# =====================================================================
def test_압축강도_3단계_시나리오():
    ctx, books = 시험_context()
    task = CompressiveTask(cfg(), Series.BSCW)
    t = CompressiveTest(series=Series.BSCW, 번호=9, 채취일=date(2026, 9, 1),
                        목록행번호=9, stage=CompStage.NEW)

    # [NEW] 채취 등록 -> 새 블록 CK (9번)
    task.execute(t, ctx)
    sh = books["test_bscw_jsp"].sheet("BSCW_압축강도_시험일지")
    c0 = col_index("CK")                          # 89
    assert sh.read(5, c0 + 2) == "Q-Q-03-09"
    assert sh.read(4, c0 + 8) == date(2026, 9, 1)
    assert sh.read(9, c0 + 9) == "=CS4+7"         # 7일 = 채취일 + 7
    assert sh.read(16, c0 + 9) == "=CT9+21"       # 28일 = 7일 + 21
    assert sh.read(11, c0 + 9) == "-"             # 7일은 판정 없음
    assert sh.print_area == (1, 89, 26, 99)
    목록 = books["test_bscw_jsp"].sheet("시험목록")
    assert 목록.read(12, 2) == date(2026, 9, 1)   # 9번 = 4+9-1 = 12행

    # [7D]
    t.stage, t.측정_7일 = CompStage.AWAIT_7D, [1.02, 1.00, 1.04]
    task.execute(t, ctx)
    assert sh.read(11, c0 + 3) == 1.02
    assert sh.read(13, c0 + 3) == 1.04
    assert 목록.read(12, 3) == 1.02               # 평균, 소수 2자리 (§18.3)

    # [28D] — 여기서 대장에 기록된다
    t.stage, t.측정_28일 = CompStage.AWAIT_28D, [2.0, 2.1, 1.9]
    task.execute(t, ctx)
    assert sh.read(18, c0 + 3) == 2.0
    assert sh.read(18, c0 + 9) == "합   격"       # 공백 3칸
    assert 목록.read(12, 4) == 2.0

    대장 = books["ledger_civil"].sheet("26.09")   # 채취 9/1 + 28일 = 9/29
    r = FIRST_DATA_ROW
    assert 대장.read(r, COL["날짜"]) == date(2026, 9, 29)
    assert 대장.read(r, COL["구분"]) == "Q-Q-\n03-09"
    assert 대장.read(r, COL["대상재료"]) == "BSCW 압축강도"
    assert 대장.read(r, COL["종목"]) == "7일 압축강도"
    assert 대장.read(r + 1, COL["종목"]) == "28일 압축강도"
    assert 대장.read(r, COL["기준"]) == "-"
    assert 대장.read(r + 1, COL["기준"]) == "1.5 이상"
    assert 대장.read(r, COL["결과"]) == 1.02
    assert 대장.read(r + 1, COL["결과"]) == 2.0
    assert 대장.read(r, COL["판정"]) == "합 격"


def test_압축강도_대장날짜는_채취일_28일_BSCW함정():
    """§15.2 실측 — 채취 7/31 -> 28일 8/28 -> 26.08 시트."""
    ctx, books = 시험_context()
    task = CompressiveTask(cfg(), Series.BSCW)
    t = CompressiveTest(series=Series.BSCW, 번호=1, 채취일=date(2026, 7, 31),
                        목록행번호=1, stage=CompStage.AWAIT_28D,
                        측정_7일=[1.2, 1.2, 1.2], 측정_28일=[2.4, 2.4, 2.4])
    task.execute(t, ctx)
    assert t.완료일 == date(2026, 8, 28)
    sh = books["ledger_civil"].sheet("26.08")
    r = sh.last_filled_row(COL["일련번호"], FIRST_DATA_ROW)
    assert sh.read(r, COL["날짜"]) == date(2026, 8, 28)
    assert sh.read(r, COL["일련번호"]) == 2       # 26.08 에 1건이 이미 있었다


def test_JSP는_전용계열_Q_Q_04():
    """§18.4 — JSP 는 Q-Q-04, 공종도 흙막이(JSP)."""
    ctx, books = 시험_context()
    task = CompressiveTask(cfg(), Series.JSP)
    t = CompressiveTest(series=Series.JSP, 번호=2, 채취일=date(2026, 8, 28),
                        목록행번호=2, stage=CompStage.NEW)
    task.execute(t, ctx)
    sh = books["test_bscw_jsp"].sheet("JSP_압축강도_시험일지")
    c0 = col_index("L")                           # 12 = 2번 블록
    assert sh.read(5, c0 + 2) == "Q-Q-04-02"
    assert sh.read(4, c0 + 2) == " 흙막이(JSP)"
    assert sh.read(1, c0 + 1) == "JSP 압축강도 시험일지   "
    목록 = books["test_bscw_jsp"].sheet("시험목록")
    assert 목록.read(5, 6) == date(2026, 8, 28)   # JSP 는 E~H 열


def test_JSP_기존1번블록은_Q_Q_04로_찾히지_않는다():
    """§21.2 #4 — JSP 1번 블록은 BSCW 를 복사하다 만 상태(Q-Q-03-01)라 재작성이 필요하다.

    프로그램이 그 블록을 JSP 1번으로 착각해 덮어쓰면 안 된다.
    """
    ctx, _ = 시험_context()
    task = CompressiveTask(cfg(), Series.JSP)
    t = CompressiveTest(series=Series.JSP, 번호=1, 채취일=date(2026, 8, 27),
                        목록행번호=1, stage=CompStage.AWAIT_28D,
                        측정_7일=[2.54, 2.54, 2.54], 측정_28일=[3.0, 3.0, 3.0])
    with pytest.raises(ValueError, match="Q-Q-04-01"):
        task.execute(t, ctx)


def test_JSP_대장은_토목대장에_JSP압축강도로():
    ctx, books = 시험_context()
    task = CompressiveTask(cfg(), Series.JSP)
    t = CompressiveTest(series=Series.JSP, 번호=2, 채취일=date(2026, 8, 27),
                        목록행번호=2, stage=CompStage.NEW)
    task.execute(t, ctx)                          # 먼저 채취 등록
    t.stage = CompStage.AWAIT_28D
    t.측정_7일 = [2.63, 2.63, 2.63]
    t.측정_28일 = [3.0, 3.0, 3.0]
    task.execute(t, ctx)
    sh = books["ledger_civil"].sheet("26.09")     # 8/27 + 28 = 9/24
    assert sh.read(FIRST_DATA_ROW, COL["대상재료"]) == "JSP 압축강도"
    assert sh.read(FIRST_DATA_ROW, COL["구분"]) == "Q-Q-\n04-02"


def test_압축강도_등록안된_시험은_7일입력을_막는다():
    ctx, _ = 시험_context()
    task = CompressiveTask(cfg(), Series.BSCW)
    t = CompressiveTest(series=Series.BSCW, 번호=99, 채취일=date(2026, 9, 1),
                        stage=CompStage.AWAIT_7D, 측정_7일=[1, 1, 1])
    with pytest.raises(ValueError, match="찾지 못했습니다"):
        task.execute(t, ctx)


def test_평균은_소수2자리로_통일():
    """§18.3 — 0.98+1.04+1.06 -> 1.03."""
    t = CompressiveTest(series=Series.BSCW, 번호=7, 채취일=date(2026, 8, 1),
                        측정_7일=[0.98, 1.04, 1.06])
    assert t.평균_7일 == 1.03


# =====================================================================
# 행그룹이 겹치지 않는가 (§14.4)
# =====================================================================
def test_실시대장_h5_그룹_두건이_겹치지_않는다():
    """A~G 가 세로 병합이라 A열만 보면 직전 그룹 위에 덮어쓴다."""
    ctx, books = 시험_context()
    task = PhcShapeTask(cfg())
    for n, day in ((7, date(2026, 9, 5)), (8, date(2026, 9, 8))):
        data = 겉모양시험()
        data.번호, data.시료채취일 = n, day
        task._write_ledger(data, ctx)

    sh = books["ledger_pile"].sheet("26.09")
    assert sh.read(FIRST_DATA_ROW, COL["구분"]) == "Q-Q-\n02-07"
    assert sh.read(FIRST_DATA_ROW + 5, COL["구분"]) == "Q-Q-\n02-08"    # 4행 -> 9행
    assert sh.read(FIRST_DATA_ROW + 5, COL["일련번호"]) == 2
    # 첫 그룹의 꼬리(모양·겉모양)가 살아 있어야 한다
    assert sh.read(FIRST_DATA_ROW + 3, COL["종목"]) == "모양"
    assert sh.read(FIRST_DATA_ROW + 4, COL["종목"]) == "겉모양"


def test_실시대장_기존_h5_그룹_다음에_이어쓴다():
    """26.08 시트에는 겉모양 1건(4~8행)이 이미 있다. 다음은 9행부터."""
    ctx, books = 시험_context()
    data = 겉모양시험()
    data.시료채취일 = date(2026, 8, 31)
    PhcShapeTask(cfg())._write_ledger(data, ctx)
    sh = books["ledger_pile"].sheet("26.08")
    assert sh.read(9, COL["구분"]) == "Q-Q-\n02-07"
    assert sh.read(9, COL["일련번호"]) == 2
    assert sh.read(4, COL["구분"]) == "Q-Q-\n02-01"     # 기존 건은 그대로
    assert sh.read(5, COL["세부"]) == "바깥\n지름"


def test_밀크_h2_그룹_두건이_겹치지_않는다():
    ctx, books = 시험_context()
    task = PhcMilkTask(cfg())
    for n in (4, 5):
        data = 밀크시험()
        data.번호 = n
        task._write_ledger(data, ctx)
    sh = books["ledger_pile"].sheet("26.09")
    assert sh.read(FIRST_DATA_ROW, COL["구분"]) == "Q-Q-\n01-04"
    assert sh.read(FIRST_DATA_ROW + 2, COL["구분"]) == "Q-Q-\n01-05"
    assert sh.read(FIRST_DATA_ROW + 1, COL["결과"]) == 39.3      # 첫 건 S-2 보존
