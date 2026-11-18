"""Tabular import. Ambiguous columns stay unmapped and become questions."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from openpyxl import load_workbook

AMBIGUOUS = {"cost", "amount", "sum", "сумма"}


def _profile(headers: list[str]) -> list[dict]:
    questions = []
    for header in headers:
        tokens = set(re.findall(r"[a-zа-яё]+", header.strip().lower()))
        if tokens & AMBIGUOUS:
            questions.append(
                {
                    "column": header,
                    "question": f"«{header}» может быть суммой с налогом или без. Нужен явный смысл колонки.",
                }
            )
    return questions


def _from_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return headers, rows


def _from_xlsx(path: Path, sheet: str | None) -> tuple[list[str], list[dict]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet] if sheet else workbook[workbook.sheetnames[0]]
        grid = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if not grid:
        return [], []
    headers = [str(cell) if cell is not None else "" for cell in grid[0]]
    rows = []
    for raw in grid[1:]:
        rows.append({headers[i]: raw[i] for i in range(len(headers))})
    return headers, rows


def import_table(path: Path, sheet: str | None = None) -> dict:
    path = Path(path)
    before = path.read_bytes()
    if path.suffix.lower() in {".csv", ".tsv"}:
        headers, rows = _from_csv(path)
    elif path.suffix.lower() == ".xlsx":
        headers, rows = _from_xlsx(path, sheet)
    else:
        raise ValueError(f"неподдерживаемый файл: {path.suffix}")
    if path.read_bytes() != before:
        raise RuntimeError("импорт изменил исходный файл")
    return {
        "source": str(path),
        "sheet": sheet,
        "headers": headers,
        "rows": rows,
        "mapping_questions": _profile(headers),
    }
