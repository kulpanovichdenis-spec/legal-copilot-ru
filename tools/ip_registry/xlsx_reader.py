"""Чтение листа «ТЗ» по заголовкам и картинок знаков напрямую из zip-пакета xlsx."""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl

SHEET = "ТЗ"
HEADER_FIELDS = {
    "№ п/п": "row_no",
    "Товарный знак": "mark_text",
    "Вид регистрации": "reg_kind_raw",
    "Заявка №": "application_no",
    "Товарный знак №": "registration_no",
    "Препарат": "product_raw",
    "Классы МКТУ": "nice_raw",
    "Дата приоритета": "priority_date",
    "Назначение": "purpose",
    "Дата истечения срока действия": "expiry_date",
    "Государство действия": "territory_raw",
    "Патентный поверенный": "attorney",
    "Статус": "status_raw",
    "Дата следующей оплаты": "next_payment_date",
    "Контакты поверенных": "attorney_contacts",
}
REQUIRED = ("mark_text", "reg_kind_raw", "registration_no", "product_raw", "territory_raw", "status_raw")

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DML = "http://schemas.openxmlformats.org/drawingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
WEB_MIME = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "gif": "image/gif"}


class RegistryFormatError(ValueError):
    """Выгрузка не того формата: нет листа или обязательной колонки."""


@dataclass
class RawRow:
    sheet_row: int
    values: dict[str, Any]


def _norm_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def read_rows(path: Path, sheet: str = SHEET) -> list[RawRow]:
    try:
        with path.open("rb") as handle:
            workbook = openpyxl.load_workbook(handle, read_only=True, data_only=True)
            try:
                return _read_sheet(workbook, sheet)
            finally:
                workbook.close()
    except RegistryFormatError:
        raise
    except Exception as exc:  # noqa: BLE001 - любой сбой openpyxl/lxml/zipfile = неверный формат
        raise RegistryFormatError(f"файл не читается как xlsx: {exc}") from exc


def _read_sheet(workbook, sheet: str) -> list[RawRow]:
    if sheet not in workbook.sheetnames:
        raise RegistryFormatError(f"в файле нет листа «{sheet}»")
    worksheet = workbook[sheet]
    worksheet.reset_dimensions()
    rows_iter = worksheet.iter_rows(values_only=True)
    header = next(rows_iter, None) or ()
    lookup = {_norm_header(title): field for title, field in HEADER_FIELDS.items()}
    columns: dict[int, str] = {}
    for index, title in enumerate(header):
        field = lookup.get(_norm_header(title))
        if field and field not in columns.values():
            columns[index] = field
    missing = [title for title, field in HEADER_FIELDS.items()
               if field in REQUIRED and field not in columns.values()]
    if missing:
        raise RegistryFormatError("нет обязательных колонок: " + ", ".join(missing))
    result = []
    body = list(rows_iter)
    for excel_row, values in enumerate(body, start=2):
        data: dict[str, Any] = {field: None for field in HEADER_FIELDS.values()}
        data.update({field: (values[index] if index < len(values) else None)
                     for index, field in columns.items()})
        if all(value is None or str(value).strip() == ""
               for field, value in data.items() if field != "row_no"):
            continue
        result.append(RawRow(excel_row, data))
    return result


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    folder, name = posixpath.split(part)
    rels_path = posixpath.join(folder, "_rels", name + ".rels")
    if rels_path not in archive.namelist():
        return {}
    result = {}
    for rel in ET.fromstring(archive.read(rels_path)):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        full = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        result[rel.get("Id")] = (rel.get("Type", ""), full)
    return result


def _sheet_part(archive: zipfile.ZipFile, sheet: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = _rels(archive, "xl/workbook.xml")
    for item in workbook.iter(f"{{{MAIN}}}sheet"):
        if item.get("name") == sheet:
            return rels[item.get(f"{{{REL}}}id")][1]
    raise RegistryFormatError(f"в файле нет листа «{sheet}»")


def parse_anchors(drawing_xml: bytes) -> list[tuple[int, str]]:
    root = ET.fromstring(drawing_xml)
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == f"{{{MC}}}Fallback":
                parent.remove(child)
    result = []
    for element in root.iter():
        if element.tag not in (f"{{{XDR}}}twoCellAnchor", f"{{{XDR}}}oneCellAnchor"):
            continue
        row = element.find(f"{{{XDR}}}from/{{{XDR}}}row")
        blip = element.find(f".//{{{DML}}}blip")
        if row is None or blip is None or not blip.get(f"{{{REL}}}embed"):
            continue
        result.append((int(row.text), blip.get(f"{{{REL}}}embed")))
    return result


def read_images(path: Path, sheet: str = SHEET) -> dict[int, tuple[bytes, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            sheet_part = _sheet_part(archive, sheet)
            parts = set(archive.namelist())
            drawings = [target for kind, target in _rels(archive, sheet_part).values()
                        if kind.endswith("/drawing")]
            result: dict[int, tuple[bytes, str]] = {}
            for drawing in drawings:
                rels = _rels(archive, drawing)
                for zero_row, rel_id in parse_anchors(archive.read(drawing)):
                    target = rels.get(rel_id)
                    if not target:
                        continue
                    ext = target[1].rsplit(".", 1)[-1].lower()
                    if target[1] in parts:
                        image = (archive.read(target[1]), ext)
                    else:
                        image = (b"", "missing")
                    result.setdefault(zero_row + 1, image)
            return result
    except RegistryFormatError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RegistryFormatError(f"файл не читается как xlsx: {exc}") from exc


def to_browser_image(data: bytes, ext: str) -> tuple[bytes, str] | None:
    ext = ext.lower()
    if ext in WEB_MIME:
        return data, WEB_MIME[ext]
    if ext in ("emf", "wmf"):
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(data))
            image.load()
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, "PNG")
            return buffer.getvalue(), "image/png"
        except Exception:
            return None
    return None
