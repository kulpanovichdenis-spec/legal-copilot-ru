"""Structured challenge findings. The function does not rewrite the budget."""
from __future__ import annotations

from pathlib import Path

from lb_local import load

annual_amount = load("calculate").annual_amount
_model = load("model")
D = _model.D
Finding = _model.Finding


def _is_material(line: dict, state: dict) -> bool:
    if line.get("material") is True:
        return True
    threshold = state.get("materiality_threshold")
    if threshold is None:
        return False
    amount = line.get("annual_amount")
    if amount in (None, ""):
        return False
    return D(amount) >= D(threshold)


def _invoice_key(value) -> str:
    return str(value).strip().casefold()


def challenge(state: dict, context: dict | None = None) -> list[Finding]:
    if context and state.get("materiality_threshold") is None and context.get("materiality_threshold") is not None:
        state = dict(state)
        state["materiality_threshold"] = context["materiality_threshold"]
    findings: list[Finding] = []
    number = 1

    def add(rule: str, refs: list[str], finding: str, why: str, action: str, severity: str, blocking: bool):
        nonlocal number
        findings.append(
            Finding(
                id=f"CH-{number:03d}",
                severity=severity,
                rule=rule,
                affected_refs=tuple(refs),
                finding=finding,
                why_it_matters=why,
                recommended_action=action,
                blocking=blocking,
            )
        )
        number += 1

    for line in state.get("lines") or []:
        monthly = line.get("monthly_amounts") or {}
        if monthly and line.get("annual_amount") not in (None, ""):
            if D(line["annual_amount"]) != annual_amount(monthly):
                add(
                    "annual_mismatch",
                    [line["id"]],
                    "Годовая сумма не равна сумме месяцев.",
                    "Итог и помесячный график разойдутся в книге и в HTML.",
                    "Пересчитать годовую сумму скриптом, не править её руками.",
                    "critical",
                    True,
                )
        if line.get("annual_amount") in (None, "") and not (line.get("monthly_amounts") or {}):
            add(
                "missing_amount",
                [line["id"]],
                "У строки нет суммы.",
                "Итог без этой строки выглядит полным.",
                "Указать сумму, диапазон или открытый вопрос. Пустое не заменять нулём.",
                "high",
                True,
            )
        refs = list(line.get("source_refs") or []) + list(line.get("assumption_refs") or [])
        if _is_material(line, state) and not refs:
            add(
                "missing_provenance",
                [line["id"]],
                "Существенная строка без источника и без допущения.",
                "Цифру нельзя защитить.",
                "Привязать source или записать assumption.",
                "high",
                True,
            )

    actual_ids = {_invoice_key(item.get("invoice_id")) for item in state.get("actuals") or [] if str(item.get("invoice_id") or "").strip()}
    accrual_ids = {_invoice_key(item.get("invoice_id")) for item in state.get("accruals") or [] if str(item.get("invoice_id") or "").strip()}
    for invoice_id in sorted(actual_ids & accrual_ids):
        add(
            "accrual_double_count",
            [invoice_id],
            "Один и тот же счёт попал и в факт, и в начисление.",
            "Расход будет посчитан дважды.",
            "Оставить счёт только в одном слое.",
            "critical",
            True,
        )

    for row in state.get("history") or []:
        if row.get("tag") == "one_off" and row.get("closed") and row.get("carried_to_line") and not row.get("carry_tag"):
            add(
                "one_off_carried",
                [str(row.get("id"))],
                "Закрытый разовый расход перенесён в следующий период без тега.",
                "База следующего года раздувается прошлым эпизодом.",
                "Убрать перенос или явно пометить, почему класс риска повторяется.",
                "high",
                False,
            )

    for item in state.get("allocations") or []:
        if item.get("presented_as_saving"):
            add(
                "allocation_as_saving",
                [str(item.get("id"))],
                "Перенос на другой центр затрат показан как экономия.",
                "Для компании расход не исчез.",
                "Показать перенос отдельно от сокращения.",
                "high",
                True,
            )

    transfer = state.get("workload_transfer")
    headcount = state.get("headcount_change")
    external = state.get("external_spend_change")
    if transfer == "outside" and headcount not in (None, "") and external not in (None, ""):
        if D(headcount) < 0 and D(external) == 0:
            add(
                "headcount_external_inconsistent",
                ["headcount", "external_spend"],
                "Штат сокращён, внешние расходы не изменены, хотя работу перенесли наружу.",
                "Сценарий занижает стоимость той же работы.",
                "Изменить внешние расходы или снять допущение о переносе.",
                "high",
                True,
            )
    return findings
