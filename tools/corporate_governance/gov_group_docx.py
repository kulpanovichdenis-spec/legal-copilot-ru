# -*- coding: utf-8 -*-
"""Документы по реестру группы: список аффилированных лиц ООО, перечень связанных сторон для
аудитора (ПБУ 11/2008), список участников (ст. 31.1 Закона № 14-ФЗ), схема владения.

Профиль «аналитическая заметка» (tools/docx_style.NoteDoc) на альбомной странице. Схема
рисуется в SVG и переводится в PNG через PyMuPDF, без новых зависимостей. Модуль раскладывает
результат расчёта (gov_group_calc) по графам и ничего не дописывает от себя: чего нет в
реестре, то стоит маркером. Все документы — черновики; подписывает ЕИО после проверки юристом.
"""
from __future__ import annotations

import datetime as dt
import html
import io
import re
import sys
import textwrap
from pathlib import Path

from docx.enum.section import WD_ORIENT
from docx.shared import Cm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_group as gg  # noqa: E402
import gov_group_calc as calc  # noqa: E402
import gov_store as store  # noqa: E402

if str(store.ROOT) not in sys.path:
    sys.path.insert(0, str(store.ROOT))
from tools.docx_style.profiles import NoteDoc  # noqa: E402

MARK = "[ПРОВЕРИТЬ ФАКТ]"
DRAFT = "Черновик. Проверяет юрист, подписывает единоличный исполнительный орган; документ никуда не направлен"
SHORT = {"eio": "ЕИО общества", "board": "член совета директоров", "holds_20": "более 20 % голосов в обществе",
         "held_20": "у общества более 20 % голосов в лице", "group": "группа лиц"}
LAW_948 = "ст. 4 Закона РСФСР от 22.03.1991 № 948-1"
PBU = "п. 4 ПБУ 11/2008 (приказ Минфина России от 29.04.2008 № 48н)"
LAW_14 = "п. 1 ст. 31.1 Федерального закона от 08.02.1998 № 14-ФЗ"
NOTES_HEADING = "Для юриста (удалить перед подписанием)"
_BAD_CHARS = re.compile(r'[<>:"/\\|?*]')


# ---------- общее ----------

def _landscape(d: NoteDoc) -> NoteDoc:
    section = d.doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Cm(29.7), Cm(21.0)
    d.text_width_cm = 29.7 - d.p["margins_cm"][0] - d.p["margins_cm"][1]
    return d


def _doc(header: str, *, landscape: bool = True) -> NoteDoc:
    d = _landscape(NoteDoc()) if landscape else NoteDoc()
    d.header(header)
    return d


def _widths(d: NoteDoc, weights: list[float]) -> list[float]:
    total = sum(weights)
    return [d.body_width_cm * w / total for w in weights]


def full_name(entity: dict) -> str:
    name = " ".join(str(entity["name"]).split())
    if entity.get("kind") == "person":
        return gg.label(entity)
    return re.sub(r'"\s*([^"]*?)\s*"', r"«\1»", name)


def _reg_id(value: str | None) -> str:
    """Иностранный номер: с собственной подписью («БИН …») как есть, голый номер — «рег. № …»."""
    if not value:
        return ""
    return value if not value[0].isdigit() else f"рег. № {value}"


def _ids(entity: dict) -> str:
    if entity["kind"] == "person":
        return "—"
    parts = [f"ОГРН {entity['ogrn']}" if entity.get("ogrn") else "",
             f"ИНН {entity['inn']}" if entity.get("inn") else "",
             _reg_id(entity.get("reg_id"))]
    if entity.get("country") and entity["country"] != "Россия":
        parts.append(entity["country"])
    if entity.get("status") == "closed":
        parts.append(f"деятельность прекращена: {gg.fmt_date(entity.get('closed')) or MARK}")
    return "\n".join(p for p in parts if p) or MARK


def _numbered(items: list[str]) -> str:
    return items[0] if len(items) == 1 else "\n".join(f"{n}) {item}" for n, item in enumerate(items, 1))


def _company_lines(company: dict) -> str:
    return ", ".join(p for p in (f"ОГРН {company['ogrn']}" if company.get("ogrn") else "",
                                 f"ИНН {company['inn']}" if company.get("inn") else "") if p) or MARK


def _eio(data: dict, cid: str, day: dt.date) -> tuple[str, str]:
    by_id = gg.entities_by_id(data)
    offices = [o for o in calc._offices_at(data, day) if o["company"] == cid and o["role"] == "eio"]
    if not offices:
        return "Единоличный исполнительный орган", MARK
    office = offices[0]
    title = (office.get("title") or "Единоличный исполнительный орган").capitalize()
    return title, gg.label(by_id[office["person"]])


def _signature(d: NoteDoc, data: dict, cid: str, day: dt.date) -> None:
    title, name = _eio(data, cid, day)
    d.para("")
    d.para(f"{title} ____________________ / {name} /", keep_next=True)
    d.para("Дата подписания: «___» __________ 20__ г.")


def _share(holdings: list[dict], owner: str, target: str) -> str:
    found = [h for h in holdings if h["owner"] == owner and h["target"] == target]
    if not found:
        return "—"
    return gg.fmt_percent(found[0]["percent"]) or MARK


def _sources(data: dict, ids: set[str]) -> list[str]:
    seen: list[str] = []
    records = [e for e in data["entities"] if e["id"] in ids]
    records += [l for l in data["links"] if l["owner"] in ids or l["target"] in ids]
    records += [o for o in data["offices"] if o["company"] in ids or o["person"] in ids]
    for record in records:
        # «документ (файл): подробности; ещё документ» → документы без подробностей, без повторов
        for part in str(record.get("source") or "").split("; "):
            head = part.split(": ")[0].strip()
            if head and head not in seen:
                seen.append(head)
    return seen


def _notes(d: NoteDoc, lines: list[str], sources: list[str]) -> None:
    d.heading(NOTES_HEADING, 2)
    for line in lines:
        d.bullet(f"[для юриста: {line}]")
    if sources:
        d.bullet("[для юриста: источники сведений реестра группы: " + "; ".join(sources) + "]")


def _file_name(kind: str, company: dict, tail: str) -> str:
    return _BAD_CHARS.sub("", f"{kind} {gg.label(company)} {tail} (черновик).docx")


# ---------- список аффилированных лиц ----------

def affiliate_table_rows(data: dict, cid: str, day: dt.date) -> list[list[str]]:
    holdings = calc.holdings_at(data, day)
    rows = []
    for n, row in enumerate(calc.affiliate_rows(data, cid, day), 1):
        entity = row["entity"]
        rows.append([
            str(n), full_name(entity), _ids(entity),
            _numbered([b["text"] for b in row["bases"]]),
            row["detail"] or "—",
            _numbered([b["since_text"] or MARK for b in row["bases"]]),
            _share(holdings, entity["id"], cid), _share(holdings, cid, entity["id"]),
        ])
    return rows


def _state_text(state: dict | None) -> str:
    if not state:
        return "—"
    parts = [SHORT[c] for c in calc.CODE_ORDER if c in state["codes"]]
    if state["holds"] is not None:
        parts.append(f"доля лица в обществе {gg.fmt_percent(state['holds'])}")
    if state["held"] is not None:
        parts.append(f"доля общества в лице {gg.fmt_percent(state['held'])}")
    return "; ".join(parts)


CHANGE_TEXT = {"include": "Включение в список", "exclude": "Исключение из списка", "change": "Изменение сведений"}


def build_affiliates(data: dict, cid: str, day: dt.date, start: dt.date, out: str) -> str:
    company = gg.require_entity(data, cid)
    cid = company["id"]
    d = _doc(f"Список аффилированных лиц {gg.label(company)} на {gg.fmt_date(day)} (черновик)")
    d.title("Список аффилированных лиц", full_name(company), _company_lines(company),
            f"по состоянию на {gg.fmt_date(day)}")
    d.para(DRAFT)
    d.heading("Раздел I. Состав аффилированных лиц на " + gg.fmt_date(day))
    rows = affiliate_table_rows(data, cid, day)
    header = ["№", "Наименование (ФИО)", "ОГРН, ИНН, страна", "Основание (основания), " + LAW_948,
              "Пояснение (цепочка группы лиц)", "Дата наступления основания", "Доля лица в уставном капитале общества",
              "Доля общества в уставном капитале лица"]
    if rows:
        d.table(header, rows, _widths(d, [0.7, 3.6, 2.8, 5.0, 6.4, 2.2, 2.0, 2.0]), center_cols=(0, 5, 6, 7))
    else:
        d.para("Аффилированных лиц по реестру группы нет " + MARK)
    d.heading(f"Раздел II. Изменения за период с {gg.fmt_date(start)} по {gg.fmt_date(day)}")
    log = calc.changes(data, cid, start, day)
    if log:
        d.table(["№", "Лицо", "Содержание изменения", "Дата изменения", "Было", "Стало"],
                [[str(n), full_name(c["entity"]), CHANGE_TEXT[c["kind"]], c["date_text"],
                  _state_text(c["before"]), _state_text(c["after"])] for n, c in enumerate(log, 1)],
                _widths(d, [0.7, 4.5, 3.0, 2.6, 6.2, 6.2]), center_cols=(0, 3))
    else:
        d.para("Изменений за период по реестру группы нет.")
    _signature(d, data, cid, day)
    involved = {cid} | {r["entity"]["id"] for r in calc.affiliate_rows(data, cid, day)}
    _notes(d, [
        f"список рассчитан по реестру группы на {gg.fmt_date(day)}; группа лиц определена по пп. 1, 2, 7, 8, 9 "
        "ч. 1 ст. 9 Закона № 135-ФЗ, признаки пп. 3–6 не проверялись, родственники учтены только внесённые в реестр",
        "цепочки п. 8 замыкаются полностью; дата основания означает начало непрерывного периода по датам записей реестра",
        "дата с пометкой «не позднее» установлена по дате выписки ЕГРЮЛ, в которой связи уже нет; точную дату "
        "взять из документа",
    ], _sources(data, involved))
    d.footer()
    return d.save(out)


# ---------- перечень связанных сторон ----------

def build_related(data: dict, cid: str, start: dt.date, end: dt.date, out: str, *, leavers: bool = True) -> str:
    """leavers=False: только лица, связанные на конец периода (выбывшие в периоде не включаются)."""
    company = gg.require_entity(data, cid)
    cid = company["id"]
    period = f"с {gg.fmt_date(start)} по {gg.fmt_date(end)}"
    d = _doc(f"Перечень связанных сторон {gg.label(company)} {period} (черновик)")
    d.title("Перечень связанных сторон", full_name(company), _company_lines(company), f"за период {period}")
    d.para(DRAFT)
    d.para(f"Связанные стороны определены по {PBU}: лица, признаваемые аффилированными лицами общества "
           f"({LAW_948}) в любой момент периода, а также участники совместной деятельности и негосударственные "
           "пенсионные фонды. " + ("Лицо, переставшее быть аффилированным в течение периода, указано с датой окончания."
                                   if leavers else "Состав на конец периода: выбывшие в течение периода не включены."))
    parties = calc.related_parties(data, cid, start, end)
    if not leavers:
        parties = [p for p in parties if p["until"] is None or p["until"] > end]
    rows = []
    for n, p in enumerate(parties, 1):
        if p["other"]:
            rows.append([str(n), p["other"]["name"], p["other"].get("ids") or "—", p["other"]["basis"], "—",
                         p["since_text"] or MARK, p["until_text"] or "—"])
            continue
        rows.append([str(n), full_name(p["entity"]), _ids(p["entity"]),
                     _numbered([calc.BASIS_TEXT[c] for c in p["codes"]]), p["detail"] or "—",
                     p["since_text"] or MARK, p["until_text"] or "—"])
    if rows:
        d.table(["№", "Наименование (ФИО)", "ОГРН, ИНН, страна", "Основание", "Пояснение",
                 "Связанная сторона с", "по"], rows, _widths(d, [0.7, 3.8, 2.8, 5.6, 6.6, 2.2, 2.0]),
                center_cols=(0, 5, 6))
    else:
        d.para("Связанных сторон по реестру группы нет " + MARK)
    if not any(p["other"] for p in parties):
        answer = f"нет ({company['pbu11_none']})" if company.get("pbu11_none") else f"в реестр группы не внесены {MARK}"
        d.para("Участники совместной деятельности и негосударственные пенсионные фонды (п. 4 «б», «в» "
               f"ПБУ 11/2008): {answer}.")
    _signature(d, data, cid, end)
    involved = {cid} | {p["entity"]["id"] for p in parties if p["entity"]}
    _notes(d, [
        "перечень для аудитора; состав аффилированных лиц рассчитан по реестру группы на каждую дату события "
        "в периоде, как в списке аффилированных лиц",
        "подпункт «а» п. 4 ПБУ 11/2008 при подготовке модуля дословно не открылся, его объём сверить с "
        "первоисточником [СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ]",
    ], _sources(data, involved))
    d.footer()
    return d.save(out)


# ---------- список участников ----------

def _participant_since(data: dict, link: dict) -> str | None:
    """Начало непрерывного участия: отрезки того же владельца, примыкающие друг к другу."""
    same = {l.get("until"): l for l in data["links"]
            if l["owner"] == link["owner"] and l["target"] == link["target"] and l.get("until")}
    current = link
    while current.get("since") in same:
        current = same[current["since"]]
    return current.get("since")


def build_participants(data: dict, cid: str, day: dt.date, out: str) -> str:
    company = gg.require_entity(data, cid)
    cid = company["id"]
    by_id = gg.entities_by_id(data)
    d = _doc(f"Список участников {gg.label(company)} на {gg.fmt_date(day)} (черновик)")
    d.title("Список участников", full_name(company), _company_lines(company), f"по состоянию на {gg.fmt_date(day)}")
    d.para(DRAFT)
    d.para(f"Сведения об участниках общества, размере их долей и оплате, о долях, принадлежащих обществу ({LAW_14}). "
           f"Доли и даты записей сверены с реестром группы; источник сведений об обществе: {company.get('source') or MARK}.")
    holdings = [h for h in calc.holdings_at(data, day) if h["target"] == cid]
    rows, total = [], 0
    for n, h in enumerate(sorted(holdings, key=lambda h: -(h["percent"] or 0)), 1):
        owner, link = by_id[h["owner"]], h["link"]
        details = _ids(owner) if owner["kind"] == "company" else "—"
        if owner.get("address"):
            details += f"\n{owner['address']}"
        total += h["percent"] or 0
        rows.append([str(n), full_name(owner), details, gg.fmt_percent(h["percent"]) or MARK,
                     gg.fmt_money(link.get("nominal")) or MARK, link.get("paid") or MARK,
                     gg.fmt_date(_participant_since(data, link)) or MARK,
                     gg.fmt_date(link.get("share_date")) or "—", link.get("basis") or MARK])
    own = gg.percent(company.get("own_share"))
    if own:
        total += own
        rows.append([str(len(rows) + 1), "Доля, принадлежащая обществу", "—", gg.fmt_percent(own), "—", "—",
                     f"дата перехода к обществу: {MARK}", "—", MARK])
    if rows:
        d.table(["№", "Участник", "ОГРН, ИНН, адрес", "Размер доли", "Номинальная стоимость, руб.", "Оплата",
                 "Участник с (запись ЕГРЮЛ)", "Размер доли по записи ЕГРЮЛ от", "Основание приобретения"],
                rows, _widths(d, [0.7, 4.2, 4.4, 1.8, 2.2, 2.4, 2.6, 2.4, 3.2]), center_cols=(0, 3, 4, 6, 7))
        d.para(f"Итого: {gg.fmt_percent(total)}" + ("" if total == 100 else f" {MARK}"))
    else:
        d.para("Участников по реестру группы на эту дату нет " + MARK)
    _signature(d, data, cid, day)
    _notes(d, [
        "оплата долей и основания приобретения в выписке ЕГРЮЛ не видны: заполнить по документам общества",
        "отрезок «доля до записи ЕГРЮЛ о текущем размере не видна» означает, что прежний размер доли "
        "в реестр не внесён",
    ], _sources(data, {cid} | {h["owner"] for h in holdings}))
    d.footer()
    return d.save(out)


# ---------- схема владения ----------

BOX_W, BOX_H, GAP_X, GAP_Y, PAD, LANE_W = 200, 52, 30, 70, 24, 36
MIN_SCALE_CM, MAX_SCALE_CM = 0.026, 0.032  # см на единицу SVG: шрифт 11,5 даёт ~8,5 и ~10,5 пт
TITLE_RESERVE_CM = 4.0  # заголовок, подзаголовки и строка о черновике над рисунком
FONT = 'font-family="Arial"'  # у каждого <text>: MuPDF не наследует шрифт от <svg>


def _scheme_edges(data: dict, cid: str, day: dt.date) -> tuple[list[dict], set[str]]:
    members = calc.group_at(data, day).members(cid)
    edges = [h for h in calc.holdings_at(data, day) if h["target"] in members or h["owner"] in members]
    return edges, {h["owner"] for h in edges} | {h["target"] for h in edges}


def _levels(nodes: set[str], edges: list[dict]) -> dict[str, int]:
    level = {n: 0 for n in nodes}
    for _ in range(len(nodes)):  # длиннейший путь от владельцев; цикл в данных не зациклит расчёт
        changed = False
        for h in edges:
            if level[h["target"]] < level[h["owner"]] + 1:
                level[h["target"]] = level[h["owner"]] + 1
                changed = True
        if not changed:
            break
    return level


def _box_lines(entity: dict) -> list[str]:
    lines = textwrap.wrap(gg.label(entity), 26)[:3]
    if entity["kind"] == "company":
        lines.append(f"ОГРН {entity['ogrn']}" if entity.get("ogrn") else (entity.get("country") or ""))
    return [line for line in lines if line]


def _layout(nodes: set[str], edges: list[dict], by_id: dict) -> tuple[dict, dict, list[list[str]], float]:
    """Ряды по уровням; связь через несколько уровней получает промежуточные «полосы» в каждом ряду,
    чтобы линия шла между блоками, а не сквозь них. Порядок в ряду — по среднему положению владельцев."""
    level = _levels(nodes, edges)
    rows: list[list[str]] = [[] for _ in range(max(level.values()) + 1)]
    for node in sorted(nodes, key=lambda n: gg.label(by_id[n])):
        rows[level[node]].append(node)
    chains, parents = [], {}
    for i, h in enumerate(edges):
        chain = [h["owner"]]
        for lvl in range(level[h["owner"]] + 1, level[h["target"]]):
            lane = f"lane:{i}:{lvl}"
            rows[lvl].append(lane)
            parents[lane] = [chain[-1]]
            chain.append(lane)
        parents.setdefault(h["target"], []).append(chain[-1])
        chains.append(chain + [h["target"]])
    width_of = lambda n: LANE_W if n.startswith("lane:") else BOX_W  # noqa: E731
    x: dict[str, float] = {}

    def centre(node: str) -> float:
        known = [x[p] + width_of(p) / 2 for p in parents.get(node, []) if p in x]
        return sum(known) / len(known) if known else 0.0

    for lvl, row in enumerate(rows):
        if lvl:
            row.sort(key=centre)
        pos = 0.0
        for node in row:
            x[node] = pos
            pos += width_of(node) + GAP_X
    width = max(sum(width_of(n) + GAP_X for n in row) - GAP_X for row in rows if row) + 2 * PAD
    for row in rows:  # ряды центрируются по ширине рисунка
        used = sum(width_of(n) + GAP_X for n in row) - GAP_X
        for node in row:
            x[node] += PAD + (width - 2 * PAD - used) / 2
    y = {n: PAD + lvl * (BOX_H + GAP_Y) for lvl, row in enumerate(rows) for n in row}
    return x, y, chains, width


def _arrow(x1: float, y1: float, x2: float, y2: float) -> str:
    """Наконечник стрелки многоугольником (маркеры SVG MuPDF не рисует)."""
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    ux, uy = dx / length, dy / length
    bx, by = x2 - ux * 10, y2 - uy * 10
    left, right = (bx - uy * 4.5, by + ux * 4.5), (bx + uy * 4.5, by - ux * 4.5)
    return (f'<polygon points="{x2:.1f},{y2:.1f} {left[0]:.1f},{left[1]:.1f} {right[0]:.1f},{right[1]:.1f}" '
            'fill="#333"/>')


def scheme_svg(data: dict, cid: str, day: dt.date) -> str:
    by_id = gg.entities_by_id(data)
    edges, nodes = _scheme_edges(data, cid, day)
    nodes = nodes or {cid}
    x, y, chains, width = _layout(nodes, edges, by_id)
    height = max(y.values()) + BOX_H + PAD
    # точки выхода и входа разнесены по краю блока в порядке соседних точек цепочки
    outs, ins = {}, {}
    for i, chain in enumerate(chains):
        outs.setdefault(chain[0], []).append((x[chain[1]], i))
        ins.setdefault(chain[-1], []).append((x[chain[-2]], i))
    attach_out, attach_in = {}, {}
    for table, store_to in ((outs, attach_out), (ins, attach_in)):
        for node, items in table.items():
            for k, (_, i) in enumerate(sorted(items)):
                store_to[i] = x[node] + BOX_W * (k + 1) / (len(items) + 1)
    top = set(calc.ultimate_owners(data, day)) & nodes
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
           f'viewBox="0 0 {width:.0f} {height:.0f}">',
           f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="white"/>']
    labels = []
    for i, (h, chain) in enumerate(zip(edges, chains)):
        points = [(attach_out[i], y[chain[0]] + BOX_H)]
        for lane in chain[1:-1]:
            centre = x[lane] + LANE_W / 2
            points += [(centre, y[lane]), (centre, y[lane] + BOX_H)]
        points.append((attach_in[i], y[chain[-1]]))
        path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        out.append(f'<polyline points="{path}" fill="none" stroke="#333" stroke-width="1.4"/>')
        out.append(_arrow(*points[-2], *points[-1]))
        (x1, y1), (x2, y2) = points[0], points[1]
        mx, my = x1 + (x2 - x1) * 0.45, y1 + (y2 - y1) * 0.45
        text = html.escape(gg.fmt_percent(h["percent"]) or "?")
        labels.append(f'<rect x="{mx - 30:.0f}" y="{my - 9:.0f}" width="60" height="16" fill="white"/>'
                      f'<text x="{mx:.0f}" y="{my + 4:.0f}" {FONT} font-size="11" text-anchor="middle">{text}</text>')
    out += labels  # подписи поверх всех линий
    for node in nodes:
        entity = by_id[node]
        rx = 16 if entity["kind"] == "person" else 3
        stroke = 3 if node in top else 1.2
        fill = "#ececec" if node == cid else "white"
        out.append(f'<rect x="{x[node]:.0f}" y="{y[node]:.0f}" width="{BOX_W}" height="{BOX_H}" rx="{rx}" '
                   f'fill="{fill}" stroke="#222" stroke-width="{stroke}"/>')
        lines = _box_lines(entity)
        first = y[node] + BOX_H / 2 - (len(lines) - 1) * 6.5 + 4
        for k, line in enumerate(lines):
            size = 9.5 if line.startswith("ОГРН") else 11.5
            out.append(f'<text x="{x[node] + BOX_W / 2:.0f}" y="{first + k * 13:.0f}" {FONT} font-size="{size}" '
                       f'text-anchor="middle">{html.escape(line)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def scheme_png(svg: str) -> bytes:
    import fitz  # noqa: PLC0415 — PyMuPDF нужен только для отрисовки схемы

    with fitz.open(stream=svg.encode("utf-8"), filetype="svg") as doc:
        return doc[0].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")


def build_scheme(data: dict, cid: str, day: dt.date, out: str) -> str:
    company = gg.require_entity(data, cid)
    cid = company["id"]
    by_id = gg.entities_by_id(data)
    svg = scheme_svg(data, cid, day)
    match = re.search(r'width="(\d+)" height="(\d+)"', svg)
    svg_w, svg_h = int(match.group(1)), int(match.group(2))
    ratio = svg_h / svg_w
    # высокий рисунок на книжной странице, широкий на альбомной: так шрифт схемы остаётся читаемым
    d = _doc(f"Схема владения группы {gg.label(company)} на {gg.fmt_date(day)} (черновик)", landscape=ratio < 0.8)
    d.title("Схема владения", f"группа лиц {full_name(company)}", f"по состоянию на {gg.fmt_date(day)}")
    d.para(DRAFT)
    section = d.doc.sections[0]
    text_height_cm = (section.page_height - section.top_margin - section.bottom_margin) / 360000
    width_cm = min(d.text_width_cm, (text_height_cm - TITLE_RESERVE_CM) / ratio, svg_w * MAX_SCALE_CM)
    d.doc.add_picture(io.BytesIO(scheme_png(svg)), width=Cm(width_cm))
    edges, nodes = _scheme_edges(data, cid, day)
    top = [by_id[n] for n in calc.ultimate_owners(data, day) if n in nodes]
    d.para("Конечный владелец (у лица нет владельцев в реестре группы, на схеме выделен жирной рамкой): "
           + ("; ".join(full_name(e) for e in top) or MARK) + ". Стрелка идёт от владельца к обществу, "
           "подпись на стрелке показывает долю в уставном капитале; общество, для которого составлена схема, выделено фоном.")
    rows = []
    for n, h in enumerate(sorted(edges, key=lambda h: (gg.label(by_id[h["target"]]), -(h["percent"] or 0))), 1):
        target, link = by_id[h["target"]], h["link"]
        rows.append([str(n), full_name(by_id[h["owner"]]), full_name(target), _ids(target),
                     gg.fmt_percent(h["percent"]) or MARK, gg.fmt_date(_participant_since(data, link)) or MARK,
                     link.get("note") or "—"])
    if rows:
        d.heading("Связи владения", 2)
        d.table(["№", "Владелец", "Общество", "ОГРН, ИНН, страна", "Доля", "Участник с", "Примечание"], rows,
                _widths(d, [0.7, 5.0, 5.0, 3.6, 1.8, 2.2, 4.4]), center_cols=(0, 4, 5))
    _notes(d, ["на схеме только владение долями; должности (ЕИО) и родственные связи показаны в списке "
               "аффилированных лиц"], _sources(data, nodes))
    d.footer()
    return d.save(out)


# ---------- комплект ----------

def build_all(data: dict, cid: str, day: dt.date, start: dt.date, out_dir: str, *,
              related: tuple[dt.date, dt.date] | None = None, related_leavers: bool = True) -> list[str]:
    """Четыре документа в out_dir; имена файлов с наименованием общества и датой. Перечень связанных
    сторон — за related (отчётный период аудита), по умолчанию за тот же период, что журнал изменений."""
    company = gg.require_entity(data, cid)
    cid, folder = company["id"], Path(out_dir)
    on = f"на {gg.fmt_date(day)}"
    rel_start, rel_end = related or (start, day)
    return [
        build_affiliates(data, cid, day, start, str(folder / _file_name("Список аффилированных лиц", company, on))),
        build_related(data, cid, rel_start, rel_end, str(folder / _file_name(
            "Перечень связанных сторон", company, f"с {gg.fmt_date(rel_start)} по {gg.fmt_date(rel_end)}")),
            leavers=related_leavers),
        build_participants(data, cid, day, str(folder / _file_name("Список участников", company, on))),
        build_scheme(data, cid, day, str(folder / _file_name("Схема владения группы", company, on))),
    ]
