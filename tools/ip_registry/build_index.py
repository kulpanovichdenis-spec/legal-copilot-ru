"""Markdown-индекс реестра ТЗ для агента. Контакты поверенных сюда не выводятся."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from pathlib import Path

from .normalize import RECORD_STATUS_LABELS, TERRITORY_STATUS_LABELS, number_key

DISCLAIMER = (
    "> Данные внутреннего реестра на дату выгрузки; статус в ФИПС/WIPO не сверялся. "
    "Пустой результат поиска = «в реестре не найдено», а не «охраны нет». "
    "Номер или статус, вынесенный в документ, — с маркером [СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ]."
)
INDEX_FILES = ("INDEX.md", "by-product.md", "by-country.md", "by-number.md", "renewals.md")


DOC_TYPE_LABELS = {
    "ru_certificate": "свидетельство РФ", "ru_registration_decision": "решение о регистрации РФ",
    "ru_refusal_decision": "решение об отказе РФ", "ru_renewal": "продление РФ",
    "ru_fips_card": "карточка ФИПС", "wipo_certificate": "сертификат МР",
    "wipo_grant": "предоставление охраны (WIPO)", "wipo_refusal": "отказ (WIPO)",
    "wipo_renewal": "продление МР", "wipo_madrid_page": "Madrid Monitor", "unknown": "документ",
}


def mark_label(mark: dict) -> str:
    return mark.get("mark_text") or "[изобразительный знак]"


def _date(value: str | None) -> str:
    return ".".join(reversed(value.split("-"))) if value else ""


def _one_line(value) -> str:
    return " ".join(("" if value is None else str(value)).splitlines())


def _cell(value) -> str:
    return _one_line(value).replace("|", "\\|")


def _primary_no(mark: dict) -> str:
    return mark["registration_no"] or mark["application_no"] or ""


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(item) for item in row) + " |" for row in rows]
    return lines


def _verified(mark: dict) -> str:
    check = mark.get("verification")
    return f" (сверено: {check['source']} {_date(check['checked'])})" if check else ""


def _countries(mark: dict) -> str:
    parts = []
    for territory in mark["territories"]:
        if territory["status"] == "protected":
            parts.append(territory["code"])
        else:
            parts.append(f"{territory['code']} ({TERRITORY_STATUS_LABELS[territory['status']]})")
    return (", ".join(parts) or "—") + _verified(mark)


def _latest_event(mark: dict, kinds: tuple[str, ...] | None = None):
    """Последнее не-seed событие знака по provenance: (поля, provenance-запись)."""
    best = None
    for field, prov in (mark.get("provenance") or {}).items():
        if kinds is not None and prov.get("kind") not in kinds:
            continue
        key = (prov.get("doc_date") or "", prov.get("event_id") or "")
        if best is None or key > best[0]:
            best = (key, prov)
    if best is None:
        return None
    event_id = best[1].get("event_id")
    fields = [f for f, p in mark["provenance"].items() if p.get("event_id") == event_id]
    return fields, best[1]


def _source_cell(mark: dict, registry: dict) -> str:
    found = _latest_event(mark)
    if found is None:
        return f"Excel {_date(registry['source']['exported'])}"
    _, prov = found
    date = _date(prov.get("doc_date"))
    if prov.get("kind") == "verification":
        check = mark.get("verification") or {}
        return " ".join(part for part in ("сверка", check.get("source"), date) if part)
    if prov.get("kind") == "document":
        return " ".join(part for part in ("документ", DOC_TYPE_LABELS.get(prov.get("doc_type"), prov.get("doc_type")), date) if part)
    return f"{prov.get('kind')} {date}".strip()


def _head(registry: dict, title: str) -> list[str]:
    source = registry["source"]
    return [
        f"# {title}",
        "",
        DISCLAIMER,
        "",
        f"Источник: `{source['file']}`, лист «{source['sheet']}», выгрузка {_date(source['exported'])}, "
        f"сборка {_date(source['built'])}.",
        "",
    ]


def _reg_type(mark: dict) -> str:
    return "Мадрид" if mark["reg_type"] == "madrid" else "нац."


def render_by_product(registry: dict) -> str:
    lines = _head(registry, "Товарные знаки по препаратам")
    groups: dict[str, list[dict]] = defaultdict(list)
    for mark in registry["marks"]:
        groups[mark["product"]].append(mark)
    for product in sorted(groups, key=str.casefold):
        lines += [f"## {product}", ""]
        rows = [[mark_label(m), _reg_type(m), _countries(m), m["registration_no"] or "",
                 m["application_no"] or "", ", ".join(map(str, m["nice_classes"])),
                 RECORD_STATUS_LABELS[m["status"]], _date(m["expiry_date"])]
                for m in sorted(groups[product], key=lambda m: mark_label(m).casefold())]
        lines += _table(["Знак", "Вид", "Страны", "№ рег.", "№ заявки", "Классы", "Статус", "Срок до"], rows)
        lines.append("")
    return "\n".join(lines)


def render_by_country(registry: dict) -> str:
    lines = _head(registry, "Товарные знаки по странам")
    groups: dict[tuple[str, str], list[tuple[dict, dict]]] = defaultdict(list)
    for mark in registry["marks"]:
        for territory in mark["territories"]:
            groups[(territory["name"], territory["code"])].append((mark, territory))
    for name, code in sorted(groups, key=lambda key: key[0].casefold()):
        lines += [f"## {name} ({code})", ""]
        rows = [[m["product"], mark_label(m), _primary_no(m),
                 TERRITORY_STATUS_LABELS[t["status"]] + _verified(m), t["basis"] or "", t["note"] or "",
                 _date(m["expiry_date"])]
                for m, t in sorted(groups[(name, code)], key=lambda pair: (pair[0]["product"].casefold(),
                                                                           mark_label(pair[0]).casefold()))]
        lines += _table(["Препарат", "Знак", "№", "Статус в стране", "Основание", "Примечание", "Срок до"], rows)
        lines.append("")
    return "\n".join(lines)


def render_by_number(registry: dict) -> str:
    lines = _head(registry, "Товарные знаки по номерам")
    lines += ["Ключ поиска — номер без пробелов и дефисов, кириллические буквы-двойники заменены латиницей.", ""]
    rows = []
    for mark in registry["marks"]:
        for kind, field in (("регистрация", "registration_no"), ("заявка", "application_no")):
            if mark[field]:
                rows.append([mark[field], number_key(mark[field]), kind, mark_label(mark), mark["product"],
                             _countries(mark), RECORD_STATUS_LABELS[mark["status"]],
                             _source_cell(mark, registry)])
    rows.sort(key=lambda row: row[1])
    lines += _table(["Номер", "Ключ", "Тип номера", "Знак", "Препарат", "Страны", "Статус", "Источник"], rows)
    return "\n".join(lines) + "\n"


def render_renewals(registry: dict) -> str:
    lines = _head(registry, "Продления и истечение сроков (действующие знаки)")
    built = dt.date.fromisoformat(registry["source"]["built"])
    year_later = built.replace(year=built.year + 1).isoformat() if not (built.month == 2 and built.day == 29) \
        else dt.date(built.year + 1, 2, 28).isoformat()
    events = []
    undated = []
    for mark in registry["marks"]:
        if mark["status"] != "active":
            continue
        dates: dict[str, list[str]] = defaultdict(list)
        if mark["next_payment_date"]:
            dates[mark["next_payment_date"]].append("оплата")
        if mark["expiry_date"]:
            dates[mark["expiry_date"]].append("истечение срока")
        if not dates:
            undated.append(mark)
        for date, what in dates.items():
            events.append((date, " / ".join(what), mark))
    events.sort(key=lambda item: item[0])

    def row(date: str | None, what: str, mark: dict) -> list:
        return [_date(date), what, mark_label(mark), mark["product"], _primary_no(mark), _countries(mark)]

    blocks = [
        ("Просрочено (раньше даты сборки)",
         [row(d, w, m) for d, w, m in events if d < built.isoformat()]),
        ("Ближайшие 12 месяцев",
         [row(d, w, m) for d, w, m in events if built.isoformat() <= d <= year_later]),
        ("Позже",
         [row(d, w, m) for d, w, m in events if d > year_later]),
        ("Срок не указан",
         [row(None, "не указано", m) for m in undated]),
    ]
    for title, rows in blocks:
        lines += [f"## {title}", ""]
        lines += _table(["Дата", "Что", "Знак", "Препарат", "№", "Страны"], rows) if rows else ["Нет."]
        lines.append("")
    return "\n".join(lines)


def render_index(registry: dict) -> str:
    stats = registry["stats"]
    lines = _head(registry, "Реестр товарных знаков — навигатор")
    source = registry["source"]
    if source.get("events") is not None:
        lines += [f"Журнал: событий в журнале: {source['events']}, последнее изменение: "
                  f"{_date(source.get('last_change')) or 'нет'}.", ""]
    lines += [
        f"Знаков: {stats['marks']}; с изображением: {stats['with_image']}; предупреждений разбора: {stats['warnings']}.",
        "",
        "| Вопрос | Файл / команда |",
        "|---|---|",
        "| Чей номер, что за знак | `by-number.md` или `python -m tools.ip_registry query --number <N>` |",
        "| Где охраняется препарат | `by-product.md` или `query --product <имя>` |",
        "| Что есть в стране | `by-country.md` или `query --country <ISO>` |",
        "| Что продлевать | `renewals.md` |",
        "| Полная запись знака | только `python -m tools.ip_registry query`; `data/base.json`, `data/events.jsonl` "
        "и `catalog.html` агент не открывает (там контакты поверенных) |",
        "| Каталог для юриста | `catalog.html` открывает юрист |",
        "",
        "Каталог `profile/knowledge/ip/` в `.gitignore`: искать через Glob+Read или CLI, не Grep-инструментом.",
    ]
    if stats.get("no_product"):
        lines += ["", f"Препарат не указан: {stats['no_product']} знаков (препарат нового знака не угадывается)."]
    pending = registry.get("pending") or []
    lines += ["", "## Ждут решения юриста", ""]
    lines += _table(["Документ", "Статус", "Причина"],
                    [[p.get("document"), p.get("status"), p.get("reason")] for p in pending]) if pending else ["Нет."]
    recent = []
    for mark in registry["marks"]:
        found = _latest_event(mark, ("document",))
        if found:
            recent.append((found[1].get("doc_date") or "", found[1].get("event_id") or "", mark, found))
    recent.sort(key=lambda item: item[:2], reverse=True)
    lines += ["", "## Последние изменения из документов", ""]
    lines += _table(["Знак", "Препарат", "№", "Поля", "Документ", "Дата"],
                    [[mark_label(m), m["product"], _primary_no(m), ", ".join(f[0]), f[1].get("file") or "",
                      _date(f[1].get("doc_date"))] for _, _, m, f in recent[:10]]) if recent else ["Нет."]
    unresolved = []
    for mark in registry["marks"]:
        found = [w for w in mark.get("warnings", [])
                 if w.startswith(("страны не распознаны", "неизвестный код страны",
                                       "фрагменты территории не разобраны",
                                       "в «Государстве действия» другие страны"))]
        if found or not mark["territories"]:
            unresolved.append([mark_label(mark), mark["product"], _primary_no(mark),
                               "; ".join(found) or "территория пуста"])
    lines += ["", "## Знаки с нераспознанной территорией", ""]
    lines += _table(["Знак", "Препарат", "№", "Предупреждение"], unresolved) if unresolved else ["Нет."]
    verified = [m for m in registry["marks"] if m.get("verification")]
    if verified:
        lines += ["", "## Сверено с ведомствами", "",
                  "Для этих знаков статусы по странам взяты из проверки в ведомстве на указанную дату "
                  "(по данным ведомства на дату сверки), а не из внутреннего реестра; регистрационные данные "
                  "(сроки, классы) остаются по реестру.", ""]
        lines += _table(["Знак", "Препарат", "№", "Источник", "Дата сверки"],
                        [[mark_label(m), m["product"], _primary_no(m), m["verification"]["source"],
                          _date(m["verification"]["checked"])] for m in verified])
    if registry["warnings"]:
        lines += ["", "## Общие предупреждения разбора", ""] + [f"- {_one_line(item)}" for item in registry["warnings"]]
    return "\n".join(lines) + "\n"


_RENDERERS = {
    "INDEX.md": render_index,
    "by-product.md": render_by_product,
    "by-country.md": render_by_country,
    "by-number.md": render_by_number,
    "renewals.md": render_renewals,
}


def write_index(registry: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in INDEX_FILES:
        path = out_dir / name
        path.write_text(_RENDERERS[name](registry), encoding="utf-8")
        written.append(path)
    return written
