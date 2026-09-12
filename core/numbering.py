"""문서번호 · 시험번호 · 서명 포맷 · 날짜 규칙 (SPEC §3, §15).

여기 있는 함수들은 전부 순수 함수다. 엑셀도 설정도 필요 없다.
"""
from __future__ import annotations

from datetime import date

from .models import Series

# ---------------------------------------------------------------------
# 시험 계열 (SPEC §15.1)
# ---------------------------------------------------------------------
TEST_SERIES: dict[Series, dict] = {
    Series.PHC_MILK:   {"prefix": "Q-Q-01-", "ledger": "ledger_pile",  "journal": "test_milk",
                        "sheet": None,                          # 시트 복제형
                        "대상재료": "PHC파일 밀크",  "그룹높이": 2},
    Series.PHC_SHAPE:  {"prefix": "Q-Q-02-", "ledger": "ledger_pile",  "journal": "test_shape",
                        "sheet": "일지",
                        "대상재료": "PHC 파일 \n겉모양, 치수", "그룹높이": 5},
    Series.BSCW:       {"prefix": "Q-Q-03-", "ledger": "ledger_civil", "journal": "test_bscw_jsp",
                        "sheet": "BSCW_압축강도_시험일지",
                        "대상재료": "BSCW 압축강도", "그룹높이": 2},
    Series.JSP:        {"prefix": "Q-Q-04-", "ledger": "ledger_civil", "journal": "test_bscw_jsp",
                        "sheet": "JSP_압축강도_시험일지",
                        "대상재료": "JSP 압축강도",  "그룹높이": 2},
    Series.OUTSOURCED: {"prefix": None,      "ledger": "ledger_outsrc", "journal": None,
                        "sheet": None,
                        "대상재료": None,            "그룹높이": None},
}


def 시험번호(series: Series, n: int) -> str:
    """'Q-Q-02-07'. 번호는 연간 통번호다 (월 리셋 아님)."""
    prefix = TEST_SERIES[series]["prefix"]
    if prefix is None:
        raise ValueError(f"{series.value} 계열은 시험번호가 없습니다 (의뢰시험)")
    return f"{prefix}{n:02d}"


def 대장_구분표기(series: Series, n: int) -> str:
    """실시대장 C열은 줄바꿈이 들어간다: 'Q-Q-\\n02-07'."""
    prefix = TEST_SERIES[series]["prefix"]
    if prefix is None:
        return "의뢰시험"
    return f"{prefix[:4]}\n{prefix[4:]}{n:02d}"


def parse_시험번호(text: str | None) -> tuple[str, int] | None:
    """'Q-Q-02-07' 또는 'Q-Q-\\n02-07' -> ('Q-Q-02-', 7). 못 읽으면 None."""
    if text is None:
        return None
    flat = str(text).replace("\n", "").replace(" ", "")
    if not flat.upper().startswith("Q-Q-"):
        return None
    parts = flat.split("-")
    if len(parts) < 4:
        return None
    try:
        return (f"Q-Q-{parts[2]}-", int(parts[3]))
    except ValueError:
        return None


def series_of(text: str | None) -> Series | None:
    """시험번호 문자열에서 계열을 알아낸다."""
    parsed = parse_시험번호(text)
    if parsed is None:
        return None
    prefix, _ = parsed
    for s, meta in TEST_SERIES.items():
        if meta["prefix"] == prefix:
            return s
    return None


# ---------------------------------------------------------------------
# 자재검수 문서번호 (SPEC §3)
# ---------------------------------------------------------------------
def 요청서_문서번호(차수: int) -> str:
    """'Q-G-03(파일)-13' — 2자리 패딩 (§10 #9)."""
    return f"Q-G-03(파일)-{차수:02d}"


def 통보서_문서번호(차수: int, 통보일자: date, 현장약칭: str = "다인영종",
                    자재구분: str = "PHC") -> str:
    """'다인영종-자검(PHC)26-13'."""
    return f"{현장약칭}-자검({자재구분}){통보일자:%y}-{차수:02d}"


def 검수결과_표기(적합: bool) -> str:
    return "■ 적합,     □ 부적합" if 적합 else "□ 적합,     ■ 부적합"


# ---------------------------------------------------------------------
# 서명 / 날짜 표기
# ---------------------------------------------------------------------
def 서명포맷(name: str) -> str:
    """'이용택' -> '이 용 택', '최수' -> '최     수' (2글자는 공백 5칸)."""
    name = name.strip()
    if not name:
        return ""
    if len(name) == 1:
        return name
    if len(name) == 2:
        return f"{name[0]}     {name[1]}"
    return " ".join(name)


def 서명란(name: str) -> str:
    """셀에 실제로 들어가는 값: 서명포맷 + '   (인)'."""
    return f"{서명포맷(name)}   (인)"


def 서명줄(label: str, name: str) -> str:
    """일지 하단 '품질관리자  :  윤 재 웅     ( 서 명 )' 형태."""
    return f"{label}  :  {서명포맷(name)}     ( 서 명 )"


def 통보일_문자열(d: date) -> str:
    """'2026 년    9 월  5 일'."""
    return f"{d.year} 년    {d.month} 월  {d.day} 일"


# ---------------------------------------------------------------------
# 실시대장 시트 (SPEC §15.2)
# ---------------------------------------------------------------------
def 대장_시트명(완료일: date) -> str:
    """'26.09'. 대장 B열 '날짜' = 시험 완료일이지 채취일이 아니다."""
    return f"{완료일:%y}.{완료일:%m}"


def 이전_대장_시트명(시트명: str) -> str:
    """'26.09' -> '26.08' (연도 경계 처리 포함)."""
    yy, mm = 시트명.split(".")
    y, m = int(yy), int(mm)
    if m == 1:
        return f"{y - 1:02d}.12"
    return f"{y:02d}.{m - 1:02d}"


# ---------------------------------------------------------------------
# 겉모양·치수 허용차 (SPEC §16.3)
# ---------------------------------------------------------------------
허용차 = {
    "길이":     lambda 규격m: (규격m * 1000 * 0.997, 규격m * 1000 * 1.003),  # ±0.3%
    "바깥지름": lambda 호칭: (호칭 - 2, 호칭 + 5),                            # +5, -2
    "두께":     lambda _: (80.0, float("inf")),                              # 80 이상
}


def 허용차_범위(항목: str, 기준값: float) -> tuple[float, float]:
    return 허용차[항목](기준값)


def 기준문자열(항목: str, 규격m: int = 15) -> str:
    """실시대장 K열에 들어가는 시험 기준 문자열."""
    if 항목 == "길이":
        return f"±0.3%\n(±{int(규격m * 3)})"
    if 항목 == "바깥지름":
        return "+5, -2"
    if 항목 == "두께":
        return "80 이상"
    raise KeyError(항목)


def 판정_겉모양(sample, 규격_A: int, 규격_m: int) -> bool:
    """길이·바깥지름·두께가 전부 허용차 안이고 모양/겉모양이 이상없으면 합격."""
    checks = (
        ("길이", sample.길이, 규격_m),
        ("바깥지름", sample.바깥지름, 규격_A),
        ("두께", sample.두께, None),
    )
    for 항목, 실측, 기준 in checks:
        lo, hi = 허용차_범위(항목, 기준 if 기준 is not None else 0)
        if not (lo <= 실측 <= hi):
            return False
    return "이상" not in str(sample.모양).replace("이상없음", "") and \
           "이상" not in str(sample.겉모양).replace("이상없음", "")


# 파일마다 다른 '합격' 표기 (실측값 그대로)
합격표기 = {
    "일지601": "합 격",      # 601 일지 판정 셀
    "대장601": "합  격",     # 601 대장 E열 (공백 2칸)
    "대장612": "합  격",     # 612 대장 E열
    "일지613": "합   격",    # 613 일지 18행 판정 (공백 3칸)
    "실시대장": "합 격",     # 실시대장 M열 (공백 1칸)
}
불합격표기 = {
    "일지601": "불합격",
    "대장601": "불합격",
    "대장612": "불합격",
    "일지613": "불합격",
    "실시대장": "불합격",
}


def 판정표기(합격: bool, where: str) -> str:
    return (합격표기 if 합격 else 불합격표기)[where]
