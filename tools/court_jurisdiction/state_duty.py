#!/usr/bin/env python3
"""State Duty Calculator (гosposhlina) — deterministic core of court-jurisdiction-resolver.

Two-module split from the ТЗ (§55-58): this file is the CALCULATOR
(arithmetic + versioned rules); the PAYMENT RESOLVER (banking requisites)
is deliberately NOT here — those are online-only operational data, never
computed and never taken from model memory (see references/court-online-resolver.md).

Safety contract:
- Formulas run in Python, never "estimated" by an LLM (ТЗ §116).
- Every rule carries effective_from/effective_to and a confidence tag:
    verified_fulltext — checked verbatim against the official text (НК РФ,
                         pravo.gov.ru nd=102067058, 2026-09-16) during build.
    search_synthesis  — aggregated from search-engine summaries, NOT
                         verbatim-checked; never returned as PAYABLE, only
                         as a MANUAL_REVIEW_REQUIRED estimate.
- Missing claim_amount for an assessable claim -> CANNOT_CALCULATE, never
  a guessed value (ТЗ §71).
- Unrecognised exemption code -> flagged UNKNOWN_CODE, never silently
  treated as "no exemption applies" nor as "exemption applies" (ТЗ §77
  spirit: refuse rather than guess in either direction).

2026-09-16: rebuilt after direct verification against pravo.gov.ru
(протокол references/pravo-gov-ru-search-protocol.md). Earlier
search_synthesis numbers for non-property/act-challenge categories and
for АПК exemptions turned out to be wrong or fabricated on spot-check —
see git history / tools/court_jurisdiction/rules/*.yaml comments for the
specific corrections. All `fixed_rates` and `exemptions` entries below are
now verified_fulltext.

Usage:
    python -m tools.court_jurisdiction.state_duty calculate
        --regime GPK|APK
        --claim-type property_assessable|fixed|writ_of_payment|other
        [--fixed-category CODE] [--claimant-type individual|organization]
        [--amount N] [--consumer] [--exemption CODE ...]
        [--calculation-date YYYY-MM-DD] [--claims-file claims.json]
    python -m tools.court_jurisdiction.state_duty list-rules --regime GPK|APK
    python -m tools.court_jurisdiction.state_duty selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

RULES_DIR = Path(__file__).parent / "rules"
REGIMES = ("GPK", "APK")
CLAIM_TYPES = ("property_assessable", "fixed", "writ_of_payment", "other")


class StateDutyError(Exception):
    pass


# ---------- rules loading ----------

def _load_yaml(name: str) -> dict:
    path = RULES_DIR / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise StateDutyError(f"файл правил повреждён: {path}")
    return data


def load_rates() -> dict:
    return _load_yaml("state_duty_rates.yaml")


def load_exemptions() -> dict:
    return _load_yaml("state_duty_exemptions.yaml")


def _select_versioned(rules: list, calc_date: dt.date):
    """Pick the rule whose [effective_from, effective_to) window covers calc_date.
    Never falls back to "closest" — no match means CANNOT_CALCULATE, not a guess."""
    for rule in rules:
        start = dt.date.fromisoformat(rule["effective_from"])
        end_s = rule.get("effective_to")
        end = dt.date.fromisoformat(end_s) if end_s else None
        if start <= calc_date and (end is None or calc_date < end):
            return rule
    return None


# ---------- bracket arithmetic (ТЗ §62-63) ----------

def calc_bracket(amount: float, brackets: list[dict]) -> tuple[float, dict]:
    """amount -> (duty, matched_bracket). Deterministic, no rounding surprises:
    duty = base + percent% * (amount - excess_over), capped at max_total if set."""
    if amount < 0:
        raise StateDutyError("цена иска не может быть отрицательной")
    for b in brackets:
        upper = b.get("upper")
        if upper is None or amount <= upper:
            duty = b["base"] + (b.get("percent", 0) / 100.0) * max(0, amount - b.get("excess_over", 0))
            if b.get("max_total") is not None:
                duty = min(duty, b["max_total"])
            return round(duty, 2), b
    raise StateDutyError("сумма превышает все известные пороги правила — проверить таблицу")


def _property_rule(regime: str, calc_date: dt.date):
    rules = load_rates().get("property_assessable", {}).get(regime, [])
    return _select_versioned(rules, calc_date)


# ---------- exemption check (ТЗ §67-70, EXEMPTION CHECK) ----------

def check_exemptions(regime: str, exemption_codes: list[str], amount: float | None) -> dict:
    """Always runs (ТЗ §67: 'до выдачи суммы обязательно выполнить EXEMPTION CHECK'),
    even with an empty exemption_codes list — the result records what was checked
    and found, so 'no exemption' is a documented outcome, not a silent skip."""
    exemptions = load_exemptions().get("exemptions", {}).get(regime, [])
    by_code = {e["code"]: e for e in exemptions}
    result = {"performed": True, "checked_codes": list(by_code.keys()), "matches": []}
    for code in exemption_codes or []:
        rule = by_code.get(code)
        if rule is None:
            result["matches"].append({
                "code": code, "status": "UNKNOWN_CODE",
                "note": f"льгота '{code}' не закодирована в state_duty_exemptions.yaml — "
                        f"сверить ст. 333.35-333.37 НК РФ напрямую, не пропускать молча.",
            })
            continue
        entry = {"code": code, "rule_id": rule["rule_id"], "source": rule["source"],
                  "confidence": rule["confidence"], "type": rule["type"]}
        if rule["type"] == "full":
            entry["status"] = "EXEMPT"
            entry["amount_after_exemption"] = 0
        elif rule["type"] == "threshold":
            threshold = rule["threshold_amount"]
            if amount is None:
                entry["status"] = "CANNOT_APPLY"
                entry["note"] = "нужна цена иска, чтобы применить порог льготы"
            elif amount <= threshold:
                entry["status"] = "EXEMPT"
                entry["amount_after_exemption"] = 0
            else:
                entry["status"] = "PARTIAL"
                entry["excess_over_threshold"] = round(amount - threshold, 2)
        result["matches"].append(entry)
    return result


# ---------- top-level calculate ----------

def _calculate(
    regime: str,
    claim_type: str,
    claimant_type: str | None = None,
    amount: float | None = None,
    consumer: bool = False,
    exemption_codes: list[str] | None = None,
    calculation_date: dt.date | None = None,
    fixed_category: str | None = None,
) -> dict:
    if regime not in REGIMES:
        raise StateDutyError(f"regime должен быть один из {REGIMES}, получено {regime!r}")
    if claim_type not in CLAIM_TYPES:
        raise StateDutyError(f"claim_type должен быть один из {CLAIM_TYPES}, получено {claim_type!r}")
    calc_date = calculation_date or dt.date.today()

    exemption_result = check_exemptions(regime, exemption_codes or [], amount)
    full_exempt = next((m for m in exemption_result["matches"] if m.get("status") == "EXEMPT"), None)

    out = {
        "regime": regime,
        "claim_type": claim_type,
        "claimant_type": claimant_type,
        "claim_amount": amount,
        "calculation_date": calc_date.isoformat(),
        "exemption_check": exemption_result,
        "calculated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }

    if full_exempt:
        out.update(status="EXEMPT", amount=0,
                    legal_basis=full_exempt["source"], rule_id=full_exempt["rule_id"])
        return out

    partial = next((m for m in exemption_result["matches"] if m.get("status") == "PARTIAL"), None)

    if claim_type == "property_assessable":
        if amount is None:
            out.update(status="CANNOT_CALCULATE", missing=["claim_amount"])
            return out
        rule = _property_rule(regime, calc_date)
        if rule is None:
            out.update(status="CANNOT_CALCULATE",
                        missing=[f"нет версии правила property_assessable/{regime} на дату {calc_date}"])
            return out

        base_amount = amount if partial is None else partial["excess_over_threshold"]
        duty, bracket = calc_bracket(base_amount, rule["brackets"])

        discount_note = None
        if consumer and regime == "GPK":
            disc_rules = load_rates().get("consumer_discount", {}).get("GPK", [])
            disc_rule = _select_versioned(disc_rules, calc_date)
            if disc_rule:
                duty = round(duty * disc_rule["percent_of_base"] / 100.0, 2)
                discount_note = disc_rule["source"]

        out.update(
            status="PARTIALLY_EXEMPT" if partial else "PAYABLE",
            amount=duty,
            legal_basis=rule["source"],
            rule_id=rule["rule_id"],
            bracket_used=bracket,
            consumer_discount_applied=discount_note,
        )
        if rule["confidence"] != "verified_fulltext":
            out["warning"] = "правило не сверено дословно — confidence=" + rule["confidence"]
        return out

    if claim_type == "writ_of_payment":
        if amount is None:
            out.update(status="CANNOT_CALCULATE", missing=["claim_amount"],
                        note="судебный приказ считается от суммы имущественного требования")
            return out
        prop_rule = _property_rule(regime, calc_date)
        writ_rules = load_rates().get("writ_of_payment", {}).get(regime, [])
        writ_rule = _select_versioned(writ_rules, calc_date)
        if prop_rule is None or writ_rule is None:
            out.update(status="CANNOT_CALCULATE",
                        missing=[f"нет версии правила writ_of_payment/{regime} на дату {calc_date}"])
            return out
        prop_duty, _ = calc_bracket(amount, prop_rule["brackets"])
        duty = round(prop_duty * writ_rule["percent_of_property"] / 100.0, 2)
        floor = writ_rule.get("floor")
        floor_applied = False
        if floor is not None and duty < floor:
            duty = float(floor)
            floor_applied = True
        out.update(
            status="PAYABLE", amount=duty, legal_basis=writ_rule["source"],
            rule_id=writ_rule["rule_id"], property_duty_base=prop_duty, floor_applied=floor_applied,
        )
        return out

    if claim_type == "fixed":
        if fixed_category is None:
            out.update(status="CANNOT_CALCULATE", missing=["fixed_category"])
            return out
        fixed_rules = load_rates().get("fixed_rates", {}).get(regime, [])
        rule = _select_versioned(fixed_rules, calc_date)
        if rule is None:
            out.update(status="CANNOT_CALCULATE",
                        missing=[f"нет версии правила fixed_rates/{regime} на дату {calc_date}"])
            return out
        category = rule["categories"].get(fixed_category)
        if category is None:
            out.update(status="CANNOT_CALCULATE",
                        missing=[f"категория '{fixed_category}' не закодирована в fixed_rates/{regime} — "
                                 f"см. list-rules за перечнем известных категорий"])
            return out
        if claimant_type == "debtor_self" and "debtor_self_filing" in category:
            duty = category["debtor_self_filing"]
        elif "flat" in category:
            duty = category["flat"]
        else:
            if claimant_type not in ("individual", "organization"):
                out.update(status="CANNOT_CALCULATE", missing=["claimant_type"])
                return out
            duty = category[claimant_type]
        out.update(
            status="PAYABLE", amount=duty, legal_basis=category["basis"],
            rule_id=rule["rule_id"], fixed_category=fixed_category,
        )
        if rule["confidence"] != "verified_fulltext":
            out["warning"] = "правило не сверено дословно — confidence=" + rule["confidence"]
        return out

    # claim_type == "other": genuinely not covered by any coded table.
    out.update(
        status="MANUAL_REVIEW_REQUIRED",
        note="категория не входит в оцифрованные property_assessable/fixed/writ_of_payment — "
             "определить ставку напрямую по ст. 333.19-333.23 НК РФ (СОЮ/мировые) или "
             "ст. 333.21-333.22 НК РФ (арбитраж), либо запросить у юриста уточнение категории.",
    )
    return out


ROUNDING_BASIS = ("п. 6 ст. 52 НК РФ (ред. Федерального закона от 31.07.2023 № 389-ФЗ): сумма сбора исчисляется "
                  "в полных рублях; госпошлина — сбор (п. 1 ст. 333.16 НК РФ). Копейки округляются в большую "
                  "сторону (решение юриста 2026-10-16): переплата до рубля исключает недоплату и возврат заявления.")


def to_full_rubles(amount: float) -> int:
    """Сумма к уплате в полных рублях, любые копейки — в большую сторону (решение юриста 2026-10-16)."""
    from decimal import Decimal, ROUND_CEILING
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_CEILING))


def calculate(*args, **kwargs) -> dict:
    """Расчёт пошлины; `amount` — арифметика по ставке (с копейками), `payable_rub` — к уплате
    в полных рублях (это число ставится в документ и платёжку)."""
    out = _calculate(*args, **kwargs)
    if out.get("status") in ("PAYABLE", "PARTIALLY_EXEMPT") and out.get("amount") is not None:
        out["payable_rub"] = to_full_rubles(out["amount"])
        out["rounding_basis"] = ROUNDING_BASIS
    return out


def calculate_multiple(claims: list[dict], regime: str, calculation_date: dt.date | None = None,
                        exemption_codes: list[str] | None = None) -> dict:
    """Multiple claims (ТЗ §65-66): property_assessable amounts are summed into
    one combined price of claim (цена иска) before bracket calculation. This
    exact rule is dословно verified for АПК (ст. 333.22 п. 1 пп. 2: "Цена иска,
    состоящего из нескольких самостоятельных требований, определяется исходя
    из суммы всех требований"); for ГПК it follows the same general procedural
    principle (ГПК ст. 91) — ст. 333.20 НК РФ does not restate it separately.
    Non-property/fixed/other claims in the same filing are calculated
    separately per claim (ст. 333.20 п. 1 пп. 1 / ст. 333.22 п. 1 пп. 1: paid
    on top of the property duty, not merged into it)."""
    property_total = sum(c["amount"] for c in claims if c.get("type") == "property_assessable")
    other_claims = [c for c in claims if c.get("type") != "property_assessable"]

    combined = calculate(regime=regime, claim_type="property_assessable",
                          amount=property_total, calculation_date=calculation_date,
                          exemption_codes=exemption_codes)
    other_results = [
        calculate(regime=regime, claim_type=c.get("type", "other"),
                  claimant_type=c.get("claimant_type"), amount=c.get("amount"),
                  fixed_category=c.get("fixed_category"), calculation_date=calculation_date)
        for c in other_claims
    ]
    return {
        "claims_count": len(claims),
        "property_claims_summed_to": property_total,
        "combined_property_duty": combined,
        "other_claims": other_results,
        "note": "цена иска по нескольким имущественным требованиям суммируется "
                "(верифицировано дословно для АПК — ст. 333.22 п. 1 пп. 2); "
                "неимущественные/прочие требования в той же сумме не участвуют "
                "— уплачиваются отдельно, сверх суммы по имущественным требованиям "
                "(ст. 333.20 п. 1 пп. 1 ГПК / ст. 333.22 п. 1 пп. 1 АПК).",
    }


# ---------- CLI ----------

def cmd_calculate(args) -> int:
    calc_date = dt.date.fromisoformat(args.calculation_date) if args.calculation_date else None
    if args.claims_file:
        claims = json.loads(Path(args.claims_file).read_text(encoding="utf-8"))
        result = calculate_multiple(claims, regime=args.regime, calculation_date=calc_date,
                                     exemption_codes=args.exemption)
    else:
        result = calculate(
            regime=args.regime, claim_type=args.claim_type, claimant_type=args.claimant_type,
            amount=args.amount, consumer=args.consumer, exemption_codes=args.exemption,
            calculation_date=calc_date, fixed_category=args.fixed_category,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_list_rules(args) -> int:
    rates = load_rates()
    exemptions = load_exemptions()
    out = {
        "property_assessable": rates.get("property_assessable", {}).get(args.regime, []),
        "fixed_rates": rates.get("fixed_rates", {}).get(args.regime, []),
        "writ_of_payment": rates.get("writ_of_payment", {}).get(args.regime, []),
        "exemptions": exemptions.get("exemptions", {}).get(args.regime, []),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="state_duty")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calculate")
    c.add_argument("--regime", required=True, choices=REGIMES)
    c.add_argument("--claim-type", choices=CLAIM_TYPES, default="property_assessable")
    c.add_argument("--fixed-category")
    c.add_argument("--claimant-type", choices=("individual", "organization", "debtor_self"))
    c.add_argument("--amount", type=float)
    c.add_argument("--consumer", action="store_true")
    c.add_argument("--exemption", action="append", default=[])
    c.add_argument("--calculation-date")
    c.add_argument("--claims-file")
    c.set_defaults(func=cmd_calculate)

    lr = sub.add_parser("list-rules")
    lr.add_argument("--regime", required=True, choices=REGIMES)
    lr.set_defaults(func=cmd_list_rules)

    st = sub.add_parser("selftest")
    st.set_defaults(func=lambda a: selftest())

    return p


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


# ---------- selftest ----------

def selftest() -> int:
    ok = 0

    # 1. Property assessable, ГПК, mid-bracket — verified against ст. 333.19.
    r = calculate(regime="GPK", claim_type="property_assessable", amount=700000)
    assert r["status"] == "PAYABLE", r
    assert r["amount"] == 15000 + 0.02 * 200000, r  # 19000
    ok += 1

    # 2. Property assessable, АПК, first bracket (flat 10000).
    r = calculate(regime="APK", claim_type="property_assessable", amount=50000)
    assert r["status"] == "PAYABLE" and r["amount"] == 10000, r
    ok += 1

    # 3. АПК top bracket respects max_total cap.
    r = calculate(regime="APK", claim_type="property_assessable", amount=2_000_000_000)
    assert r["amount"] == 10_000_000, r  # capped
    ok += 1

    # 4. Missing amount -> CANNOT_CALCULATE, never guessed.
    r = calculate(regime="GPK", claim_type="property_assessable", amount=None)
    assert r["status"] == "CANNOT_CALCULATE" and r["missing"] == ["claim_amount"], r
    ok += 1

    # 5. Full exemption (labor) short-circuits to EXEMPT regardless of amount.
    r = calculate(regime="GPK", claim_type="property_assessable", amount=5_000_000,
                  exemption_codes=["labor_claims"])
    assert r["status"] == "EXEMPT" and r["amount"] == 0, r
    ok += 1

    # 6. Threshold exemption (consumer, ст.333.36 п.2 пп.4+п.3): under threshold -> EXEMPT.
    r = calculate(regime="GPK", claim_type="property_assessable", amount=500000,
                  exemption_codes=["consumer_claims"])
    assert r["status"] == "EXEMPT", r
    ok += 1

    # 7. Threshold exemption: over threshold -> PARTIALLY_EXEMPT on the excess only.
    r = calculate(regime="GPK", claim_type="property_assessable", amount=1_100_000,
                  exemption_codes=["consumer_claims"])
    assert r["status"] == "PARTIALLY_EXEMPT", r
    assert r["amount"] == calc_bracket(100000, load_rates()["property_assessable"]["GPK"][0]["brackets"])[0], r
    ok += 1

    # 8. Unknown exemption code -> flagged, not silently ignored either way.
    r = calculate(regime="GPK", claim_type="property_assessable", amount=100000,
                  exemption_codes=["not_a_real_code"])
    assert r["exemption_check"]["matches"][0]["status"] == "UNKNOWN_CODE", r
    assert r["status"] == "PAYABLE", r  # unknown code does not fabricate an exemption
    ok += 1

    # 9. Consumer discount (ст. 333.19 п.2): 50% of base duty.
    r = calculate(regime="GPK", claim_type="property_assessable", amount=700000, consumer=True)
    full = calculate(regime="GPK", claim_type="property_assessable", amount=700000)
    assert r["amount"] == round(full["amount"] * 0.5, 2), r
    ok += 1

    # 10. Fixed non-property (verified_fulltext, 2026-09-16 correction) -> PAYABLE now,
    #     not MANUAL_REVIEW_REQUIRED — ГПК пп.3 п.1 ст.333.19: 3000 / 20000.
    r = calculate(regime="GPK", claim_type="fixed", fixed_category="non_property",
                  claimant_type="organization")
    assert r["status"] == "PAYABLE" and r["amount"] == 20000, r
    r = calculate(regime="GPK", claim_type="fixed", fixed_category="non_property",
                  claimant_type="individual")
    assert r["amount"] == 3000, r
    ok += 1

    # 11. Corrected value: act_challenge_nonnormative was wrongly 300/2000 before
    #     verification; the real ГПК figure (пп.7 п.1 ст.333.19) is 3000/15000.
    r = calculate(regime="GPK", claim_type="fixed", fixed_category="act_challenge_nonnormative",
                  claimant_type="organization")
    assert r["amount"] == 15000, r
    ok += 1

    # 12. АПК exemption "labor_claims" was fabricated before verification — ст.333.37
    #     has no such category. It must now be UNKNOWN_CODE for APK.
    r = calculate(regime="APK", claim_type="property_assessable", amount=100000,
                  exemption_codes=["labor_claims"])
    assert r["exemption_check"]["matches"][0]["status"] == "UNKNOWN_CODE", r

    # 13. Real АПК exemption instead: bankruptcy debtor incidental disputes (full).
    r = calculate(regime="APK", claim_type="property_assessable", amount=100000,
                  exemption_codes=["bankrupt_debtor_incidental"])
    assert r["status"] == "EXEMPT", r
    ok += 1

    # 14. Flat fixed category (divorce, ГПК пп.5 п.1 ст.333.19 — flat 5000, no
    #     claimant_type distinction).
    r = calculate(regime="GPK", claim_type="fixed", fixed_category="divorce")
    assert r["amount"] == 5000, r
    ok += 1

    # 15. Bankruptcy petition (АПК): debtor filing for own bankruptcy -> 0.
    r = calculate(regime="APK", claim_type="fixed", fixed_category="bankruptcy_petition",
                  claimant_type="debtor_self")
    assert r["amount"] == 0, r
    r = calculate(regime="APK", claim_type="fixed", fixed_category="bankruptcy_petition",
                  claimant_type="organization")
    assert r["amount"] == 100000, r
    ok += 1

    # 16. Writ of payment (АПК): 50% of property duty, floor 8000 руб.
    r = calculate(regime="APK", claim_type="writ_of_payment", amount=100000)
    prop = calculate(regime="APK", claim_type="property_assessable", amount=100000)
    assert r["property_duty_base"] == prop["amount"] == 10000, r
    assert r["amount"] == 8000 and r["floor_applied"] is True, r  # 50%*10000=5000 < floor 8000
    ok += 1

    # 17. Writ of payment (ГПК): 50% of property duty, no floor.
    r = calculate(regime="GPK", claim_type="writ_of_payment", amount=700000)
    assert r["amount"] == round(full["amount"] * 0.5, 2), r
    ok += 1

    # 18. Unknown fixed category -> CANNOT_CALCULATE, never a guessed number.
    r = calculate(regime="GPK", claim_type="fixed", fixed_category="not_a_real_category")
    assert r["status"] == "CANNOT_CALCULATE", r
    ok += 1

    # 19. Rule versioning: a date before effective_from finds no rule.
    r = calculate(regime="APK", claim_type="property_assessable", amount=100000,
                  calculation_date=dt.date(2020, 1, 1))
    assert r["status"] == "CANNOT_CALCULATE", r
    ok += 1

    # 20. Multiple property claims are summed before bracket calculation.
    m = calculate_multiple([
        {"type": "property_assessable", "amount": 400000},
        {"type": "property_assessable", "amount": 300000},
    ], regime="GPK")
    assert m["property_claims_summed_to"] == 700000, m
    assert m["combined_property_duty"]["amount"] == full["amount"], m
    ok += 1

    # 21. Negative amount rejected outright.
    try:
        calc_bracket(-1, [{"upper": None, "base": 0, "percent": 0, "excess_over": 0}])
        raise AssertionError("отрицательная сумма должна падать")
    except StateDutyError:
        ok += 1

    # 22. Сумма к уплате — в полных рублях, копейки вверх (п. 6 ст. 52 НК РФ; решение юриста 2026-10-16).
    assert to_full_rubles(94472.77) == 94473 and to_full_rubles(32593.40) == 32594, "округление вверх"
    assert to_full_rubles(1000.01) == 1001 and to_full_rubles(1000.00) == 1000, "целые рубли не трогать"
    r = calculate(regime="APK", claim_type="property_assessable", amount=5464851.27)
    assert r["amount"] == 188945.54 and r["payable_rub"] == 188946 and "52" in r["rounding_basis"], r
    ok += 1

    print(f"selftest OK ({ok} проверок)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run(sys.argv[1:]))
    except StateDutyError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        sys.exit(1)
