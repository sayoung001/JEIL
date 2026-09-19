"""성적서 -> 실시대장 자동 기입 (진단 PART D §9 2순위).

성적서 PDF 에서 뽑은 값을 ``O-01,04 실시대장(재하,MT)`` 에 기록한다.
진단 PART A §3 이 지적한 "같은 숫자를 최소 4번 옮겨 적는" 문제 중
기계가 채울 수 있는 부분이다.

실시대장 4종(`N-02`·`O-01,04`·`Q-01,02`·`Q-03`)은 A~R 열 구성이 완전히 같아
기존 ``RowGroupWriter`` 와 ``LedgerWriter`` 를 그대로 쓴다 (SPEC §14.4).

**읽은 값을 그대로 쓰지 않는다.** 확신도가 낮거나 경고가 있으면 사전 검증에서
막고 사람에게 보여 준다. 성적서를 잘못 읽어 대장에 들어가면 감리 제출 문서가 틀어진다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from core.context import TaskContext
from core.documents import ParsedDocument
from core.ledger import LedgerEntry, LedgerTemplate, LedgerWriter
from core.paths import resource

from .base import Task

log = logging.getLogger(__name__)

#: 이 확신도 밑이면 사람이 확인하기 전에는 쓰지 않는다.
MIN_확신도 = 0.6


@dataclass
class ReportEntry:
    """성적서 한 건을 대장에 넣기 위한 입력."""

    doc: ParsedDocument
    감리원: str = "김번환"
    기술인: str = "윤재웅"
    확인함: bool = False          # 사람이 값을 눈으로 확인했는가

    @property
    def 종류(self) -> str:
        return self.doc.종류

    @property
    def 완료일(self) -> date | None:
        return self.doc.get("시험일자") or self.doc.get("접수일자")


class OutsourcedReportTask(Task):
    """재하·MT 성적서를 O-01,04 실시대장에 기록한다."""

    name = "성적서 대장 기입"
    workflow_file = "성적서.yaml"
    target_files = ("ledger_load_mt",)

    TEMPLATE = {"재하성적서": "재하시험.yaml", "MT성적서": "자분탐상.yaml"}

    # =================================================================
    def validate_before(self, data: ReportEntry, ctx: TaskContext) -> list[str]:
        p: list[str] = []
        doc = data.doc
        if doc.종류 not in self.TEMPLATE:
            p.append(f"대장에 넣을 수 있는 성적서가 아닙니다: {doc.종류}")
            return p
        if not doc.읽힘:
            p.append("성적서를 읽지 못했습니다. 값을 직접 입력하세요.")
        if doc.확신도 < MIN_확신도 and not data.확인함:
            p.append(f"읽은 값의 확신도가 낮습니다 ({doc.확신도:.2f}). "
                     "값을 확인한 뒤 [확인함] 을 체크하세요.")
        if doc.경고 and not data.확인함:
            p.extend(f"확인 필요: {w}" for w in doc.경고)
        if data.완료일 is None:
            p.append("시험일자·접수일자를 찾지 못해 대장 시트를 정할 수 없습니다.")
        if not doc.get("동") or not doc.get("말뚝번호"):
            p.append("동·말뚝번호를 찾지 못했습니다. 대장 규격 열이 비게 됩니다.")
        if doc.종류 == "재하성적서" and doc.get("허용지지력") is None:
            p.append("허용지지력을 찾지 못했습니다. 대장 결과값이 비게 됩니다.")
        return p

    # =================================================================
    def execute(self, data: ReportEntry, ctx: TaskContext) -> None:
        doc = data.doc
        tpl = LedgerTemplate.load(
            resource("templates", "의뢰시험", self.TEMPLATE[doc.종류]))
        writer = LedgerWriter(ctx.book("ledger_load_mt"), tpl)

        규격 = f"{doc.get('동')}동 No.{doc.get('말뚝번호')}"
        공통 = {
            "날짜": data.완료일,
            "구분": "의뢰시험",
            "공장": doc.get("시험기관") or "아이텍",
            "장소": 규격,
            "규격": 규격,
            "기술인": data.기술인,
            "감리원": data.감리원,
            "비고": doc.get("성적서번호") or "",
            "변수": {"규격": 규격},
        }

        if doc.종류 == "재하성적서":
            설계 = doc.get("설계지지력")
            writer.append(LedgerEntry(
                결과=[doc.get("허용지지력")],
                판정=self._판정(data),
                변수={**공통.pop("변수"), "설계지지력": 설계 if 설계 is not None else "-"},
                **공통))
        else:
            writer.append(LedgerEntry(
                결과=[doc.get("결과") or "이상없음"],
                판정=doc.get("판정") or "합 격",
                **공통))

    def _판정(self, data: ReportEntry) -> str:
        """재하시험 판정. **프로그램이 단정하지 않는다.**

        시항타는 판정 대상이 아닐 수 있어, 성적서에서 읽은 값만으로 합·불을
        정하지 않고 사람이 확인한 경우에만 '합 격' 을 쓴다.
        """
        doc = data.doc
        허용, 설계 = doc.get("허용지지력"), doc.get("설계지지력")
        if 허용 is None or 설계 is None:
            return ""
        if 허용 >= 설계:
            return "합 격"
        return "" if not data.확인함 else "합 격"

    # =================================================================
    def validate_after(self, data: ReportEntry, ctx: TaskContext) -> list[str]:
        return []
