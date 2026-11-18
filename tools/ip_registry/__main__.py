"""CLI: python -m tools.ip_registry build | ingest <xlsx> | query [--number|--product|--country]."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .normalize import RECORD_STATUS_LABELS, TERRITORY_STATUS_LABELS
from .xlsx_reader import RegistryFormatError
from .documents import DOC_EXTENSIONS, accept_document, list_cards
from .facts import apply_facts, dismiss, revert_event, set_field
from .journal import read_events
from .pipeline import build, default_root, ingest_file, migrate, query
from .publish import publish


def _print_result(result) -> None:
    print(f"Знаков: {result.marks}; предупреждений разбора: {result.warnings}")
    print(f"Каталог: {result.catalog_path}")
    if result.changes_path:
        print(f"Изменения: {result.changes_path} {result.diff_counts}")
    if result.new_products:
        print("Новые препараты в products.yaml: " + ", ".join(result.new_products))


def _short(mark: dict) -> dict:
    short = {
        "знак": mark["mark_text"] or "[изобразительный знак]",
        "препарат": mark["product"],
        "№ рег.": mark["registration_no"],
        "№ заявки": mark["application_no"],
        "вид": mark["reg_type"],
        "статус": RECORD_STATUS_LABELS[mark["status"]],
        "страны": [f"{t['code']} {t['name']}: {TERRITORY_STATUS_LABELS[t['status']]}"
                   + (f" ({t['note']})" if t["note"] else "") for t in mark["territories"]],
        "классы": mark["nice_classes"],
        "срок до": mark["expiry_date"],
        "оплата": mark["next_payment_date"],
        "предупреждения": mark["warnings"],
    }
    if mark.get("verification"):
        short["сверка"] = f"{mark['verification']['source']} {mark['verification']['checked']}"
    if mark.get("provenance"):
        short["источник"] = {field: f"{p.get('kind')} {p.get('doc_date')} {p.get('file')}"
                             for field, p in mark["provenance"].items()}
    if mark.get("history"):
        short["событий"] = len(mark["history"])
    if mark["territory_notes"]:
        short["неразобранные фрагменты"] = mark["territory_notes"]
    return short


def _today(sub) -> None:
    sub.add_argument("--today", type=dt.date.fromisoformat)


def _day(args) -> dt.date:
    return args.today or dt.date.today()


def _value(field: str, raw: str):
    if field == "nice_classes":
        try:
            return [int(part) for part in raw.split(",") if part.strip()]
        except ValueError:
            raise ValueError("nice_classes: ожидаются номера классов через запятую") from None
    return raw


def _ingest(root: Path, args) -> None:
    suffix = args.path.suffix.lower()
    if suffix == ".xlsx":
        _print_result(ingest_file(root, args.path, today=args.today))
    elif suffix in DOC_EXTENSIONS:
        card = accept_document(root, args.path, today=_day(args))
        print(f"{card['doc_id']} {card['status']}" + (f" ({card['reason']})" if card.get("reason") else ""))
    else:
        raise ValueError(f"тип файла {suffix or '(без расширения)'} не поддерживается")


def _pending(root: Path) -> None:
    cards = [c for c in list_cards(root, statuses=("awaiting_facts", "needs_decision")) if c.get("doc_id")]
    print(json.dumps([{"doc_id": c["doc_id"], "document": c.get("document"), "status": c["status"],
                       "reason": c.get("reason")} for c in cards], ensure_ascii=False, indent=1))


def _facts_path(root: Path, path: Path) -> Path:
    """Относительный путь, которого нет от текущей папки, берётся от --root (pending/<doc_id>.facts.json)."""
    if path.is_absolute() or path.exists():
        return path
    return root / path


def _apply(root: Path, args) -> None:
    force = tuple(f.strip() for f in (args.force_fields or "").split(",") if f.strip())
    report = apply_facts(root, _facts_path(root, args.facts), today=_day(args), force_fields=force,
                         comment=args.comment)
    print(f"внесено: {len(report['applied'])}; новых: {len(report['created'])}; "
          f"устаревших: {len(report['stale'])}; отброшено: {len(report['dropped'])}; "
          f"ждут решения: {len(report['decisions'])}")
    print(f"Отчёт: {report['changes_path']}")
    if report["decisions"]:
        print("Решения юриста: python -m tools.ip_registry pending")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m tools.ip_registry", description="Реестр товарных знаков")
    parser.add_argument("--root", type=Path, help="папка домена (по умолчанию profile/knowledge/ip)")
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build", help="пересобрать из последней выгрузки в originals/ или из --source")
    build_cmd.add_argument("--source", type=Path)
    build_cmd.add_argument("--today", type=dt.date.fromisoformat)
    ingest_cmd = sub.add_parser("ingest", help="принять новую выгрузку: собрать и перенести в originals/")
    ingest_cmd.add_argument("path", type=Path)
    ingest_cmd.add_argument("--today", type=dt.date.fromisoformat)
    query_cmd = sub.add_parser("query", help="найти знаки")
    query_cmd.add_argument("--number")
    query_cmd.add_argument("--product")
    query_cmd.add_argument("--country", help="ISO-код или название, например UZ или Узбекистан")
    for name, help_text in (("migrate", "перенести прежний реестр в журнал"),
                            ("rebuild", "пересобрать базу из журнала без его изменений")):
        _today(sub.add_parser(name, help=help_text))
    sub.add_parser("pending", help="открытые карточки документов (JSON)")
    apply_cmd = sub.add_parser("apply-facts", help="внести факты документа")
    apply_cmd.add_argument("facts", type=Path)
    apply_cmd.add_argument("--force-fields")
    apply_cmd.add_argument("--comment")
    _today(apply_cmd)
    set_cmd = sub.add_parser("set", help="ручная правка поля знака")
    set_cmd.add_argument("--mark", required=True)
    set_cmd.add_argument("--field", required=True)
    set_cmd.add_argument("--value", required=True)
    set_cmd.add_argument("--comment", required=True)
    _today(set_cmd)
    revert_cmd = sub.add_parser("revert", help="отменить событие журнала")
    revert_cmd.add_argument("event_id")
    revert_cmd.add_argument("--comment", required=True)
    _today(revert_cmd)
    dismiss_cmd = sub.add_parser("dismiss", help="отклонить документ")
    dismiss_cmd.add_argument("doc_id")
    dismiss_cmd.add_argument("--comment", required=True)
    _today(dismiss_cmd)
    args = parser.parse_args(argv)
    root = args.root or default_root()

    try:
        if args.command == "build":
            _print_result(build(root, args.source, today=args.today))
        elif args.command == "ingest":
            _ingest(root, args)
        elif args.command == "migrate":
            result = migrate(root, today=_day(args))
            print(f"Знаков: {result['marks']}; событий: {result['events']}")
        elif args.command == "rebuild":
            events = read_events(root / "data" / "events.jsonl")
            if not events:
                raise ValueError("журнал пуст: сначала build или migrate")
            publish(root, events, today=_day(args))
            print(f"Пересобрано из журнала: событий {len(events)}")
        elif args.command == "pending":
            _pending(root)
        elif args.command == "apply-facts":
            _apply(root, args)
        elif args.command == "set":
            event = set_field(root, mark=args.mark, field=args.field, value=_value(args.field, args.value),
                              comment=args.comment, today=_day(args))
            print(f"Событие {event['event_id']}")
        elif args.command == "revert":
            event = revert_event(root, args.event_id, comment=args.comment, today=_day(args))
            print(f"Событие {event['event_id']}")
        elif args.command == "dismiss":
            card = dismiss(root, args.doc_id, comment=args.comment, today=_day(args))
            print(f"{card['doc_id']} dismissed")
        else:
            found = query(root, number=args.number, product=args.product, country=args.country)
            print(json.dumps([_short(mark) for mark in found], ensure_ascii=False, indent=1))
            if not found:
                print("В реестре не найдено (это не означает отсутствия охраны).", file=sys.stderr)
    except (RegistryFormatError, FileNotFoundError, ValueError, RuntimeError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
