"""데이터 모델 (SPEC §3, §16~§18)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


# =====================================================================
# PART 1 — 자재검수
# =====================================================================
@dataclass
class MaterialRow:
    """자재 1줄 (갑지 5~8행에 대응, 최대 4줄)."""

    품명: str = "PHC파일"
    규격: str = ""            # 'Ø500-15M'
    단위: str = "본"
    전일수량: int | str = "-"  # 이전 회차 누계 (없으면 '-')
    반입수량: int = 0
    비고: str = ""            # '㈜한국파일/\n아주산업㈜'

    @property
    def 누계수량(self) -> int | str:
        if isinstance(self.전일수량, (int, float)):
            return int(self.전일수량) + int(self.반입수량)
        return int(self.반입수량)


@dataclass
class DeliveryRow:
    """송장 1건 (★수불부 체크용 1행에 대응)."""

    송장일자: date
    반입일자: date
    업체명: str               # vendor_alias 의 어떤 표기든 허용 (정규화해서 쓴다)
    규격_A: int = 500
    규격_m: int = 15
    구분: str = "상"          # '상' | '하' | '단'
    수량_본: int = 0
    밴드500: int | None = None
    밴드600: int | None = None
    # 규격×본(J열)은 수식, K=차수, L='완' — 쓰기 시점에 엔진이 넣는다


@dataclass
class InspectionRound:
    """자재검수 1회차."""

    차수: int
    반입일자: date
    통보일자: date | None = None      # 기본 = 반입일자
    자재구분: str = "PHC"
    현장약칭: str = "다인영종"
    공종: str = "건축"
    요청서수신: str = "총괄감리원"
    통보서수신: str = "현장대리인"
    첨부물: str = "■ 출하송장, ■ 사진대지 등"
    검수결과: str = "적합"            # '적합' | '부적합'
    부적합사유: str = ""
    특기사항: str = ""
    담당자: str = "이승현"
    현장대리인: str = "이용택"
    담당감리원: str = "김운종"
    총괄감리원: str = "김번환"
    자재목록: list[MaterialRow] = field(default_factory=list)
    송장목록: list[DeliveryRow] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.통보일자 is None:
            self.통보일자 = self.반입일자

    @property
    def 반입수량합계(self) -> int:
        return sum(int(m.반입수량) for m in self.자재목록)

    @property
    def 송장본합계(self) -> int:
        return sum(int(d.수량_본) for d in self.송장목록)


# =====================================================================
# PART 2 — 시험
# =====================================================================
class Series(str, Enum):
    """시험 계열 (SPEC §15.1)."""

    PHC_MILK = "PHC_MILK"      # Q-Q-01
    PHC_SHAPE = "PHC_SHAPE"    # Q-Q-02
    BSCW = "BSCW"              # Q-Q-03
    JSP = "JSP"                # Q-Q-04
    OUTSOURCED = "OUTSOURCED"  # N-02, 시험번호 없음


@dataclass
class ShapeSample:
    """겉모양·치수 시료 1개 (601 일지 9행 이후)."""

    시료번호: int = 1
    길이: float = 0.0
    바깥지름: float = 0.0
    두께: float = 0.0
    모양: str = "이상없음"
    겉모양: str = "이상없음"


@dataclass
class ShapeTest:
    """T-03 PHC 겉모양·치수 (Q-Q-02)."""

    번호: int
    시료채취일: date              # = 시험일자
    업체명: str
    규격_A: int = 500
    규격_m: int = 15
    시료반입일: date | None = None
    시료반입량_본: int = 0
    채취장소: str = "야적장"
    감리원: str = "김운종"
    품질관리기술인: str = "윤재웅"
    시료목록: list[ShapeSample] = field(default_factory=lambda: [ShapeSample()])

    @property
    def 시험일자(self) -> date:
        return self.시료채취일

    @property
    def 시료종류(self) -> str:
        return f"PHC파일-A{self.규격_A}-{self.규격_m}M"

    @property
    def 완료일(self) -> date:
        return self.시료채취일          # §15.2


@dataclass
class MilkSpecimen:
    """밀크 시험 시료 1개 (S-1 / S-2). 입력은 숫자 3개뿐."""

    총중량: float = 0.0
    건조중량: float = 0.0
    용기무게: float = 0.0

    @property
    def 시멘트질량(self) -> float:      # ④ = ② - ③
        return self.건조중량 - self.용기무게

    @property
    def 물질량(self) -> float:          # ⑤ = ① - ④ - ③
        return self.총중량 - self.시멘트질량 - self.용기무게

    @property
    def 물시멘트비(self) -> float:      # ⑤/④ × 100
        if self.시멘트질량 == 0:
            raise ZeroDivisionError("시멘트 질량이 0입니다 (건조중량 = 용기무게)")
        return self.물질량 / self.시멘트질량 * 100


@dataclass
class MilkTest:
    """T-04 PHC 밀크 / 물시멘트비 (Q-Q-01)."""

    번호: int
    시료채취일: date
    시험일자: date
    S1: MilkSpecimen
    S2: MilkSpecimen
    시료종류: str = "시멘트 페이스트"
    채취장소: str = "현장 내"
    시공업체: str = "이산지반건설"
    기준: str = "83%이하"
    한계: float = 83.0
    품질관리기술인: str = "윤재웅"
    감리원: str = "김운종"

    @property
    def 결과들(self) -> tuple[float, float]:
        return (self.S1.물시멘트비, self.S2.물시멘트비)

    @property
    def 합격(self) -> bool:
        return all(v <= self.한계 for v in self.결과들)

    @property
    def 완료일(self) -> date:
        return self.시험일자             # §15.2


class CompStage(str, Enum):
    """BSCW/JSP 상태 기계 (SPEC §18.1)."""

    NEW = "NEW"
    AWAIT_7D = "AWAIT_7D"
    AWAIT_28D = "AWAIT_28D"
    DONE = "DONE"


@dataclass
class CompressiveTest:
    """T-05 BSCW / JSP 압축강도. 2단계 태스크."""

    series: Series                   # Series.BSCW | Series.JSP
    번호: int
    채취일: date                     # = 타설일
    목록행번호: int | None = None     # 613 '시험목록' 의 1~36 중 몇 번인지 (기본 = 번호)
    공종: str = ""
    시공업체: str = "한성토건"
    채취장소: str = "현장 내"
    측정_7일: list[float] = field(default_factory=list)
    측정_28일: list[float] = field(default_factory=list)
    stage: CompStage = CompStage.NEW
    품질관리기술인: str = "윤재웅"
    감리원: str = "김남일"
    기준: float = 1.5

    def __post_init__(self) -> None:
        if not self.공종:
            self.공종 = " 흙막이(BSCW)" if self.series is Series.BSCW else " 흙막이(JSP)"
        if self.목록행번호 is None:
            self.목록행번호 = self.번호

    # -- 날짜 (§18.1) --------------------------------------------------
    @property
    def 일자_7일(self) -> date:
        from datetime import timedelta

        return self.채취일 + timedelta(days=7)

    @property
    def 일자_28일(self) -> date:
        from datetime import timedelta

        return self.채취일 + timedelta(days=28)

    @property
    def 완료일(self) -> date:
        """§15.2 — BSCW/JSP 의 대장 날짜는 28일 강도일이다. 채취일이 아니다."""
        return self.일자_28일

    # -- 평균 (§18.3 소수 2자리로 통일) ---------------------------------
    @staticmethod
    def 평균(values: list[float], digits: int = 2) -> float | None:
        if len(values) != 3:
            return None
        return round(sum(values) / 3, digits)

    @property
    def 평균_7일(self) -> float | None:
        return self.평균(self.측정_7일)

    @property
    def 평균_28일(self) -> float | None:
        return self.평균(self.측정_28일)

    @property
    def 합격(self) -> bool | None:
        avg = self.평균_28일
        return None if avg is None else avg >= self.기준
