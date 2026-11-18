# -*- coding: utf-8 -*-
"""Команды реестра группы: group-sync, group-add, group-link, group-officer, group-relative,
group-pbu11, group-show, group-lists.

group-sync получает выписку ЕГРЮЛ (или берёт уже скачанную, --file) и переносит в реестр общество,
участников с долями и датами записей и ЕИО. Иностранные компании, их доли и руководителей, закрытие,
родственников и прочие связанные стороны ПБУ 11/2008 юрист вносит вручную, всегда с --source.
group-lists выпускает четыре черновика .docx. Реестр не привязан к одной компании, поэтому команды
без --slug и берут блокировку реестра сами.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_egrul as egrul  # noqa: E402
import gov_group as gg  # noqa: E402
import gov_group_calc as calc  # noqa: E402
import gov_group_docx as gdocx  # noqa: E402
import gov_store as store  # noqa: E402
from gov_cmd_egrul import MANUAL, _free_name  # noqa: E402

SHORT = gdocx.SHORT


def _day(value: str | None, field: str) -> dt.date:
    return gg.as_date(gg.check_date(value, field)) if value else dt.date.today()


def _mutate(args, action: str, change) -> int:
    """Цикл «прочитать, изменить, сохранить, записать в аудит» под блокировкой реестра."""
    grp = gg.group_store(args)
    grp.ensure()
    with grp.locked():
        data = grp.load()
        obj, new, source, lines = change(data, grp)
        rev = grp.save(data)
        grp.audit(action, obj, actor=args.actor, new=new, source=source, rev=rev)
    for line in lines:
        print(line)
    return 0


# ---------- group-sync ----------

def _extract_file(args, grp: gg.GroupStore) -> tuple[Path, str]:
    if args.file:
        path = Path(args.file)
        path = path if path.is_absolute() else grp.domain_dir / path
        if not path.is_file():
            raise store.GovError(f"файл выписки не найден: {path}")
        return path, "файл"
    if not args.ogrn:
        raise store.GovError("нужен --ogrn (выписка будет получена с egrul.nalog.ru) или --file (уже скачанная)")
    originals = grp.domain_dir / "originals"
    target = originals / _free_name(originals, f"ЕГРЮЛ {args.ogrn.strip()} {store.today()}")
    try:
        egrul.fetch_extract(args.ogrn, target)
    except ValueError as exc:
        raise store.GovError(str(exc)) from exc
    except egrul.EgrulUnavailable as exc:
        raise store.GovError(f"выписка не получена автоматически ({exc}). {MANUAL} Затем group-sync --file "
                             "originals/<файл>.") from exc
    return target, egrul.BASE_URL


def cmd_group_sync(args) -> int:
    def change(data, grp):
        path, origin = _extract_file(args, grp)
        try:
            info = egrul.parse_pages(egrul.pdf_page_texts(path))
            if args.ogrn and info["ogrn"] not in (args.ogrn.strip(), None) and info["inn"] != args.ogrn.strip():
                raise store.GovError(f"в файле выписка другой компании (ОГРН {info['ogrn']}, запрошен {args.ogrn})")
        except Exception as exc:  # noqa: BLE001 — нечитаемая или чужая выписка сообщается как ошибка команды
            if origin != "файл":
                path.unlink(missing_ok=True)  # скачанный файл не остаётся в originals/
            raise store.GovError(f"выписку не удалось принять ({exc})") from exc
        rel = path.relative_to(grp.domain_dir).as_posix() if path.is_relative_to(grp.domain_dir) else str(path)
        source = f"выписка ЕГРЮЛ от {gg.fmt_date(info['extract_date'])} ({rel})"
        company, lines = gg.apply_extract(data, info, source)
        return company["id"], {"ogrn": info["ogrn"], "extract_date": info["extract_date"], "file": rel,
                               "origin": origin}, source, lines
    return _mutate(args, "group-sync", change)


# ---------- ручные записи ----------

ENTITY_FIELDS = ("ogrn", "inn", "reg_id", "country", "address", "short_name")


def cmd_group_add(args) -> int:
    def change(data, _grp):
        fields = {k: getattr(args, k) for k in ENTITY_FIELDS if getattr(args, k)}
        if args.own_share:
            if gg.percent(args.own_share) is None:
                raise store.GovError(f"--own-share {args.own_share!r}: нужно число процентов")
            fields["own_share"] = args.own_share.replace(",", ".")
        if args.closed:
            fields.update(closed=gg.check_date(args.closed, "closed", year_ok=True), status="closed",
                          closed_reported=gg.check_date(args.closed_reported, "closed-reported") or store.today())
        if args.key:
            entity = gg.require_entity(data, args.key)
            if args.name:
                entity["name"] = " ".join(args.name.split())
            entity.update(fields, source=args.source)
            created = False
        else:
            if not (args.kind and args.name):
                raise store.GovError("новое лицо: нужны --kind и --name (изменение существующего: --key)")
            entity, created = gg.upsert_entity(data, kind=args.kind, name=args.name, source=args.source, **fields)
        verb = "заведено" if created else "обновлено"
        return entity["id"], dict(entity), args.source, [f"OK: {entity['id']} {gg.label(entity)} — {verb}"]
    return _mutate(args, "group-add", change)


def cmd_group_link(args) -> int:
    def change(data, _grp):
        owner, target = gg.require_entity(data, args.owner), gg.require_entity(data, args.target)
        link, created = gg.add_link(data, owner=owner["id"], target=target["id"], source=args.source,
                                    percent_value=args.percent, nominal=args.nominal, since=args.since,
                                    until=args.until, share_date=args.share_date, paid=args.paid, basis=args.basis)
        period = f"{gg.fmt_date(link.get('since')) or '?'} — {gg.fmt_date(link.get('until')) or 'н. в.'}"
        return link["id"], dict(link), args.source, [
            f"OK: {link['id']} {gg.label(owner)} → {gg.label(target)} {gg.fmt_percent(link.get('percent')) or '?'}, "
            f"{period} — {'внесена' if created else 'обновлена'}"]
    return _mutate(args, "group-link", change)


def _update_office(data: dict, args) -> tuple:
    office = next((o for o in data["offices"] if o["id"] == args.key), None)
    if office is None:
        raise store.GovError(f"должности {args.key} в реестре группы нет (group-show)")
    fields = {"since": gg.check_date(args.since, "since"), "until": gg.check_date(args.until, "until"),
              "title": args.title}
    office.update({k: v for k, v in fields.items() if v}, source=args.source)
    by_id = gg.entities_by_id(data)
    return office["id"], dict(office), args.source, [
        f"OK: {office['id']} {gg.label(by_id[office['person']])} — {SHORT[office['role']]} "
        f"{gg.label(by_id[office['company']])} с {gg.fmt_date(office.get('since')) or '?'} — обновлено"]


def cmd_group_officer(args) -> int:
    def change(data, _grp):
        if args.key:
            return _update_office(data, args)
        if not (args.person and args.company and args.role):
            raise store.GovError("новая должность: нужны --person, --company и --role (изменение: --key O-…)")
        person, company = gg.require_entity(data, args.person), gg.require_entity(data, args.company)
        if person["kind"] != "person" and args.role == "board":
            raise store.GovError("членом совета директоров может быть только физическое лицо")
        office, created = gg.add_office(data, person=person["id"], company=company["id"], role=args.role,
                                        source=args.source, since=args.since, until=args.until, title=args.title)
        return office["id"], dict(office), args.source, [
            f"OK: {office['id']} {gg.label(person)} — {SHORT[args.role]} {gg.label(company)} "
            f"с {gg.fmt_date(office.get('since')) or '?'} — {'внесено' if created else 'обновлено'}"]
    return _mutate(args, "group-officer", change)


def cmd_group_relative(args) -> int:
    def change(data, _grp):
        a, b = gg.require_entity(data, args.a), gg.require_entity(data, args.b)
        if a["kind"] != "person" or b["kind"] != "person":
            raise store.GovError("родственная связь (п. 7 ч. 1 ст. 9 Закона № 135-ФЗ) — только между физическими лицами")
        record = {"id": store.next_id("K", data["relatives"], "id"), "a": a["id"], "b": b["id"],
                  "relation": args.relation, "since": gg.check_date(args.since, "since"),
                  "until": gg.check_date(args.until, "until"), "source": args.source}
        data["relatives"].append(record)
        return record["id"], record, args.source, [f"OK: {record['id']} {gg.label(a)} и {gg.label(b)}: {args.relation}"]
    return _mutate(args, "group-relative", change)


def cmd_group_pbu11(args) -> int:
    def change(data, _grp):
        company = gg.require_entity(data, args.company)
        if args.none:
            company["pbu11_none"] = args.source
            return company["id"], {"pbu11_none": args.source}, args.source, [
                f"OK: {gg.label(company)}: участников совместной деятельности и НПФ нет ({args.source})"]
        if not (args.name and args.basis):
            raise store.GovError("нужны --name и --basis (или --none, если таких лиц нет)")
        company.pop("pbu11_none", None)
        record = {"id": store.next_id("P", data["pbu11_other"], "id"), "company": company["id"], "name": args.name,
                  "ids": args.ids, "basis": args.basis, "since": gg.check_date(args.since, "since"),
                  "until": gg.check_date(args.until, "until"), "source": args.source}
        data["pbu11_other"].append(record)
        return record["id"], record, args.source, [f"OK: {record['id']} {args.name} — {args.basis}"]
    return _mutate(args, "group-pbu11", change)


# ---------- просмотр и выпуск ----------

def cmd_group_show(args) -> int:
    data = gg.group_store(args).load()
    by_id = gg.entities_by_id(data)
    print(f"Реестр группы: лиц {len(data['entities'])}, связей владения {len(data['links'])}, "
          f"должностей {len(data['offices'])}, родственных связей {len(data['relatives'])}")
    for e in data["entities"]:
        closed = f", прекращено {gg.fmt_date(e.get('closed'))}" if e.get("status") == "closed" else ""
        print(f"  {e['id']} {gg.label(e)} ({e['kind']}{closed})")
    for l in data["links"]:
        until = f" по {gg.fmt_date(l['until'])}" if l.get("until") else ""
        print(f"  {l['id']} {gg.label(by_id[l['owner']])} → {gg.label(by_id[l['target']])} "
              f"{gg.fmt_percent(l.get('percent')) or '?'} с {gg.fmt_date(l.get('since')) or '?'}{until}")
    if args.company:
        company = gg.require_entity(data, args.company)
        day = _day(args.date, "--date")
        print(f"Аффилированные лица {gg.label(company)} на {gg.fmt_date(day)}:")
        for row in calc.affiliate_rows(data, company["id"], day):
            bases = "; ".join(f"{SHORT[b['code']]} с {b['since_text'] or '?'}" for b in row["bases"])
            print(f"  {gg.label(row['entity'])}: {bases}")
    return 0


def cmd_group_lists(args) -> int:
    data = gg.group_store(args).load()
    company = gg.require_entity(data, args.company)
    day, start = _day(args.date, "--date"), _day(args.period_start, "--period-start")
    if start >= day:
        raise store.GovError(f"--period-start {start} должен быть раньше --date {day}")
    rel_start = _day(args.related_start, "--related-start") if args.related_start else start
    rel_end = _day(args.related_end, "--related-end") if args.related_end else day
    if rel_start >= rel_end:
        raise store.GovError(f"--related-start {rel_start} должен быть раньше --related-end {rel_end}")
    paths = gdocx.build_all(data, company["id"], day, start, args.out_dir, related=(rel_start, rel_end),
                            related_leavers=not args.related_without_leavers)
    rows = calc.affiliate_rows(data, company["id"], day)
    print(f"OK: {gg.label(company)} на {gg.fmt_date(day)}: аффилированных лиц: {len(rows)}, "
          f"изменений за период: {len(calc.changes(data, company['id'], start, day))}, "
          f"связанных сторон за {gg.fmt_date(rel_start)}–{gg.fmt_date(rel_end)}: "
          f"{len(calc.related_parties(data, company['id'], rel_start, rel_end))}")
    for path in paths:
        print(f"  {path}")
    return 0


def register(sub) -> None:
    common = store.common_parser(need_slug=False)

    p = sub.add_parser("group-sync", parents=[common],
                       help="выписка ЕГРЮЛ → реестр группы: общество, участники с датами записей, ЕИО")
    p.add_argument("--ogrn", help="ОГРН или ИНН: выписка будет получена с egrul.nalog.ru")
    p.add_argument("--file", help="уже скачанная выписка (путь от corporate/ или абсолютный)")
    p.set_defaults(func=cmd_group_sync)

    p = sub.add_parser("group-add", parents=[common], help="завести или изменить лицо в реестре группы")
    p.add_argument("--key", help="изменить существующее лицо (id, ОГРН, ИНН, рег. номер, имя)")
    p.add_argument("--kind", choices=gg.KINDS)
    p.add_argument("--name")
    p.add_argument("--short-name", dest="short_name")
    for field in ("ogrn", "inn", "country", "address"):
        p.add_argument(f"--{field}")
    p.add_argument("--reg-id", dest="reg_id", help="регистрационный номер иностранной компании")
    p.add_argument("--own-share", dest="own_share", help="доля в процентах, принадлежащая самому обществу")
    p.add_argument("--closed", help="дата или год прекращения деятельности")
    p.add_argument("--closed-reported", dest="closed_reported",
                   help="когда стало известно о закрытии (по умолчанию сегодня): год закрытия не позже этой даты")
    p.add_argument("--source", required=True)
    p.set_defaults(func=cmd_group_add)

    p = sub.add_parser("group-link", parents=[common], help="отрезок владения долей (владелец → общество)")
    p.add_argument("--owner", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--percent")
    p.add_argument("--nominal")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--share-date", dest="share_date")
    p.add_argument("--paid", help="сведения об оплате доли")
    p.add_argument("--basis", help="основание приобретения доли")
    p.add_argument("--source", required=True)
    p.set_defaults(func=cmd_group_link)

    p = sub.add_parser("group-officer", parents=[common], help="ЕИО или член совета директоров")
    p.add_argument("--key", help="изменить внесённую должность (id O-…): даты по документу или со слов юриста")
    p.add_argument("--person")
    p.add_argument("--company")
    p.add_argument("--role", choices=gg.ROLES)
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--title", help="наименование должности")
    p.add_argument("--source", required=True)
    p.set_defaults(func=cmd_group_officer)

    p = sub.add_parser("group-relative", parents=[common],
                       help="родственная связь физических лиц (п. 7 ч. 1 ст. 9 Закона № 135-ФЗ)")
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--relation", required=True)
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--source", required=True)
    p.set_defaults(func=cmd_group_relative)

    p = sub.add_parser("group-pbu11", parents=[common],
                       help="участник совместной деятельности или НПФ (п. 4 «б», «в» ПБУ 11/2008)")
    p.add_argument("--company", required=True)
    p.add_argument("--none", action="store_true",
                   help="таких лиц нет (ответ юриста или документ в --source): перечень покажет «нет» вместо маркера")
    p.add_argument("--name")
    p.add_argument("--ids", help="ОГРН, ИНН или иные реквизиты")
    p.add_argument("--basis")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--source", required=True)
    p.set_defaults(func=cmd_group_pbu11)

    p = sub.add_parser("group-show", parents=[common], help="реестр группы и аффилированные лица на дату")
    p.add_argument("--company")
    p.add_argument("--date")
    p.set_defaults(func=cmd_group_show)

    p = sub.add_parser("group-lists", parents=[common],
                       help="четыре черновика .docx: аффилированные лица, связанные стороны, участники, схема")
    p.add_argument("--company", required=True)
    p.add_argument("--date", help="дата списка (по умолчанию сегодня)")
    p.add_argument("--period-start", dest="period_start", required=True,
                   help="начало периода для журнала изменений и связанных сторон")
    p.add_argument("--related-start", dest="related_start",
                   help="начало периода перечня связанных сторон (отчётный период аудита; по умолчанию --period-start)")
    p.add_argument("--related-end", dest="related_end", help="конец периода перечня (по умолчанию --date)")
    p.add_argument("--related-without-leavers", dest="related_without_leavers", action="store_true",
                   help="в перечне только связанные на конец периода, без выбывших в периоде")
    p.add_argument("--out-dir", dest="out_dir", required=True)
    p.set_defaults(func=cmd_group_lists)
