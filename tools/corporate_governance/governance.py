#!/usr/bin/env python3
"""Корпоративный слой (Entity Governance): профиль компании, правила из устава,
источники, аудит. Детерминированное ядро класса A: хранит записи, проверяет
схему и provenance, считает проекции. Правовых выводов не делает: квалификацию
по закону, классификацию пунктов и оценку конфликтов выполняет агент, решение
принимает юрист (references/corporate-governance-method.md).

Данные компании: profile/knowledge/corporate/entities/<slug>/
(sources.yaml, rules.yaml, profile.yaml, audit.jsonl, _work/).

Использование:
    python tools/corporate_governance/governance.py init-entity --slug pilot-llc --name "..."
    python tools/corporate_governance/governance.py register-source --slug pilot-llc --kind charter ...
    python tools/corporate_governance/governance.py add-rule --slug pilot-llc --topic notice ...
    python tools/corporate_governance/governance.py confirm --slug pilot-llc --ids R-001 --by "Иванов И. И."
    python tools/corporate_governance/governance.py report --slug pilot-llc --view all
    python tools/corporate_governance/governance.py selftest
Полный список команд: governance.py --help
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_cmd_entity  # noqa: E402
import gov_cmd_rules  # noqa: E402
import gov_cmd_checks  # noqa: E402
import gov_cmd_confirm  # noqa: E402
import gov_cmd_report  # noqa: E402
import gov_cmd_cards  # noqa: E402
import gov_cmd_egrul  # noqa: E402
import gov_cmd_group  # noqa: E402
import gov_cmd_competence  # noqa: E402
import gov_store  # noqa: E402

COMMAND_MODULES = (gov_cmd_entity, gov_cmd_rules, gov_cmd_checks, gov_cmd_confirm,
                   gov_cmd_report, gov_cmd_cards, gov_cmd_egrul, gov_cmd_group, gov_cmd_competence)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="governance.py",
        description="Корпоративный слой: профиль компании, правила из устава, аудит")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for module in COMMAND_MODULES:
        module.register(sub)
    sub.add_parser("selftest", help="самопроверка на временной папке").set_defaults(func=cmd_selftest)
    return parser


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return int(_dispatch(args) or 0)


def _dispatch(args):
    """Единственное место, где команда с компанией берёт блокировку на весь свой цикл.

    Команда с --slug блокирует компанию, если она явно не помечена no_lock=True в своём register()
    (чтение, init-entity берёт блокировку сама, render-pages не трогает yaml). Так новая команда
    по умолчанию защищена, а не «забыта».
    """
    if getattr(args, "slug", None) is None or getattr(args, "no_lock", False):
        return args.func(args)
    with gov_store.entity_from_args(args).locked():
        return args.func(args)


def cmd_selftest(_args) -> int:
    """Сценарий: завести → источник → правило → отказ confirm без freshness → confirm."""
    with tempfile.TemporaryDirectory() as tmp:
        base = ["--entities-dir", str(Path(tmp) / "corporate" / "entities"), "--slug", "selftest-llc"]
        steps = [
            ["init-entity", "--name", "Самопроверка"],
            ["register-source", "--kind", "charter", "--title", "Устав", "--file",
             "originals/x.pdf", "--pages", "3"],
            ["add-rule", "--topic", "notice", "--subject", "срок уведомления", "--value", "за 30 дней",
             "--classification", "CHARTER_OVERRIDE", "--law-card", "llc/notice",
             "--law-article", "ст. 36, п. 1", "--source-id", "S-001",
             "--page", "2", "--clause", "8.4", "--quote", "не позднее чем за 30 дней"],
        ]
        for step in steps:
            if run(step + base) != 0:
                print("SELFTEST FAIL: шаг", step[0])
                return 1
        if run(["confirm", "--ids", "R-001", "--by", "Иванов И. И."] + base) == 0:
            print("SELFTEST FAIL: confirm без freshness должен быть отказом")
            return 1
        follow = [
            ["set-freshness", "--rule-id", "R-001", "--status", "verified", "--edition", "ред. selftest"],
            ["confirm", "--ids", "R-001", "--by", "Иванов И. И."],
            ["validate"],
        ]
        for step in follow:
            if run(step + base) != 0:
                print("SELFTEST FAIL: шаг", step[0])
                return 1
    print("SELFTEST OK: сценарий завести → правило → freshness → confirm отработал")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except gov_store.GovError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
