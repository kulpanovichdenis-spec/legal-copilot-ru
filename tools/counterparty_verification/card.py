#!/usr/bin/env python3
"""Машиночитаемая карточка проверки контрагента (единый информационный слой дела).

Детерминированная валидация и сериализация `card.json`: единый машиночитаемый
слой, куда сводятся извлечённые из документов и источников сведения. Юридическое
суждение — в SKILL.md/references; здесь только проверка обязательных полей и запись.

Схема (минимальный контракт):
- обязательные верхнеуровневые ключи: schema, check_date, jurisdiction, identity, verdict;
- identity: наименование (full_name|short_name|name) И хотя бы один идентификатор
  (inn|ogrn|reg_number);
- verdict: строка из {green,yellow,red} ЛИБО объект с полем level из того же набора.
"""
from __future__ import annotations

import argparse
import json
import sys

REQUIRED_TOP = ("schema", "check_date", "jurisdiction", "identity", "verdict")
VERDICT_LEVELS = {"green", "yellow", "red"}


class CardError(Exception):
    pass


def _verdict_level(verdict) -> str | None:
    if isinstance(verdict, str):
        return verdict
    if isinstance(verdict, dict):
        return verdict.get("level")
    return None


def validate(data: dict) -> list[str]:
    """Вернуть список проблем карточки (пустой список = валидна)."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["карточка должна быть объектом (dict)"]
    for k in REQUIRED_TOP:
        if not data.get(k):
            problems.append(f"нет обязательного поля: {k}")
    ident = data.get("identity")
    if isinstance(ident, dict):
        if not (ident.get("full_name") or ident.get("short_name") or ident.get("name")):
            problems.append("identity: нет наименования (full_name|short_name|name)")
        if not (ident.get("inn") or ident.get("ogrn") or ident.get("reg_number")):
            problems.append("identity: нет идентификатора (inn|ogrn|reg_number)")
    elif "identity" in data:
        problems.append("identity должно быть объектом (dict)")
    if "verdict" in data:
        lvl = _verdict_level(data.get("verdict"))
        if lvl not in VERDICT_LEVELS:
            problems.append(f"verdict.level должен быть одним из {sorted(VERDICT_LEVELS)}, дано: {lvl!r}")
    return problems


def build_card(data: dict, out_path: str) -> str:
    problems = validate(data)
    if problems:
        raise CardError("карточка невалидна: " + "; ".join(problems))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return out_path


def selftest() -> int:
    import tempfile
    from pathlib import Path
    ok = 0
    valid = {
        "schema": "counterparty-verification/card@1",
        "check_date": "2026-09-07",
        "jurisdiction": "RU",
        "identity": {"full_name": 'ООО "Ромашка"', "inn": "7700000000", "ogrn": "1147700000000"},
        "verdict": {"level": "yellow", "risk": "low"},
    }
    assert validate(valid) == [], validate(valid)
    ok += 1

    with tempfile.TemporaryDirectory() as td:
        out = str(Path(td) / "card.json")
        build_card(valid, out)
        back = json.loads(Path(out).read_text(encoding="utf-8"))
        assert back == valid, "round-trip карточки не совпал"
        ok += 1

        # verdict как строка тоже допустим
        v2 = dict(valid); v2["verdict"] = "green"
        assert validate(v2) == []
        ok += 1

        for bad, needle in [
            ({k: v for k, v in valid.items() if k != "verdict"}, "verdict"),
            ({**valid, "verdict": {"level": "bad"}}, "verdict.level"),
            ({**valid, "identity": {"full_name": "X"}}, "идентификатор"),
            ({**valid, "identity": {"inn": "7700000000"}}, "наименовани"),
        ]:
            try:
                build_card(bad, str(Path(td) / "x.json"))
                raise AssertionError(f"ожидалась CardError ({needle})")
            except CardError as e:
                assert needle in str(e), str(e)
                ok += 1
    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", required=True)
    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    with open(args.infile, encoding="utf-8") as fh:
        data = json.load(fh)
    print(build_card(data, args.out))
    return 0


def main() -> int:
    try:
        return run(sys.argv[1:])
    except CardError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
