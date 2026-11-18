"""Строка листа «ТЗ» → нормализованная запись знака; справочник препаратов."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .normalize import (
    RECORD_TO_TERRITORY,
    CountryBook,
    clean,
    national_territories,
    normalize_status,
    number_key,
    parse_classes,
    parse_date,
    parse_number,
    parse_territories,
    product_key,
)
from .xlsx_reader import RawRow, to_browser_image

NO_PRODUCT = "Без препарата"
PRODUCTS_HEADER = (
    "# Справочник препаратов: каноническое имя → варианты написания из столбца «Препарат».\n"
    "# Правит юрист. Сборка только дописывает новые варианты, существующие не меняет.\n"
)
_IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif"}
_DATE_FIELDS = ("priority_date", "expiry_date", "next_payment_date")
MISSING_IMAGE_NOTE = "изображение повреждено в файле реестра — откройте реестр"


def load_products(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    products = (data.get("products") or {}) if isinstance(data, dict) else None
    if not isinstance(products, dict):
        raise ValueError("products.yaml: ожидается словарь products: {Препарат: [варианты]}")
    return {str(name): [str(item) for item in (variants or [])]
            for name, variants in products.items()}


def save_products(path: Path, products: dict[str, list[str]]) -> None:
    ordered = {name: products[name] for name in sorted(products, key=str.casefold)}
    body = yaml.safe_dump({"products": ordered}, allow_unicode=True, sort_keys=False)
    path.write_text(PRODUCTS_HEADER + body, encoding="utf-8")


def product_mapping(products: dict[str, list[str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for canonical, variants in products.items():
        for name in (canonical, *variants):
            mapping.setdefault(product_key(name), canonical)
    return mapping


def plan_products(products: dict[str, list[str]], raw_names: list[Any]) -> dict[str, list[str]]:
    result = {name: list(variants) for name, variants in products.items()}
    mapping = product_mapping(result)
    counts = Counter(name for name in (clean(item) for item in raw_names) if name)
    groups: dict[str, list[str]] = {}
    for name in counts:
        key = product_key(name)
        if key in mapping:
            canonical = mapping[key]
            if name != canonical and name not in result[canonical]:
                result[canonical].append(name)
            continue
        groups.setdefault(key, []).append(name)
    for names in groups.values():
        canonical = max(names, key=lambda item: (counts[item], -names.index(item)))
        result[canonical] = sorted(item for item in names if item != canonical)
    return result


def _image(sheet_row: int, raw: tuple[bytes, str] | None, has_text: bool):
    record_id = f"tm-{sheet_row:04d}"
    if raw is None:
        return None, (None if has_text else "нет изображения в реестре"), None
    if raw[1] == "missing":
        return None, MISSING_IMAGE_NOTE, None
    converted = to_browser_image(*raw)
    if converted is None:
        return None, f"изображение в формате {raw[1].upper()} — откройте реестр", None
    data, mime = converted
    return f"marks/{record_id}.{_IMAGE_EXT[mime]}", None, data


def build_records(
    rows: list[RawRow],
    images: dict[int, tuple[bytes, str]],
    book: CountryBook,
    mapping: dict[str, str],
) -> tuple[list[dict], dict[str, bytes], list[str]]:
    marks: list[dict] = []
    blobs: dict[str, bytes] = {}
    warnings: list[str] = []
    orphans = sorted(set(images) - {row.sheet_row for row in rows})
    if orphans:
        warnings.append(
            f"изображений без строки знака: {len(orphans)} (строки листа {', '.join(map(str, orphans[:10]))})"
        )
    for row in rows:
        values = row.values
        record_warnings: list[str] = []
        mark_text = clean(values.get("mark_text"))
        raw_image = images.get(row.sheet_row)
        image, image_note, data = _image(row.sheet_row, raw_image, bool(mark_text))
        if data is not None:
            blobs[image] = data
        if mark_text and raw_image:
            mark_kind = "text_and_image"
        elif mark_text:
            mark_kind = "word"
        elif raw_image:
            mark_kind = "image"
        else:
            mark_kind = "unknown"

        kind_raw = clean(values.get("reg_kind_raw"))
        reg_type = "madrid" if re.search(r"мадрид|международн", kind_raw or "", re.IGNORECASE) else "national"
        registration_no, registration_note = parse_number(values.get("registration_no"))
        application_no, application_note = parse_number(values.get("application_no"))
        status_raw = clean(values.get("status_raw")) or registration_note
        status, known = normalize_status(status_raw)
        if not status_raw:
            record_warnings.append("статус не указан")
        elif not known:
            record_warnings.append(f"статус не распознан: «{status_raw}»")

        territory_raw = values.get("territory_raw")
        if reg_type == "madrid":
            territories, territory_warnings, territory_notes = parse_territories(territory_raw, book)
        else:
            territories, territory_warnings, territory_notes = national_territories(kind_raw, territory_raw, book)
        record_warnings.extend(territory_warnings)
        for territory in territories:
            if territory["status"] is None:
                territory["status"] = RECORD_TO_TERRITORY[status]

        product_raw = clean(values.get("product_raw"))
        product = mapping.get(product_key(product_raw), product_raw) if product_raw else NO_PRODUCT
        nice_raw = clean(values.get("nice_raw"))
        nice_classes = parse_classes(values.get("nice_raw"))
        if nice_raw and not nice_classes:
            record_warnings.append(f"классы МКТУ не распознаны: «{nice_raw[:60]}»")
        dates = {}
        for field in _DATE_FIELDS:
            dates[field] = parse_date(values.get(field))
            if dates[field] is None and clean(values.get(field)):
                record_warnings.append(f"дата не распознана ({field}): «{clean(values.get(field))}»")

        marks.append(
            {
                "id": f"tm-{row.sheet_row:04d}",
                "sheet_row": row.sheet_row,
                "row_no": clean(values.get("row_no")),
                "mark_text": mark_text,
                "mark_kind": mark_kind,
                "image": image,
                "image_note": image_note,
                "reg_type": reg_type,
                "reg_kind_raw": kind_raw,
                "application_no": application_no,
                "registration_no": registration_no,
                "number_note": "; ".join(note for note in (registration_note, application_note) if note) or None,
                "search_numbers": sorted({number_key(item) for item in (application_no, registration_no) if item}),
                "product": product,
                "product_raw": product_raw,
                "purpose": clean(values.get("purpose")),
                "nice_classes": nice_classes,
                "nice_raw": nice_raw,
                **dates,
                "status": status,
                "status_raw": status_raw,
                "territories": territories,
                "territory_raw": clean(territory_raw),
                "territory_notes": territory_notes,
                "attorney": clean(values.get("attorney")),
                "attorney_contacts": clean(values.get("attorney_contacts")),
                "warnings": record_warnings,
            }
        )
    return marks, blobs, warnings
