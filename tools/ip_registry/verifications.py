"""Сверки статусов знаков с ведомствами (verifications.yaml): перекрывают территории реестра по странам."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import yaml

from .normalize import TERRITORY_STATUS_LABELS, CountryBook, number_key

FILE_NAME = "verifications.yaml"


def _iso_date(value: Any, where: str) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            pass
    raise ValueError(f"verifications.yaml: {where}: ожидается дата ГГГГ-ММ-ДД, получено {value!r}")


def _text(item: dict, key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"verifications.yaml: {where}: поле {key} должно быть непустой строкой (в кавычках)")
    return value.strip()


def _country(code: Any, data: Any, where: str) -> tuple[str, dict]:
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2}", code):
        raise ValueError(f"verifications.yaml: {where}: код страны {code!r} должен быть строкой из двух "
                         "заглавных латинских букв в кавычках (NO без кавычек YAML читает как false)")
    if not isinstance(data, dict):
        raise ValueError(f"verifications.yaml: {where}, {code}: ожидается {{status: ..., since: ..., note: ...}}")
    status = data.get("status")
    if status not in TERRITORY_STATUS_LABELS:
        raise ValueError(f"verifications.yaml: {where}, {code}: статус {status!r} не из списка "
                         + ", ".join(TERRITORY_STATUS_LABELS))
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError(f"verifications.yaml: {where}, {code}: note должно быть строкой")
    since = data.get("since")
    return code, {"status": status, "note": note,
                  "since": _iso_date(since, f"{where}, {code}, since") if since is not None else None}


def load_verifications(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"verifications.yaml: не читается как YAML: {error}") from error
    if data is None:
        return []
    items = data.get("verifications") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("verifications.yaml: ожидается список verifications: [...]")
    result = []
    for index, item in enumerate(items, 1):
        where = f"запись {index}"
        if not isinstance(item, dict):
            raise ValueError(f"verifications.yaml: {where}: ожидается словарь")
        registration_no = _text(item, "registration_no", where)
        where = f"запись {index} (№ {registration_no})"
        countries = item.get("countries")
        if not isinstance(countries, dict) or not countries:
            raise ValueError(f"verifications.yaml: {where}: countries должен быть непустым словарём")
        reference = item.get("reference")
        if reference is not None and not isinstance(reference, str):
            raise ValueError(f"verifications.yaml: {where}: reference должно быть строкой")
        result.append({
            "registration_no": registration_no,
            "source": _text(item, "source", where),
            "checked": _iso_date(item.get("checked"), f"{where}, checked"),
            "reference": reference,
            "countries": dict(_country(code, value, where) for code, value in countries.items()),
        })
    return result


def apply_verifications(marks: list[dict], verifications: list[dict], book: CountryBook) -> list[str]:
    warnings: list[str] = []
    for item in verifications:
        key = number_key(item["registration_no"])
        matched = [m for m in marks if key and number_key(m.get("registration_no")) == key]
        if not matched:
            warnings.append(f"сверка: знак № {item['registration_no']} не найден в реестре")
            continue
        territories = []
        for code, data in item["countries"].items():
            country = book.by_iso(code)
            if country is None:
                warnings.append(f"сверка: знак № {item['registration_no']}: код страны {code} не в справочнике")
            territories.append({"code": code, "name": country.name if country else code,
                                "status": data["status"], "basis": None, "note": data["note"],
                                "since": data["since"]})
        for mark in matched:
            mark["registry_territories"] = mark["territories"]
            mark["territories"] = [dict(t) for t in territories]
            mark["verification"] = {"source": item["source"], "checked": item["checked"],
                                    "reference": item["reference"]}
    return warnings
