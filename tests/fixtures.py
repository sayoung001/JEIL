"""2026-09-05 실측 상태를 재현한 메모리 통합문서.

SPEC §4 에 적힌 값 그대로 만든다. 이게 있어야 Excel 없이 쓰기 로직을 검증할 수 있다.
"""
from __future__ import annotations

from datetime import date

from core.config import Config, load_config
from core.context import TaskContext
from core.sheets import MemorySheet, MemoryWorkbook, WorkbookPort

CONFIG_PATH = "config.example.yaml"


def cfg() -> Config:
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    return load_config(root / CONFIG_PATH)


# ---------------------------------------------------------------------
def 체크용() -> MemoryWorkbook:
    """★수불부 체크용.xlsx — 시트 `파일 (2)`. 마지막 데이터 행 54 (차수 12)."""
    wb = MemoryWorkbook(path="★수불부 체크용.xlsx")
    sh = wb.add_sheet("파일 (2)")
    sh.write(16, 1, "정산용")
    headers = ["송장일자", "반입일자", "업체명", "규격\n(A-??)", "규격\n(m)", "구분",
               "수량\n(본)", "500밴드\n(EA)", "600밴드\n(EA)", "규격×본\n(m)",
               "자재검수\n차수", "완/미완"]
    for i, h in enumerate(headers, start=1):
        sh.write(17, i, h)

    # 18~54행: 차수 1~12. 여기서는 마지막 몇 행만 실측대로 채운다.
    rows = [
        (18, date(2026, 8, 6), "아주산업", 500, 15, "상", 6, 1),
        (19, date(2026, 8, 6), "아주산업", 500, 15, "하", 6, 1),
        (52, date(2026, 9, 3), "삼일씨엔에스", 500, 15, "상", 12, None),
        (53, date(2026, 9, 4), "동진파일", 500, 14, "상", 12, None),
        (54, date(2026, 9, 4), "동진파일", 500, 14, "하", 12, 12),
    ]
    for r, d, vendor, a, m, gubun, bon, 차수 in rows:
        sh.write(r, 1, d)
        sh.write(r, 2, f"=+A{r}")
        sh.write(r, 3, vendor)
        sh.write(r, 4, a)
        sh.write(r, 5, m)
        sh.write(r, 6, gubun)
        sh.write(r, 7, bon)
        sh.write(r, 10, f"=E{r}*G{r}")
        if 차수:
            sh.write(r, 11, 차수)
            sh.write(r, 12, "완")
    # 55·56행에는 J열 수식만 미리 깔려 있다 (§4.1 — 덮어쓰지 말 것)
    sh.write(55, 10, "=E55*G55")
    sh.write(56, 10, "=E56*G56")
    sh.log.clear()
    return wb


def 갑지() -> MemoryWorkbook:
    """자재검수요청서 갑지.xlsx — 시트 `자재검수(PHC)`. 마지막 블록 CW(차수 12)."""
    wb = MemoryWorkbook(path="자재검수요청서 갑지.xlsx")
    sh = wb.add_sheet("자재검수(PHC)")
    for n in range(1, 12):                    # 블록 1~11 = 차수 2~12
        c0 = 1 + (n - 1) * 10
        차수 = n + 1
        sh.write(1, c0, "자재검수 요청서")
        sh.write(2, c0, "문서번호")
        sh.write(2, c0 + 2, f"Q-G-03(파일)-{차수:02d}")
        sh.write(2, c0 + 4, "수      신")
        sh.write(2, c0 + 6, "총괄감리원")
        sh.write(3, c0, "반입일자")
        sh.write(3, c0 + 2, date(2026, 9, 4))
        sh.write(3, c0 + 4, "공      종")
        sh.write(3, c0 + 6, "건축")
        for i, h in enumerate(["NO", "품명", None, "규격", "단위", "전 일 \n수 량",
                               "반 입 \n수 량 ", "누 계 \n수 량", "비고"]):
            if h:
                sh.write(4, c0 + i, h)
        for i, row in enumerate((5, 6, 7, 8)):            # 직전 회차 자재 4건이 차 있다
            sh.write(row, c0, i + 1)
            sh.write(row, c0 + 1, "PHC파일")
            sh.write(row, c0 + 3, "Ø500-14M")
            sh.write(row, c0 + 4, "본")
            sh.write(row, c0 + 5, 100 + i)
            sh.write(row, c0 + 6, 12)
            sh.write(row, c0 + 7, f"=+{_L(c0 + 5)}{row}+{_L(c0 + 6)}{row}")
            sh.write(row, c0 + 8, "동진파일㈜")
        sh.write(9, c0, "합계")
        for off in (5, 6, 7):
            sh.write(9, c0 + off, f"=SUM({_L(c0 + off)}5:{_L(c0 + off)}8)")
        sh.write(11, c0, "첨 부 물")
        sh.write(11, c0 + 3, "■ 출하송장, ■ 사진대지 등")
        sh.write(12, c0, "주요 자재 검수를 위와 같이 요청합니다.")
        sh.write(12, c0 + 8, "이 승 현   (인)")
        sh.write(13, c0 + 8, "이 용 택   (인)")
        sh.write(14, c0, "자재검수결과 통보서")
        sh.write(15, c0 + 2, f"다인영종-자검(PHC)26-{차수:02d}")
        sh.write(16, c0 + 2, "■ 적합,     □ 부적합")
        sh.write(18, c0 + 9, "2026 년    9 월  4 일")
        sh.write(19, c0 + 8, "김 운 종   (인)")
        sh.write(20, c0 + 8, "김 번 환   (인)")
        for i in range(10):
            sh.set_column_width(c0 + i, 9.0 + i)
    sh.print_area = (1, 101, 20, 110)         # 'CW1:DF20'
    sh.log.clear()
    return wb


def 수불부() -> MemoryWorkbook:
    """JQC304-A 자재수불부(PHC파일).xlsx — 시트 `500`. 8월(A) · 9월(Q) 블록."""
    wb = MemoryWorkbook(path="JQC304-A 자재수불부(PHC파일).xlsx")
    sh = wb.add_sheet("500")
    for n, (label, rows) in enumerate([("26년 08월", 14), ("26년 09월", 3)], start=1):
        c0 = 1 + (n - 1) * 16
        sh.write(1, c0, f"주요자재 검사 및 수불부 ({label})")
        sh.write(2, c0, "품명 : ")
        sh.write(2, c0 + 2, "PHC 파일")
        prev_r, prev_c = None, None
        for i in range(rows):
            r = 5 + i * 2
            sh.write(r, c0 + 1, "m")
            sh.write(r, c0 + 2, "A500")
            sh.write(r, c0 + 3, 15)
            sh.write(r, c0 + 4, date(2026, 7 + n, 5 + i))
            sh.write(r, c0 + 5, 12)
            sh.write(r, c0 + 6, f"={_L(c0 + 3)}{r}*{_L(c0 + 5)}{r}")
            if prev_r is None and n == 1:
                sh.write(r, c0 + 7, f"={_L(c0 + 6)}{r}")
            elif prev_r is None:              # 9월 첫 행 = 8월 마지막 누계 참조
                sh.write(r, c0 + 7, "=H31+W5")
            else:
                sh.write(r, c0 + 7, f"=+{_L(prev_c)}{prev_r}+{_L(c0 + 6)}{r}")
            sh.write(r, c0 + 10, f"=+{_L(c0 + 4)}{r}")
            sh.write(r, c0 + 11, f"={_L(c0 + 6)}{r}")
            sh.write(r, c0 + 15, "동진파일")
            prev_r, prev_c = r, c0 + 7
        sh.write(5, c0, "-")
        sh.write(5, c0 + 12, "-")
    sh.log.clear()
    return wb


def _L(col: int) -> str:
    from core.sheets import col_letter

    return col_letter(col)


class FakeContext(TaskContext):
    """미리 만든 메모리 통합문서를 태스크에 물려 준다."""

    def __init__(self, config: Config, books: dict[str, MemoryWorkbook]):
        super().__init__(config)
        self._books = books

    @property
    def is_preview(self) -> bool:
        return True

    def _open(self, path):  # noqa: ANN001
        raise AssertionError("FakeContext 는 미리 준 통합문서만 씁니다")

    def book(self, file_key: str) -> WorkbookPort:
        if file_key not in self._books:
            raise KeyError(f"테스트 통합문서에 없는 키: {file_key}")
        self._opened[file_key] = self._books[file_key]
        return self._books[file_key]


def full_context() -> tuple[FakeContext, dict[str, MemoryWorkbook]]:
    books = {"supply_check": 체크용(), "request_cover": 갑지(), "ledger_phc": 수불부()}
    return FakeContext(cfg(), books), books


# =====================================================================
# PART 2 — 시험 파일
# =====================================================================
def 일지601() -> MemoryWorkbook:
    """601. PHC파일 겉모양,치수 검사 작업일지.xlsx — 마지막 블록 BI(6번)."""
    wb = MemoryWorkbook(path="601. PHC파일 겉모양,치수 검사 작업일지.xlsx")
    sh = wb.add_sheet("일지")
    for n in range(1, 7):                      # 블록 1~6 (BI = 61열 = 6번)
        c0 = 1 + (n - 1) * 12
        sh.write(1, c0, "PHC파일 겉모양 · 치수 검사 작업일지")
        sh.write(2, c0, "공 사 명 : 영종하늘 A16BL 공공지원 민간임대주택 신축공사")
        sh.write(3, c0, "1.시험번호")
        sh.write(3, c0 + 3, f"Q-Q-02-{n:02d}")
        sh.write(3, c0 + 6, "5.채취장소")
        sh.write(3, c0 + 9, "야적장")
        sh.write(4, c0, "2.시료종류")
        sh.write(4, c0 + 3, "PHC파일-A500-15M")
        sh.write(4, c0 + 6, "6.생산업체")
        sh.write(4, c0 + 9, "동진파일㈜ ")
        sh.write(5, c0, "3. 시료채취일")
        sh.write(5, c0 + 3, date(2026, 9, 4))
        sh.write(5, c0 + 6, "7. 시료반입일")
        sh.write(5, c0 + 9, date(2026, 9, 4))
        sh.write(6, c0, "4.시험일자")
        sh.write(6, c0 + 3, f"=+{_L(c0 + 3)}5")
        sh.write(6, c0 + 6, "8. 시료반입량")
        sh.write(6, c0 + 9, "24 본")
        sh.write(9, c0, 1)
        sh.write(9, c0 + 1, 15017)
        sh.write(9, c0 + 3, 503)
        sh.write(9, c0 + 5, 84)
        sh.write(9, c0 + 7, "이상없음")
        sh.write(9, c0 + 9, "이상없음")
        sh.write(9, c0 + 11, "합 격")
        sh.write(20, c0, "품질관리자  :  윤 재 웅     ( 서 명 )")
        sh.write(22, c0, "감   리   원  :  김 운 종     ( 서 명 )")
    sh.print_area = (1, 61, 23, 72)            # 'BI1:BT23'

    대장 = wb.add_sheet("대장")
    for i, h in enumerate(["No", "날짜", "업체명", "규격", "판정", "CSI"], start=1):
        대장.write(4, i, h)
    for i in range(6):
        r = 5 + i
        대장.write(r, 1, i + 1)
        대장.write(r, 2, date(2026, 8, 20 + i))
        대장.write(r, 3, "동진파일㈜ ")
        대장.write(r, 4, "500-15")
        대장.write(r, 5, "합  격")
        대장.write(r, 6, "ㅇ")
    for s in wb.sheets.values():
        s.log.clear()
    return wb


def 일지612() -> MemoryWorkbook:
    """612. PHC파일 밀크 시험일지.xls — 시트 양식/대장/01/사진대지/02/…"""
    wb = MemoryWorkbook(path="612. PHC파일 밀크 시험일지.xls")
    양식 = wb.add_sheet("양식")
    양식.write(1, 1, "PHC파일 물시멘트비(W/C) 시험·검사 작업일지")
    양식.write(3, 1, "1. 시 험 번 호 :")
    양식.write(4, 1, "2. 시 료 종 류 :")
    양식.write(5, 1, "3. 시 험 일 자 :")
    양식.write(8, 1, "① 시료의 총중량 (g)")
    양식.write(11, 9, "=I9-I10")
    양식.write(13, 9, "=I12/I11*100")
    양식.print_area = (1, 1, 20, 30)

    대장 = wb.add_sheet("대장")
    대장.write(4, 3, "시 험 결 과")
    for i in range(3):
        r = 5 + i
        대장.write(r, 1, i + 1)
        대장.write(r, 2, date(2026, 9, 1 + i))
        대장.write(r, 3, 79.9)
        대장.write(r, 4, 76.4)
        대장.write(r, 5, "합  격")
    for name in ("01", "사진대지", "02", "사진대지 (2)", "03", "사진대지 (3)"):
        wb.add_sheet(name)
    for s in wb.sheets.values():
        s.log.clear()
    return wb


def 일지613() -> MemoryWorkbook:
    """613. BSCW, JSP 시험일지.xlsx — BSCW 마지막 블록 BZ(8번), JSP 1번."""
    wb = MemoryWorkbook(path="613. BSCW, JSP 시험일지.xlsx")

    def _block(sh, n, prefix, title, 공종):
        c0 = 1 + (n - 1) * 11
        sh.write(1, c0 + 1, title)
        sh.write(2, c0, "공사명")
        sh.write(4, c0, " 1. 공      종 :")
        sh.write(4, c0 + 2, 공종)
        sh.write(4, c0 + 6, "3. 채취일자 : ")
        sh.write(4, c0 + 8, date(2026, 7, 31))
        sh.write(5, c0, " 2. 시험번호 : ")
        sh.write(5, c0 + 2, f"{prefix}{n:02d}")
        sh.write(5, c0 + 6, "4. 채취장소 :")
        sh.write(5, c0 + 8, " 현장 내")
        sh.write(6, c0 + 2, " 한성토건")
        sh.write(9, c0 + 9, f"={_L(c0 + 8)}4+7")
        sh.write(16, c0 + 9, f"={_L(c0 + 9)}9+21")
        for r in (11, 18):
            sh.write(r, c0 + 6,
                     f"=({_L(c0 + 3)}{r}+{_L(c0 + 3)}{r + 1}+{_L(c0 + 3)}{r + 2})/3")
        for i, r in enumerate((11, 12, 13)):
            sh.write(r, c0, f"S - {i + 1}")
            sh.write(r, c0 + 3, 1.0 + i * 0.02)
        sh.write(11, c0 + 9, "-")
        sh.write(25, c0, "품질관리자  :  윤 재 웅     ( 서 명 )")
        sh.write(26, c0, "감   리   원  :  김 남 일     ( 서 명 )")

    bscw = wb.add_sheet("BSCW_압축강도_시험일지")
    for n in range(1, 9):
        _block(bscw, n, "Q-Q-03-", "BSCW 압축강도 시험일지   ", " 흙막이(BSCW)")
    bscw.print_area = (1, 78, 26, 88)          # 'BZ1:CJ26'

    jsp = wb.add_sheet("JSP_압축강도_시험일지")
    _block(jsp, 1, "Q-Q-03-", "JSP 압축강도 시험일지   ", " 흙막이(BSCW)")  # §21.2 #4 상태

    목록 = wb.add_sheet("시험목록")
    for i, h in enumerate(["시험번호", "타설일", "7일강도", "28일강도"] * 2, start=1):
        목록.write(3, i, h)
    for i in range(36):                        # 번호 1~36 이 미리 채워져 있다
        r = 4 + i
        목록.write(r, 1, i + 1)
        목록.write(r, 5, i + 1)
    for i, (타설, s7, s28) in enumerate([
            (date(2026, 7, 31), 1.21, 2.4), (date(2026, 8, 1), 0.8, 1.9)]):
        목록.write(4 + i, 2, 타설)
        목록.write(4 + i, 3, s7)
        목록.write(4 + i, 4, s28)
    for i, (타설, s7) in enumerate([
            (date(2026, 8, 27), 2.54), (date(2026, 8, 28), 2.63), (date(2026, 8, 29), 2.10)]):
        목록.write(4 + i, 6, 타설)
        목록.write(4 + i, 7, s7)
    wb.add_sheet("사진")
    wb.add_sheet("사진 (2)")
    for s in wb.sheets.values():
        s.log.clear()
    return wb


def 실시대장(sheets: tuple[str, ...] = ("26.08", "26.09")) -> MemoryWorkbook:
    """Q-01,02 / Q-03 실시대장.xls — 열 구성은 3종이 동일하다 (§14.4)."""
    wb = MemoryWorkbook(path="Q-01,02 품질검사 실시대장(파일).xls")
    for name in sheets:
        sh = wb.add_sheet(name)
        sh.write(1, 1, f"품질검사 실시대장 ({name})")
        headers = ["일련\n번호", "날 짜", "시험·검사\n구분", "품질검사\n대상 재료", "규 격",
                   "건설자재,부재를공급받은 공장", "시험 · 검사\n장  소", "시험 · 검사\n종   목",
                   None, "단 위", "시 험 기 준", "시 험 결 과", "시 험\n결 과\n판 정",
                   "성명", "서명", "성명", "서명", "비 고"]
        for i, h in enumerate(headers, start=1):
            if h:
                sh.write(3, i, h)
    # 26.08 에 겉모양 1건(h=5, 4~8행)이 이미 있다 — 실제 파일과 같은 모양으로
    sh = wb.sheet(sheets[0])
    sh.write(4, 1, 1)
    sh.write(4, 2, date(2026, 8, 20))
    sh.write(4, 3, "Q-Q-\n02-01")
    sh.write(4, 4, "PHC 파일 \n겉모양, 치수")
    sh.write(4, 5, "500-15")
    sh.write(4, 6, "아주산업")
    sh.write(4, 7, "현장내")
    sh.write(4, 8, "치 수")            # H{r}:H{r+2}
    sh.write(7, 8, "모양")             # H{r+3}:I{r+3}
    sh.write(8, 8, "겉모양")           # H{r+4}:I{r+4}
    sh.write(4, 9, "길이")
    sh.write(5, 9, "바깥\n지름")
    sh.write(6, 9, "두께")
    for r, (단위, 기준, 결과) in enumerate([
            ("mm", "±0.3%\n(±45)", 15017), ("mm", "+5, -2", 503), ("mm", "80 이상", 84),
            ("-", "이상없을것", "이상없음"), ("-", "이상없을것", "이상없음")], start=4):
        sh.write(r, 10, 단위)
        sh.write(r, 11, 기준)
        sh.write(r, 12, 결과)
    sh.write(4, 13, "합 격")
    sh.write(4, 14, "윤재웅")
    sh.write(4, 16, "김운종")
    for rect in [(4, c, 8, c) for c in (*range(1, 8), *range(13, 19))]:
        sh.merges.add(rect)
    sh.merges.update({(4, 8, 6, 8), (7, 8, 7, 9), (8, 8, 8, 9)})
    for s in wb.sheets.values():
        s.log.clear()
    return wb


def 시험_context():
    books = {
        "test_shape": 일지601(),
        "test_milk": 일지612(),
        "test_bscw_jsp": 일지613(),
        "ledger_pile": 실시대장(),
        "ledger_civil": 실시대장(),
        "supply_check": 체크용(),
    }
    return FakeContext(cfg(), books), books
