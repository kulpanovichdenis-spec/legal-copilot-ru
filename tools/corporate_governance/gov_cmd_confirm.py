# -*- coding: utf-8 -*-
"""Команда confirm: перевод записей в verified только по подтверждению юриста.

Подтверждает содержание конкретной записи. Отказы объяснены по каждой записи,
остальные записи в том же вызове подтверждаются (юрист подтверждает группами).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_schema as schema  # noqa: E402
import gov_store as store  # noqa: E402


def _freshness_status_reason(fresh: dict) -> str:
    """Текст отказа по неверифицированному freshness — общий для обоих гейтов ниже (I3):
    закон-зависимого класса и leftover-блока, пережившего реклассификацию."""
    action = str(fresh.get("required_action") or "").strip()
    return f"freshness.status={fresh.get('status')}" + (f": {action}" if action else "")


def blockers(kind: str, record: dict, sources_by_id: dict) -> list[str]:
    """Причины, по которым запись нельзя подтвердить (пустой список = можно)."""
    reasons: list[str] = []
    if record.get("needs_review"):
        reasons.append("помечена needs_review: источник заменён новой редакцией, "
                       "внесите правило заново из актуального документа")
    prov = record.get("provenance")
    prov = prov if isinstance(prov, dict) else {}
    source_id = prov.get("source_id")
    source = sources_by_id.get(source_id) if isinstance(source_id, str) else None
    # needs_review ставится только записям, существовавшим на момент supersede-source;
    # запись, внесённая позже из уже заменённого источника, флага не имеет
    if isinstance(source, dict) and source.get("status") == "superseded":
        reasons.append(f"источник {source_id} заменён новой редакцией (superseded): "
                       "внесите правило заново из актуального документа")
    if kind == "rule":
        reasons.extend(schema.validate_rule(record, sources_by_id))
        needs_law = schema.needs_law(record)
        fresh = record.get("freshness")
        if needs_law:
            law_ref = record.get("law_ref")
            if not law_ref:
                reasons.append("нет law_ref: укажите карточку-указатель нормы")
            elif isinstance(law_ref, dict) and not str(law_ref.get("article") or "").strip():
                # I4: карточка сама по себе — не подтверждённая норма; без статьи/пункта, открытых
                # живым маршрутом, Legal Freshness Check по факту не о чём — только по карточке
                reasons.append("нет law_ref.article: укажите статью/пункт, открытые живым маршрутом")
            if not fresh:
                reasons.append("нет проверки актуальности нормы (Legal Freshness Check)")
            elif not isinstance(fresh, dict):
                reasons.append("freshness имеет неверную форму (ожидается объект)")
            elif fresh.get("status") != "verified":
                reasons.append(_freshness_status_reason(fresh))
        elif fresh and not record.get("law_ref"):
            # validate отвергает блок freshness без law_ref у любого правила, не только закон-зависимого
            reasons.append("freshness без law_ref: укажите карточку-указатель нормы или уберите проверку")
        # I3: реклассификация (update-rule --classification) не сбрасывает freshness сама по
        # себе — если после неё правило больше не закон-зависимое, но старый неверифицированный
        # freshness-блок остался, confirm по-прежнему отказывает: иначе гейт актуальности нормы
        # обходится сменой класса без новой проверки
        if not needs_law and isinstance(fresh, dict) and fresh.get("status") != "verified":
            reasons.append(_freshness_status_reason(fresh))
        # I3: классификация — это решение юриста; NEEDS_HUMAN_REVIEW без другого класса значит,
        # что юрист его ещё не принял, и confirm тут подтверждать нечего
        cls = record.get("classification") or []
        if cls and not [c for c in cls if c != "NEEDS_HUMAN_REVIEW"]:
            reasons.append(
                "классификация — только NEEDS_HUMAN_REVIEW: юрист ещё не определил итоговый класс "
                "правила, confirm требует содержательной классификации")
    else:
        reasons.extend(schema.validate_fact(record, sources_by_id))
    quote_check = prov.get("quote_check")
    if isinstance(quote_check, dict) and quote_check.get("status") == "not_found":
        reasons.append("цитата не найдена в тексте страницы (quote_check=not_found): "
                       "исправьте цитату или страницу")
    return reasons


def _schema_reasons_if_verified(kind: str, record: dict, sources_by_id: dict, by: str, at: str) -> list[str]:
    """Ошибки схемы, которые возникнут у записи в состоянии verified (запись не меняется).

    Подтверждение не должно писать то, что не пропускает валидатор схемы.
    Вызывать только после того, как blockers вернул пустой список: слой рассчитан на записи,
    форму которых blockers уже проверил (иначе валидатор может упасть на неверном типе поля).
    """
    candidate = {**record, "verification": "verified", "verified_by": by, "verified_at": at}
    validator = schema.validate_rule if kind == "rule" else schema.validate_fact
    return validator(candidate, sources_by_id)


def _confirm_snapshot(kind: str, record: dict) -> dict:
    """Компактный снимок подтверждённого содержания для аудита (I7c): что именно юрист
    подтвердил, а не только approval.by/at, которое подтверждение уже несёт отдельно."""
    prov = record.get("provenance") or {}
    reduced_provenance = {"page": prov.get("page"), "clause": prov.get("clause"),
                          "quote": prov.get("quote")}
    if kind == "rule":
        return {"subject": record.get("subject"), "value": record.get("value"),
                "classification": record.get("classification"), "law_ref": record.get("law_ref"),
                "freshness": record.get("freshness"), "provenance": reduced_provenance}
    return {"key": record.get("key"), "value": record.get("value"), "section": record.get("section"),
            "provenance": reduced_provenance}


def cmd_confirm(args) -> int:
    by = (args.by or "").strip()
    if not by:
        raise store.GovError("--by не должен быть пустым: подтверждение принимает конкретный юрист")
    if store.is_placeholder_approver(by):
        raise store.GovError(
            f"--by должен быть именем юриста, который дал согласие в этой сессии, а не ролью "
            f"или плейсхолдером ({by!r}): укажите ФИО, как его назвал юрист")
    entity = store.entity_from_args(args)
    ids = list(dict.fromkeys(x.strip() for x in args.ids.split(",") if x.strip()))
    if not ids:
        raise store.GovError("--ids пуст")
    rules, profile = entity.load_rules(), entity.load_profile()
    sources = entity.sources_by_id()
    stamp = store.today()
    confirmed, refused = [], []
    snapshots: dict[str, dict] = {}
    touched = {"rules": False, "profile": False}
    for oid in ids:
        if oid.startswith("R-"):
            kind, record = "rule", next((r for r in rules["rules"] if r["rule_id"] == oid), None)
        elif oid.startswith("F-"):
            kind, record = "fact", next((f for f in profile["facts"] if f["fact_id"] == oid), None)
        else:
            refused.append((oid, ["confirm поддерживает правила (R-…) и факты (F-…)"]))
            continue
        if record is None:
            refused.append((oid, ["запись не найдена"]))
            continue
        if record.get("verification") == "verified":
            refused.append((oid, ["уже подтверждено"]))
            continue
        reasons = blockers(kind, record, sources)
        if not reasons:
            reasons = _schema_reasons_if_verified(kind, record, sources, by, stamp)
        if reasons:
            refused.append((oid, reasons))
            continue
        record["verification"] = "verified"
        record["verified_by"] = by
        record["verified_at"] = stamp
        confirmed.append(oid)
        snapshots[oid] = _confirm_snapshot(kind, record)
        touched["rules" if kind == "rule" else "profile"] = True
    rev_rules = entity.save_rules(rules) if touched["rules"] else None
    rev_profile = entity.save_profile(profile) if touched["profile"] else None
    for oid in confirmed:
        entity.audit("confirm", oid, actor=args.actor, approval={"by": by, "at": stamp},
                     new=snapshots[oid], rev=rev_rules if oid.startswith("R-") else rev_profile)
    print(f"Подтверждено: {len(confirmed)}" + (f" ({', '.join(confirmed)})" if confirmed else ""))
    for oid, reasons in refused:
        print(f"ОТКАЗ {oid}:")
        for reason in reasons:
            print(f"  - {reason}")
    return 1 if refused else 0


def register(sub) -> None:
    p = sub.add_parser("confirm", parents=[store.common_parser()],
                       help="подтвердить записи (verified) по решению юриста")
    p.add_argument("--ids", required=True, help="R-001,R-002,F-001")
    p.add_argument("--by", required=True, help="кто подтвердил (юрист)")
    p.set_defaults(func=cmd_confirm)
