# -*- coding: utf-8 -*-
"""Команды competence-engine: validate-catalog, tag-decisions, competence, decisions-review.

Каталог решений ООО — общий слой (references/corporate-decisions/llc.yaml); привязки правил
и ответы — частный слой компании. Правовых выводов команды не делают.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_competence as competence  # noqa: E402
import gov_decisions as decisions  # noqa: E402
import gov_schema as schema  # noqa: E402
import gov_store as store  # noqa: E402
from gov_cmd_report import _refuse_out_inside_entities_dir  # noqa: E402
from gov_cmd_rules import _find, _reset_verification  # noqa: E402


def _catalog(args) -> dict:
    return decisions.read_catalog(Path(args.catalog) if args.catalog else decisions.CATALOG_PATH)


def _add_catalog_arg(parser) -> None:
    parser.add_argument("--catalog", help="каталог решений (по умолчанию references/corporate-decisions/llc.yaml)")


def cmd_validate_catalog(args) -> int:
    data = _catalog(args)
    errors = decisions.validate_catalog(data)
    if errors:
        print(f"ОШИБОК: {len(errors)}")
        for item in errors:
            print(f"  - {item}")
        return 1
    note = "" if data.get("approved_by") else " (каталог не подтверждён юристом: competence вернёт NEEDS_REVIEW)"
    print(f"OK: позиций {len(data['decisions'])}, ошибок нет{note}")
    return 0


def _split(text: str | None) -> list[str]:
    return [item.strip() for item in (text or "").split(",") if item.strip()]


def _read_map(path: str) -> dict[str, list[str]]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as exc:
        raise store.GovError(f"--map не читается: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise store.GovError("--map: нужен словарь вида R-001: [decision_id, ...]")
    return {str(key): [str(item) for item in value] for key, value in data.items()}


def cmd_tag_decisions(args) -> int:
    """Привязка правил к позициям каталога. Изменение снимает подтверждение правила:
    привязка — часть утверждаемого юристом содержания профиля."""
    if bool(args.map) == bool(args.rule_id):
        raise store.GovError("укажите либо --rule-id с --add/--remove, либо --map <файл>")
    if args.rule_id and not (args.add or args.remove):
        raise store.GovError("для --rule-id нужен --add или --remove")
    known = decisions.decision_ids(_catalog(args))
    entity = store.entity_from_args(args)
    data = entity.load_rules()
    if args.map:
        plan = _read_map(args.map)
    else:
        rule = _find(data["rules"], "rule_id", args.rule_id, "правило")
        removed = set(_split(args.remove))
        target = [d for d in (rule.get("decisions") or []) if d not in removed]
        target += [d for d in _split(args.add) if d not in target]
        plan = {args.rule_id: target}
    unknown = sorted({d for ids in plan.values() for d in ids} - known)
    if unknown:
        raise store.GovError(f"нет в каталоге решений: {', '.join(unknown)}")
    by_id = entity.sources_by_id()
    changes, downgraded = [], []
    for rule_id, target in plan.items():
        rule = _find(data["rules"], "rule_id", rule_id, "правило")
        old = {"decisions": list(rule.get("decisions") or []), "verification": rule.get("verification")}
        new_ids = list(dict.fromkeys(target))
        if new_ids == old["decisions"]:
            continue
        rule["decisions"] = new_ids
        if _reset_verification(rule):
            downgraded.append(rule_id)
        errors = schema.validate_rule(rule, by_id)
        if errors:
            raise store.GovError("; ".join(errors))
        changes.append((rule_id, old, {"decisions": new_ids, "verification": rule.get("verification")}))
    if not changes:
        print("OK: привязки без изменений")
        return 0
    rev = entity.save_rules(data)
    for rule_id, old, new in changes:
        entity.audit("tag-decisions", rule_id, actor=args.actor, old=old, new=new, rev=rev)
    note = (f"; подтверждение снято: {', '.join(downgraded)} (повторное confirm — по решению юриста)"
            if downgraded else "")
    print(f"OK: привязки изменены у {len(changes)} правил{note}")
    return 0


def cmd_competence(args) -> int:
    today = schema.to_date(args.date) if args.date else dt.date.today()
    if today is None:
        raise store.GovError("--date должен быть датой YYYY-MM-DD")
    catalog = _catalog(args)
    errors = decisions.validate_catalog(catalog)
    if errors:
        raise store.GovError("каталог решений с ошибками, сначала validate-catalog: " + "; ".join(errors[:3]))
    entity = store.entity_from_args(args)
    rules = entity.load_rules()["rules"]
    sources = entity.load_sources()["sources"]
    assumptions = entity.load_profile().get("assumptions", [])
    results = [competence.assemble(decisions.find_decision(catalog, did), catalog, rules, sources,
                                   assumptions, slug=entity.slug, today=today, days=args.days)
               for did in dict.fromkeys(args.decision)]
    payload = {"entity": entity.slug, "as_of": today.isoformat(),
               "status": competence.worst([r["status"] for r in results]), "results": results}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(competence.render_md(payload))
    return 0


def cmd_decisions_review(args) -> int:
    entity = store.entity_from_args(args)
    _refuse_out_inside_entities_dir(entity, args.out)
    catalog = _catalog(args)
    import gov_docx  # noqa: PLC0415 — python-docx нужен только этой команде

    path = gov_docx.build_decisions_review(entity, catalog, args.out)
    entity.audit("decisions-review", entity.slug, actor=args.actor, new={"path": str(path)})
    print(f"OK: {path}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("validate-catalog", parents=[store.common_parser(need_slug=False)],
                       help="проверить каталог решений ООО (references/corporate-decisions/llc.yaml)")
    _add_catalog_arg(p)
    p.set_defaults(func=cmd_validate_catalog)

    p = sub.add_parser("tag-decisions", parents=[store.common_parser()],
                       help="привязать правила к позициям каталога решений (снимает подтверждение)")
    p.add_argument("--rule-id")
    p.add_argument("--add", help="decision_id через запятую")
    p.add_argument("--remove", help="decision_id через запятую")
    p.add_argument("--map", help="yaml R-001: [decision_id, ...] — привязки задаются целиком")
    _add_catalog_arg(p)
    p.set_defaults(func=cmd_tag_decisions)

    p = sub.add_parser("competence", parents=[store.common_parser()],
                       help="кто решает вопрос: правила устава, допущения и проверки норм по позиции каталога")
    p.add_argument("--decision", required=True, action="append",
                   help="decision_id каталога; можно повторить для нескольких позиций")
    p.add_argument("--date", help="дата, на которую считается давность проверок (по умолчанию сегодня)")
    p.add_argument("--days", type=int, default=competence.STALE_DAYS, help="порог давности проверки нормы")
    p.add_argument("--format", default="json", choices=("json", "md"))
    _add_catalog_arg(p)
    # только читает: os.replace даёт целый файл, блокировка не нужна
    p.set_defaults(func=cmd_competence, no_lock=True)

    p = sub.add_parser("decisions-review", parents=[store.common_parser()],
                       help=".docx юристу: правила по позициям каталога и правила без привязки")
    p.add_argument("--out", required=True, help="путь к .docx (в workflow/<дело>/)")
    _add_catalog_arg(p)
    p.set_defaults(func=cmd_decisions_review)
