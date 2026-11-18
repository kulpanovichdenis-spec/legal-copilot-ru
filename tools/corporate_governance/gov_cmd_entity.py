# -*- coding: utf-8 -*-
"""Команды: init-entity, register-source, set-source-status, supersede-source."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_cmd_rules  # noqa: E402
import gov_schema as schema  # noqa: E402
import gov_store as store  # noqa: E402


def _detect_pages(entity: store.Entity, rel_file: str) -> int | None:
    """Число страниц PDF, если файл лежит под corporate/ и читается PyMuPDF."""
    path = entity.domain_dir / rel_file
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return None
    try:
        import fitz
    except ImportError:
        return None
    try:
        with fitz.open(str(path)) as doc:
            return len(doc)
    except Exception:  # noqa: BLE001 — повреждённый PDF регистрируется без числа страниц, а не роняет команду
        return None


def find_source(data: dict, source_id: str) -> dict:
    for src in data["sources"]:
        if src["source_id"] == source_id:
            return src
    raise store.GovError(f"источник не найден: {source_id}")


def cmd_init_entity(args) -> int:
    entity = store.entity_from_args(args, must_exist=False)
    entity.init(args.name)
    entity.audit("init-entity", entity.slug, actor=args.actor, new={"name": args.name}, rev=1)
    print(f"OK: заведена компания {entity.slug} ({entity.dir})")
    return 0


def cmd_register_source(args) -> int:
    entity = store.entity_from_args(args)
    data = entity.load_sources()
    if any(s.get("file") == args.file for s in data["sources"]):
        raise store.GovError(f"документ уже зарегистрирован: {args.file}")
    registry = None
    if args.grn or args.grn_date:
        registry = {"grn": args.grn, "date": args.grn_date}
    src = {
        "source_id": store.next_id("S", data["sources"], "source_id"),
        "kind": args.kind,
        "title": args.title,
        "edition_date": args.edition_date,
        "registry_record": registry,
        "file": args.file,
        "pages": args.pages if args.pages else _detect_pages(entity, args.file),
        "status": "unverified",
        "supersedes": None,
        "current_basis": None,
        "registered_at": store.today(),
    }
    errors = schema.validate_source(src)
    if errors:
        raise store.GovError("; ".join(errors))
    data["sources"].append(src)
    rev = entity.save_sources(data)
    entity.audit("register-source", src["source_id"], actor=args.actor, new=src,
                 source=args.file, rev=rev)
    print(f"OK: {src['source_id']} {src['kind']} (стр. {src['pages']}), статус unverified")
    return 0


def cmd_update_source(args) -> int:
    """Уточнить реквизиты зарегистрированного документа (название, вид, дата редакции, запись ЕГРЮЛ).

    Отметку налогового органа часто читают уже после регистрации, а повторно зарегистрировать
    тот же файл нельзя. Вид исправляется без смены статуса. Смена даты редакции или записи ЕГРЮЛ снимает статус current: прежнее
    основание актуальности относилось к другим реквизитам.
    """
    entity = store.entity_from_args(args)
    data = entity.load_sources()
    src = find_source(data, args.source_id)
    if src["status"] == "superseded":
        raise store.GovError(f"{args.source_id} уже заменён (superseded): реквизиты прежней редакции не меняются")
    if not any((args.title, args.kind, args.edition_date, args.grn, args.grn_date)):
        raise store.GovError("укажите хотя бы одно: --title, --kind, --edition-date, --grn с --grn-date")
    if bool(args.grn) != bool(args.grn_date):
        raise store.GovError("запись ЕГРЮЛ задаётся парой: --grn и --grn-date")
    keys = ("title", "kind", "edition_date", "registry_record", "status", "current_basis",
            "approved_by", "approved_at", "verified_by_extract")
    old = {k: src.get(k) for k in keys}
    if args.title:
        src["title"] = args.title
    if args.kind:
        src["kind"] = args.kind
    edition_changed = False
    if args.edition_date and args.edition_date != src.get("edition_date"):
        src["edition_date"] = args.edition_date
        edition_changed = True
    if args.grn:
        registry = {"grn": args.grn, "date": args.grn_date}
        if registry != src.get("registry_record"):
            src["registry_record"] = registry
            edition_changed = True
    if edition_changed and src["status"] == "current":
        src.update(status="unverified", current_basis=None, approved_by=None, approved_at=None,
                   verified_by_extract=None)
    errors = schema.validate_source(src)
    if errors:
        raise store.GovError("; ".join(errors))
    rev = entity.save_sources(data)
    entity.audit("update-source", src["source_id"], actor=args.actor, old=old,
                 new={k: src.get(k) for k in keys}, rev=rev)
    note = " (статус current снят: реквизиты редакции изменились)" if old["status"] != src["status"] else ""
    print(f"OK: {src['source_id']} обновлён{note}")
    return 0


def cmd_set_source_status(args) -> int:
    entity = store.entity_from_args(args)
    data = entity.load_sources()
    src = find_source(data, args.source_id)
    if args.status == "superseded":
        raise store.GovError(
            "set-source-status не заменяет редакцию: используйте supersede-source "
            "(--old <прежний source_id> --new <новый source_id>) — она же переносит needs_review "
            "на связанные правила и факты")
    if src["status"] == "superseded":
        raise store.GovError(f"{args.source_id} уже заменён: статус superseded не меняется "
                             "(см. supersede-source, которая его установила)")
    approval = None
    if args.status == "current":
        by = (args.by or "").strip()
        if not by:
            raise store.GovError(
                "set-source-status --status current требует --by <ФИО юриста>: кто подтвердил "
                "актуальность редакции (наряду с --basis)")
        if store.is_placeholder_approver(by):
            raise store.GovError(
                f"--by должен быть именем юриста, который подтвердил актуальность, а не ролью "
                f"или плейсхолдером ({by!r}): укажите ФИО, как его назвал юрист")
        approval = {"by": by, "at": store.today()}
    old = {"status": src["status"], "current_basis": src.get("current_basis"),
           "approved_by": src.get("approved_by"), "approved_at": src.get("approved_at")}
    src["status"] = args.status
    # current_basis и approved_by/approved_at относятся только к текущему подтверждению
    # актуальности: уходя из current, их сбросить, иначе старое основание молча остаётся
    # при следующем статусе
    src["current_basis"] = args.basis if args.status == "current" else None
    src["approved_by"] = approval["by"] if approval else None
    src["approved_at"] = approval["at"] if approval else None
    # ручной статус заменяет сверку check-edition: её основание к новому статусу не относится
    src["verified_by_extract"] = None
    errors = schema.validate_source(src)
    if errors:
        raise store.GovError("; ".join(errors))
    rev = entity.save_sources(data)
    entity.audit("set-source-status", src["source_id"], actor=args.actor, old=old,
                 new={"status": src["status"], "current_basis": src.get("current_basis"),
                      "approved_by": src.get("approved_by"), "approved_at": src.get("approved_at")},
                 approval=approval, rev=rev)
    print(f"OK: {src['source_id']} → {src['status']}")
    return 0


def _require_provenance(items: list[dict], id_key: str, label: str) -> None:
    """Проверить форму записей до любой правки: supersede-source не должна писать файлы наполовину."""
    for item in items:
        prov = item.get("provenance")
        if not isinstance(prov, dict) or "source_id" not in prov:
            raise store.GovError(
                f"{item.get(id_key, '?')}: {label} повреждена (нет provenance.source_id) — "
                "supersede-source остановлена, файлы не изменены")


def cmd_supersede_source(args) -> int:
    entity = store.entity_from_args(args)
    if args.old == args.new:
        raise store.GovError("старая и новая редакции должны быть разными источниками")
    data = entity.load_sources()
    old, new = find_source(data, args.old), find_source(data, args.new)
    if old["status"] == "superseded":
        raise store.GovError(f"{args.old} уже заменён")
    # читать и проверять форму правил и фактов ДО первой правки: при битой записи операция
    # не должна оставлять sources.yaml изменённым, а rules.yaml/profile.yaml — нетронутыми
    rules = entity.load_rules()
    profile = entity.load_profile()
    _require_provenance(rules["rules"], "rule_id", "запись правила")
    _require_provenance(profile["facts"], "fact_id", "запись факта")

    prev_status = old["status"]
    old["status"] = "superseded"
    new["supersedes"] = args.old

    flagged_rules, downgraded_rules = [], []
    for rule in rules["rules"]:
        if rule["provenance"]["source_id"] == args.old and not rule.get("needs_review"):
            rule["needs_review"] = True
            flagged_rules.append(rule["rule_id"])
            if gov_cmd_rules._reset_verification(rule):
                downgraded_rules.append(rule["rule_id"])

    flagged_facts, downgraded_facts = [], []
    for fact in profile["facts"]:
        if fact["provenance"]["source_id"] == args.old and not fact.get("needs_review"):
            fact["needs_review"] = True
            flagged_facts.append(fact["fact_id"])
            if gov_cmd_rules._reset_verification(fact):
                downgraded_facts.append(fact["fact_id"])

    rev_sources = entity.save_sources(data)
    rev_rules = entity.save_rules(rules)
    rev_profile = entity.save_profile(profile)

    entity.audit("supersede-source", args.old, actor=args.actor,
                 old={"status": prev_status,
                      "downgraded_from_verified": {"rules": downgraded_rules, "facts": downgraded_facts}},
                 new={"superseded_by": args.new, "needs_review_rules": flagged_rules,
                      "needs_review_facts": flagged_facts,
                      "revisions": {"sources": rev_sources, "rules": rev_rules, "profile": rev_profile}},
                 rev=rev_sources)
    downgraded_note = ""
    if downgraded_rules or downgraded_facts:
        downgraded_note = (f"; понижено с verified: правил {len(downgraded_rules)}, "
                           f"фактов {len(downgraded_facts)}")
    print(f"OK: {args.old} заменён на {args.new}; на пересмотр: правил {len(flagged_rules)}, "
          f"фактов {len(flagged_facts)}{downgraded_note}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("init-entity", parents=[store.common_parser()],
                       help="завести компанию (папка + пустые yaml)")
    p.add_argument("--name", required=True, help="название компании (метка профиля)")
    p.set_defaults(func=cmd_init_entity, no_lock=True)  # папки ещё нет; блокировку берёт Entity.init

    p = sub.add_parser("register-source", parents=[store.common_parser()],
                       help="зарегистрировать документ (устав, решение и т. д.)")
    p.add_argument("--kind", required=True, choices=schema.SOURCE_KINDS)
    p.add_argument("--title", required=True)
    p.add_argument("--file", required=True,
                   help="путь относительно corporate/, например originals/Устав.pdf")
    p.add_argument("--pages", type=int, help="число страниц (для PDF определяется само)")
    p.add_argument("--edition-date", help="дата редакции документа YYYY-MM-DD")
    p.add_argument("--grn", help="ГРН записи ЕГРЮЛ о редакции")
    p.add_argument("--grn-date", help="дата записи YYYY-MM-DD")
    p.set_defaults(func=cmd_register_source)

    p = sub.add_parser("update-source", parents=[store.common_parser()],
                       help="уточнить реквизиты документа: название, вид, дата редакции, запись ЕГРЮЛ "
                            "(смена редакции снимает статус current)")
    p.add_argument("--source-id", required=True)
    p.add_argument("--title")
    p.add_argument("--kind", choices=schema.SOURCE_KINDS,
                   help="вид документа, если зарегистрирован неверно (статус не меняется)")
    p.add_argument("--edition-date", help="дата редакции документа YYYY-MM-DD")
    p.add_argument("--grn", help="ГРН записи ЕГРЮЛ о редакции (вместе с --grn-date)")
    p.add_argument("--grn-date", help="дата записи YYYY-MM-DD")
    p.set_defaults(func=cmd_update_source)

    p = sub.add_parser("set-source-status", parents=[store.common_parser()],
                       help="установить статус источника (current требует --basis и --by; "
                            "superseded — только через supersede-source)")
    p.add_argument("--source-id", required=True)
    p.add_argument("--status", required=True, choices=schema.SOURCE_STATUSES)
    p.add_argument("--basis", help="чем подтверждена актуальность (для current)")
    p.add_argument("--by", help="ФИО юриста, подтвердившего актуальность (обязателен для current)")
    p.set_defaults(func=cmd_set_source_status)

    p = sub.add_parser("supersede-source", parents=[store.common_parser()],
                       help="новая редакция заменяет старую; правила старой уходят на пересмотр")
    p.add_argument("--old", required=True, help="source_id прежней редакции")
    p.add_argument("--new", required=True, help="source_id новой редакции")
    p.set_defaults(func=cmd_supersede_source)
