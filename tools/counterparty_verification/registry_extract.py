#!/usr/bin/env python3
"""Парсинг ответа DaData Suggest Party → карточка реестра + объективные red-flag флаги.

Только детерминированная нормализация и объективные флаги (статус, возраст,
минимальный капитал). Юридическая оценка совокупности — модель (risk-rules.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

_MIN_CAPITAL_OOO = 10000.0
_YOUNG_DAYS = 365
_BAD_STATUS = {"LIQUIDATED", "LIQUIDATING", "BANKRUPT", "REORGANIZING"}


class RegistryError(Exception):
    pass


def _epoch_ms_to_date(v):
    if v is None:
        return None
    try:
        return dt.datetime.fromtimestamp(int(v) / 1000, tz=dt.timezone.utc).date()
    except Exception:
        return None


def _to_number(v, cast):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def _red_flags(card: dict) -> list[dict]:
    flags = []
    st = card.get("status")
    if st in _BAD_STATUS:
        flags.append({"code": f"status_{st.lower()}", "severity": "red",
                      "detail": f"Статус ЮЛ: {st}"})
    age = card.get("age_days")
    if age is not None and age < _YOUNG_DAYS:
        flags.append({"code": "young_company", "severity": "yellow",
                      "detail": f"Компания создана недавно ({age} дн.)"})
    cap = card.get("capital")
    if cap is not None and cap <= _MIN_CAPITAL_OOO:
        flags.append({"code": "min_capital", "severity": "yellow",
                      "detail": f"Уставный капитал минимальный ({cap:.0f} руб.)"})
    return flags


def extract(response: dict, *, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    if not isinstance(response, dict):
        raise RegistryError("ответ DaData должен быть dict")
    suggestions = response.get("suggestions")
    if suggestions is None:
        return {"status": "unavailable", "markers": ["[DADATA НЕДОСТУПНА]"], "card": None, "flags": []}
    if not suggestions:
        return {"status": "not_found", "markers": ["[DADATA НЕ НАЙДЕНО]"], "card": None, "flags": []}

    first = suggestions[0]
    if not isinstance(first, dict):
        raise RegistryError("некорректный элемент suggestions[0]")
    data = first.get("data", {}) or {}
    name = data.get("name", {}) or {}
    state = data.get("state", {}) or {}
    address = data.get("address", {}) or {}
    mgmt = data.get("management", {}) or {}
    opf = data.get("opf", {}) or {}
    okved_meta = data.get("okveds") or []
    reg_date = _epoch_ms_to_date(state.get("registration_date"))
    cap_raw = data.get("capital") or {}

    card = {
        "full_name": name.get("full_with_opf"),
        "short_name": name.get("short_with_opf"),
        "inn": data.get("inn"),
        "kpp": data.get("kpp"),
        "ogrn": data.get("ogrn"),
        "opf": opf.get("full") or opf.get("short"),
        "status": state.get("status"),
        "registration_date": reg_date.isoformat() if reg_date else None,
        "age_days": (today - reg_date).days if reg_date else None,
        "address": address.get("unrestricted_value") or address.get("value"),
        "management_name": mgmt.get("name"),
        "management_post": mgmt.get("post"),
        "capital": _to_number(cap_raw.get("value"), float) if isinstance(cap_raw, dict) else None,
        "okved": data.get("okved"),
        "okved_count": len(okved_meta) if okved_meta else None,
        "branch_count": _to_number(data.get("branch_count"), int),
        "msp_category": (data.get("sme") or {}).get("category") if isinstance(data.get("sme"), dict) else None,
    }
    return {"status": "found", "markers": [], "card": card, "flags": _red_flags(card)}


def selftest() -> int:
    ok = 0
    today = dt.date(2026, 8, 28)

    def resp(status, reg_date, capital):
        ms = int(dt.datetime.combine(reg_date, dt.time(), tzinfo=dt.timezone.utc).timestamp() * 1000)
        return {"suggestions": [{"data": {
            "name": {"full_with_opf": 'Общество с ограниченной ответственностью "Ромашка"',
                     "short_with_opf": 'ООО "Ромашка"'},
            "inn": "7700000000", "kpp": "770001001", "ogrn": "1147700000000",
            "opf": {"full": "Общество с ограниченной ответственностью", "short": "ООО"},
            "state": {"status": status, "registration_date": ms},
            "address": {"unrestricted_value": "г. Москва, ул. Тестовая, д. 1"},
            "management": {"name": "Иванов Иван Иванович", "post": "Генеральный директор"},
            "capital": {"value": capital},
        }}]}

    r = extract(resp("ACTIVE", dt.date(2015, 1, 1), 5_000_000), today=today)
    assert r["status"] == "found" and r["card"]["inn"] == "7700000000"
    assert r["flags"] == [], r["flags"]                       # ACTIVE, старая, большой капитал
    assert r["card"]["registration_date"] == "2015-01-01", r["card"]["registration_date"]
    assert r["card"]["age_days"] == (dt.date(2026, 8, 28) - dt.date(2015, 1, 1)).days
    assert r["card"]["short_name"] == 'ООО "Ромашка"'
    assert r["card"]["full_name"].startswith("Общество")
    assert r["card"]["ogrn"] == "1147700000000"
    assert r["card"]["kpp"] == "770001001"
    assert r["card"]["address"] == "г. Москва, ул. Тестовая, д. 1"
    assert r["card"]["management_name"] == "Иванов Иван Иванович"
    assert r["card"]["management_post"] == "Генеральный директор"
    assert r["card"]["capital"] == 5000000.0
    ok += 1

    r = extract(resp("LIQUIDATED", dt.date(2015, 1, 1), 5_000_000), today=today)
    assert any(f["code"] == "status_liquidated" and f["severity"] == "red" for f in r["flags"])
    ok += 1

    r = extract(resp("ACTIVE", dt.date(2026, 6, 1), "10000"), today=today)
    codes = {f["code"] for f in r["flags"]}
    assert "young_company" in codes and "min_capital" in codes, codes
    assert r["card"]["capital"] == 10000.0, r["card"]["capital"]
    ok += 1

    assert extract({"suggestions": []})["status"] == "not_found"
    assert extract({})["status"] == "unavailable"
    ok += 1
    try:
        extract("нет")
        raise AssertionError("не-dict должен падать")
    except RegistryError:
        ok += 1
    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--today")
    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    with open(args.infile, encoding="utf-8") as fh:
        response = json.load(fh)
    today = dt.date.fromisoformat(args.today) if args.today else None
    print(json.dumps(extract(response, today=today), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    try:
        return run(sys.argv[1:])
    except RegistryError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
