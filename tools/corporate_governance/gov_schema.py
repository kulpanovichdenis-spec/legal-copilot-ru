# -*- coding: utf-8 -*-
"""Схемы и валидаторы корпоративного слоя: единый источник enum и проверок.

Ничего не квалифицирует юридически: только форма записей, provenance и
взаимные ссылки (ТЗ Corporate Governance, §5, §8.3, §10, §24).
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

SOURCE_KINDS = (
    "charter", "sole_member_decision", "shareholder_decision", "board_minutes",
    "internal_rule", "corporate_agreement", "founding_agreement", "egrul_extract", "poa", "other",
)
SOURCE_STATUSES = ("current", "superseded", "unverified")
LAYERS = ("charter", "internal", "corporate_agreement")
TOPICS = (
    "competence", "convening", "notice", "agenda", "quorum", "threshold",
    "voting_procedure", "confirmation", "sole_member", "executive_body",
    "transactions", "capital_shares", "profit", "info_rights", "audit_body",
    "representation",
)
# I5: допущение (add-assumption) может фиксировать ещё и молчащее поле классификации
# компании (§5 ТЗ) — тему правил (add-rule/update-rule, TOPICS) она не расширяет: правило
# из устава по-прежнему привязывается только к одной из 16 тем таксономии выше.
ASSUMPTION_TOPICS = TOPICS + ("classification",)
ASSUMPTION_STATUSES = ("open", "resolved")  # resolved — недостающий документ получен (resolve-assumption)
CLASSIFICATIONS = (
    "MANDATORY_LAW", "DEFAULT_LAW", "CHARTER_OVERRIDE", "CHARTER_OPTION",
    "INTERNAL_RULE", "CONFLICT", "POTENTIALLY_OUTDATED", "MISSING_RULE",
    "NEEDS_HUMAN_REVIEW",
)
# классы, при которых вывод опирается на закон и требует Legal Freshness Check
LAW_DEPENDENT = frozenset({
    "MANDATORY_LAW", "DEFAULT_LAW", "CHARTER_OVERRIDE", "CHARTER_OPTION",
    "CONFLICT", "POTENTIALLY_OUTDATED",
})
FRESHNESS_STATUSES = ("verified", "changed", "uncertain", "failed")
VERIFICATIONS = ("candidate", "verified")
QUOTE_STATUSES = ("matched", "fuzzy", "not_found", "unchecked")
FACT_SECTIONS = (
    "classification", "ownership", "governance_bodies", "appointments",
    "related_entities", "open_governance_issues",
)
# ТЗ §5: классификация компании; unknown допустим всегда
CLASSIFICATION_FIELDS = {
    "entity_type": ("LLC", "JSC", "unknown"),
    "jsc_type": ("public", "non_public", "n/a", "unknown"),
    "issuer_status": (
        "issuer_with_disclosure_obligations", "issuer_without_continuous_disclosure",
        "non_issuer", "unknown",
    ),
    "ownership_mode": ("sole_member", "multiple_members", "shareholders", "unknown"),
    "board_exists": (True, False, "unknown"),
    "collective_executive_body_exists": (True, False, "unknown"),
    "special_regulatory_status": (
        "credit_institution", "insurance", "professional_securities_market",
        "strategic_entity", "other", "none", "unknown",
    ),
}


def to_date(value) -> dt.date | None:
    """Дата из строки YYYY-MM-DD или объекта date (yaml разбирает даты сам)."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def is_iso_date(value) -> bool:
    return to_date(value) is not None


def needs_law(rule: dict) -> bool:
    """Правило опирается на закон, если среди классов есть зависимые от закона."""
    return any(c in LAW_DEPENDENT for c in (rule.get("classification") or []))


def _blank(value) -> bool:
    return not str(value if value is not None else "").strip()


CARD_NAME_RE = re.compile(r"[a-z]+/[a-z0-9]+(?:-[a-z0-9]+)*")  # llc/voting-procedure


def _card_exists(card: str) -> bool:
    """law_ref.card — имя карточки-указателя вида <вид>/<slug> с файлом references/corporate-norm-cards/<card>.md.

    Строгое имя отсекает README рядом с карточками, обход каталога и регистр (Windows открыл бы
    LLC/NOTICE как llc/notice). Локальный импорт: gov_cards сам импортирует gov_schema, поэтому
    на уровне модуля был бы цикл; к моменту вызова оба модуля загружены, путь не дублируется.
    """
    if not isinstance(card, str) or not CARD_NAME_RE.fullmatch(card):
        return False
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import gov_cards  # noqa: PLC0415 — намеренно локальный импорт, см. докстринг

    try:
        return (gov_cards.CARDS_DIR.parent / f"{card}.md").is_file()
    except OSError:
        return False


# ---------- provenance и freshness ----------

def validate_provenance(prov, sources_by_id: dict) -> list[str]:
    if not isinstance(prov, dict):
        return ["provenance отсутствует или не объект"]
    errs: list[str] = []
    sid = prov.get("source_id")
    src = sources_by_id.get(sid)
    if _blank(sid):
        errs.append("provenance.source_id пуст")
    elif src is None:
        errs.append(f"provenance.source_id {sid!r} не найден в sources.yaml")
    page = prov.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        errs.append("provenance.page должен быть целым числом >= 1")
    elif src is not None and isinstance(src.get("pages"), int) and page > src["pages"]:
        errs.append(f"provenance.page {page} больше числа страниц источника ({src['pages']})")
    for field in ("clause", "quote"):
        if _blank(prov.get(field)):
            errs.append(f"provenance.{field} пуст")
    if not is_iso_date(prov.get("extracted_at")):
        errs.append("provenance.extracted_at должен быть датой YYYY-MM-DD")
    qc = prov.get("quote_check")
    if qc is not None and (not isinstance(qc, dict) or qc.get("status") not in QUOTE_STATUSES):
        errs.append(f"provenance.quote_check.status должен быть одним из {QUOTE_STATUSES}")
    return errs


def validate_freshness(fr) -> list[str]:
    if not isinstance(fr, dict):
        return ["freshness должен быть объектом"]
    errs: list[str] = []
    status = fr.get("status")
    if status not in FRESHNESS_STATUSES:
        errs.append(f"freshness.status должен быть одним из {FRESHNESS_STATUSES}")
    if not is_iso_date(fr.get("checked_at")):
        errs.append("freshness.checked_at должен быть датой YYYY-MM-DD")
    if _blank(fr.get("checked_source")):
        errs.append("freshness.checked_source пуст")
    if status == "verified" and _blank(fr.get("edition")):
        errs.append("freshness.status=verified требует edition (редакция и дата открытого текста)")
    if status in ("changed", "uncertain", "failed") and _blank(fr.get("required_action")):
        errs.append(f"freshness.status={status} требует required_action")
    return errs


# ---------- записи ----------

def validate_source(src: dict) -> list[str]:
    sid = src.get("source_id", "?")
    errs: list[str] = []
    if not re.fullmatch(r"S-\d{3,}", str(sid)):
        errs.append(f"{sid}: source_id должен иметь вид S-001")
    if src.get("kind") not in SOURCE_KINDS:
        errs.append(f"{sid}: kind должен быть одним из {SOURCE_KINDS}")
    if src.get("status") not in SOURCE_STATUSES:
        errs.append(f"{sid}: status должен быть одним из {SOURCE_STATUSES}")
    if _blank(src.get("title")):
        errs.append(f"{sid}: title пуст")
    if _blank(src.get("file")):
        errs.append(f"{sid}: file пуст")
    pages = src.get("pages")
    if pages is not None and (not isinstance(pages, int) or isinstance(pages, bool) or pages < 1):
        errs.append(f"{sid}: pages должен быть целым числом >= 1 или пусто")
    if src.get("edition_date") is not None and not is_iso_date(src["edition_date"]):
        errs.append(f"{sid}: edition_date должен быть датой YYYY-MM-DD")
    if src.get("status") == "current" and _blank(src.get("current_basis")):
        errs.append(f"{sid}: status=current требует current_basis (чем подтверждена актуальность)")
    # актуальность подтверждает юрист (approved_by) либо сверка с выпиской ЕГРЮЛ (verified_by_extract,
    # команда check-edition); сама выписка ФНС — документ реестра на свою дату и одобрения не требует
    if (src.get("status") == "current" and src.get("kind") != "egrul_extract"
            and _blank(src.get("approved_by")) and _blank(src.get("verified_by_extract"))):
        errs.append(f"{sid}: status=current требует approved_by (кто подтвердил актуальность) "
                    "или verified_by_extract (сверка с выпиской ЕГРЮЛ, check-edition)")
    by_extract = src.get("verified_by_extract")
    if by_extract is not None and not re.fullmatch(r"S-\d{3,}", str(by_extract)):
        errs.append(f"{sid}: verified_by_extract должен быть source_id выписки или пусто")
    sup = src.get("supersedes")
    if sup is not None and not re.fullmatch(r"S-\d{3,}", str(sup)):
        errs.append(f"{sid}: supersedes должен быть source_id или пусто")
    return errs


def validate_rule(rule: dict, sources_by_id: dict) -> list[str]:
    rid = rule.get("rule_id", "?")
    errs: list[str] = []

    def add(msg: str) -> None:
        errs.append(f"{rid}: {msg}")

    if not re.fullmatch(r"R-\d{3,}", str(rid)):
        add("rule_id должен иметь вид R-001")
    if rule.get("layer") not in LAYERS:
        add(f"layer должен быть одним из {LAYERS}")
    if rule.get("topic") not in TOPICS:
        add(f"topic должен быть одним из {TOPICS}")
    if _blank(rule.get("subject")):
        add("subject пуст")
    if rule.get("value") in (None, "", {}, []):
        add("value пуст")
    cls = rule.get("classification")
    if not isinstance(cls, list) or not cls:
        add("classification должен быть непустым списком")
    else:
        for item in cls:
            if item not in CLASSIFICATIONS:
                add(f"неизвестный класс {item!r}")
        if "MISSING_RULE" in cls:
            add("MISSING_RULE фиксируется допущением (add-assumption), а не правилом")
    if rule.get("verification") not in VERIFICATIONS:
        add(f"verification должен быть одним из {VERIFICATIONS}")
    errs.extend(f"{rid}: {e}" for e in validate_provenance(rule.get("provenance"), sources_by_id))
    fresh = rule.get("freshness")
    if fresh is not None:
        errs.extend(f"{rid}: {e}" for e in validate_freshness(fresh))
    law_ref = rule.get("law_ref")
    if law_ref is not None and (not isinstance(law_ref, dict) or _blank(law_ref.get("card"))):
        add("law_ref.card пуст")
    elif isinstance(law_ref, dict) and not _blank(law_ref.get("card")) and not _card_exists(law_ref["card"]):
        add(f"law_ref.card указывает на несуществующую карточку {law_ref['card']} — "
            "проверьте references/corporate-norm-cards/llc/")
    decisions = rule.get("decisions")
    if decisions is not None and (
            not isinstance(decisions, list)
            or not all(isinstance(d, str) and d.strip() for d in decisions)
            or len(set(decisions)) != len(decisions)):
        add("decisions должен быть списком неповторяющихся decision_id каталога решений")
    if rule.get("verification") == "verified":
        if _blank(rule.get("verified_by")) or not is_iso_date(rule.get("verified_at")):
            add("verified требует verified_by и verified_at")
        if needs_law(rule):
            if not law_ref:
                add("verified-правило, зависящее от закона, требует law_ref")
            elif isinstance(law_ref, dict) and _blank(law_ref.get("article")):
                add("verified-правило, зависящее от закона, требует law_ref.article (статья и пункт)")
            if not fresh or fresh.get("status") != "verified":
                add("verified-правило, зависящее от закона, требует freshness.status=verified")
        quote_check = (rule.get("provenance") or {}).get("quote_check") or {}
        if quote_check.get("status") == "not_found":
            add("verified-правило с quote_check=not_found")
    return errs


def validate_fact(fact: dict, sources_by_id: dict) -> list[str]:
    fid = fact.get("fact_id", "?")
    errs: list[str] = []

    def add(msg: str) -> None:
        errs.append(f"{fid}: {msg}")

    if not re.fullmatch(r"F-\d{3,}", str(fid)):
        add("fact_id должен иметь вид F-001")
    if fact.get("section") not in FACT_SECTIONS:
        add(f"section должен быть одним из {FACT_SECTIONS}")
    if _blank(fact.get("key")):
        add("key пуст")
    if "value" not in fact or fact["value"] in (None, "", {}, []):
        add("value пуст")
    if fact.get("section") == "classification":
        allowed = CLASSIFICATION_FIELDS.get(fact.get("key"))
        if allowed is None:
            add(f"неизвестное поле классификации {fact.get('key')!r}; допустимы {sorted(CLASSIFICATION_FIELDS)}")
        elif fact.get("value") not in allowed:
            add(f"значение {fact.get('value')!r} не входит в {allowed}")
    if fact.get("verification") not in VERIFICATIONS:
        add(f"verification должен быть одним из {VERIFICATIONS}")
    errs.extend(f"{fid}: {e}" for e in validate_provenance(fact.get("provenance"), sources_by_id))
    if fact.get("verification") == "verified" and (
        _blank(fact.get("verified_by")) or not is_iso_date(fact.get("verified_at"))
    ):
        add("verified требует verified_by и verified_at")
    return errs


def validate_assumption(item: dict) -> list[str]:
    aid = item.get("assumption_id", "?")
    errs: list[str] = []
    if not re.fullmatch(r"A-\d{3,}", str(aid)):
        errs.append(f"{aid}: assumption_id должен иметь вид A-001")
    if item.get("topic") not in ASSUMPTION_TOPICS:
        errs.append(f"{aid}: topic должен быть одним из {ASSUMPTION_TOPICS}")
    for field in ("missing_data", "default_rule_if_no_special_rule", "risk", "required_verification"):
        if _blank(item.get(field)):
            errs.append(f"{aid}: {field} пуст (ТЗ §24: допущение описывается полностью)")
    status = item.get("status", "open")
    if status not in ASSUMPTION_STATUSES:
        errs.append(f"{aid}: status должен быть одним из {ASSUMPTION_STATUSES}")
    if status == "resolved":
        if _blank(item.get("resolved_basis")) or not is_iso_date(item.get("resolved_at")):
            errs.append(f"{aid}: снятое допущение требует resolved_basis и resolved_at")
        source = item.get("resolved_by_source")
        if source is not None and not re.fullmatch(r"S-\d{3,}", str(source)):
            errs.append(f"{aid}: resolved_by_source должен быть source_id или пусто")
    return errs
