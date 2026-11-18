"""Workbook, HTML and view model must show the same canonical totals."""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from lb_local import load

Issue = load("model").Issue


def _sheet_value(path: Path, sheet: str, row: int, column: int):
    book = load_workbook(path, data_only=True)
    try:
        return book[sheet].cell(row, column).value
    finally:
        book.close()


def _same_amount(left, right) -> bool:
    if left in (None, "") or right in (None, ""):
        return False
    D = load("model").D
    try:
        return D(left) == D(right)
    except Exception:
        return str(left) == str(right)


def reconcile(view: dict, workbook_path: Path, html_path: Path, docx_path: Path | None = None) -> list[Issue]:
    issues: list[Issue] = []
    total_cell = _sheet_value(workbook_path, "Summary", 2, 2)
    if not _same_amount(total_cell, view.get("total")):
        issues.append(Issue("error", "total_mismatch", "workbook", "итог книги не равен view model"))
    html = Path(html_path).read_text(encoding="utf-8")
    needle = f'data-total-budget="{view.get("total")}"'
    if needle not in html:
        issues.append(Issue("error", "html_total_mismatch", "html", "итог HTML не равен view model"))
    saving = view.get("scenario_saving")
    if saving is not None and f'data-scenario-saving="{saving}"' not in html:
        issues.append(Issue("error", "html_scenario_mismatch", "html", "экономия сценария не совпала"))
    if "<th>Месяц</th>" not in html:
        issues.append(Issue("error", "monthly_not_table", "html", "помесячный блок не таблица"))
    bridge_total = view.get("bridge_total")
    if bridge_total:
        if f'data-bridge-total="{bridge_total}"' not in html:
            issues.append(Issue("error", "html_bridge_mismatch", "html", "итог моста не совпал"))
        if not _same_amount(_sheet_value(workbook_path, "Summary", 4, 2), bridge_total):
            issues.append(Issue("error", "workbook_bridge_mismatch", "workbook", "мост книги не совпал"))
        if not _same_amount(bridge_total, view.get("total")):
            issues.append(Issue("error", "bridge_total_mismatch", "bridge", "итог моста не равен итогу строк"))
    remote = ("cdn.", "googleapis", "fonts.google", "script src=\"http")
    if any(token in html for token in remote):
        issues.append(Issue("error", "external_asset", "html", "HTML тянет внешний ресурс"))
    for item in view.get("findings") or []:
        token = str(item.get("id") or "")
        if token and token not in html:
            issues.append(Issue("error", "html_finding_missing", "html", f"в HTML нет {token}"))
    if docx_path is not None and Path(docx_path).exists():
        from docx import Document

        text = "\n".join(paragraph.text for paragraph in Document(docx_path).paragraphs)
        if str(view.get("total")) not in text:
            issues.append(Issue("error", "docx_total_mismatch", "docx", "итог записки не равен view model"))
        for item in view.get("findings") or []:
            token = str(item.get("id") or "")
            if token and token not in text:
                issues.append(Issue("error", "docx_finding_missing", "docx", f"в записке нет {token}"))
    return issues
