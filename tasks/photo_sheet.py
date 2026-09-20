"""자재반입 송장 사진대지 시트 생성 (SPEC §4.4).

1차 자동화 범위는 **시트 복사 + 반입일 기입까지**다.
사진 삽입은 수동이고, 워크플로우 패널에 체크박스로 남는다.
"""
from __future__ import annotations

from datetime import date

from core.context import TaskContext
from core.engines import SheetCloneWriter
from core.sheets import SheetPort

from .base import Task

TEMPLATE_SHEET = "양식"
DATE_CELL = (2, 7)          # G2 — 반입일


class PhotoSheetTask(Task):
    name = "사진대지 시트 생성"
    workflow_file = "자재검수.yaml"
    target_files = ("photo_template",)

    def validate_before(self, data: date, ctx: TaskContext) -> list[str]:
        book = ctx.book("photo_template")
        if not book.has_sheet(TEMPLATE_SHEET):
            return [f"사진대지 양식에 `{TEMPLATE_SHEET}` 시트가 없습니다: {book.sheet_names}"]
        return []

    def execute(self, data: date, ctx: TaskContext) -> SheetPort:
        book = ctx.book("photo_template")
        clone = SheetCloneWriter(book, TEMPLATE_SHEET)
        # 같은 이름 시트가 이미 있으면 '0905-2' 로 붙는다
        sheet = clone.clone(f"{data:%m%d}")
        sheet.write(*DATE_CELL, data, number_format="yyyy-mm-dd")
        return sheet
