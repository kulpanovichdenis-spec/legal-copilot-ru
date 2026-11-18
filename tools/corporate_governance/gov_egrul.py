# -*- coding: utf-8 -*-
"""Выписка из ЕГРЮЛ: получение с egrul.nalog.ru и разбор текстового слоя.

Официальный сервис ФНС «Предоставление сведений из ЕГРЮЛ/ЕГРИП в электронном
виде» отдаёт выписку в PDF по ОГРН или ИНН. fetch_extract повторяет шаги формы
сайта (поиск, запрос выписки, статус, скачивание), передаёт только публичный
идентификатор и представляется своим User-Agent. Капчу не обходит: если ФНС её
запросила, выписку получают вручную (EgrulUnavailable с причиной).

parse_pages / parse_pdf разбирают текстовый слой PDF ФНС построчно: реквизиты и
адрес общества, дата регистрации, лица, действующие без доверенности, участники
(с датами записей об участнике и о размере доли), доля, принадлежащая обществу,
записи ЕГРЮЛ с признаком «изменение учредительного документа». Колонтитулы страниц
отбрасываются. Правовых выводов модуль не делает: сравнение с уставом выполняет
команда check-edition.
"""
from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://egrul.nalog.ru"
USER_AGENT = "legal-copilot/1.0 (corporate-governance; egrul extract)"

REASON = "Причина внесения записи в ЕГРЮЛ"
RECORD_GRN = "ГРН и дата внесения записи в ЕГРЮЛ"
PERSON_HEADER = "ГРН и дата внесения в ЕГРЮЛ сведений о"
MANAGERS_HEADING = "Сведения о лице, имеющем право без доверенности"
PARTICIPANTS_HEADING = "Сведения об участниках / учредителях"
COMPANY_SHARE_HEADING = "Сведения о доле в уставном капитале общества"
RECORD_GRN_FIELD = "ГРН и дата внесения в ЕГРЮЛ записи"
MANAGERS_STOP = ("Сведения об уставном", "Сведения об участниках", "Сведения об учете", "Сведения о держателе",
                 "Сведения о записях", "Сведения об управляющей", "Сведения о видах")
PARTICIPANTS_STOP = (COMPANY_SHARE_HEADING, "Сведения об учете", "Сведения о регистрации", "Сведения о видах", "Сведения о лицензиях",
                     "Сведения о записях", "Сведения о держателе", "Сведения о филиалах",
                     "Сведения о представительствах", "Сведения о правопредшественнике",
                     "Сведения о правопреемнике")

_FOOTER_RE = re.compile(r"(?m)^Страница \d+ из")
_DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_GRN_RE = re.compile(r"\d{13}|\d{15}")


class EgrulUnavailable(Exception):
    """Выписку не удалось получить автоматически (сеть, капча, неоднозначный поиск)."""


class NotEgrulExtract(ValueError):
    """Документ не похож на выписку из ЕГРЮЛ."""


# ---------- разбор текстового слоя ----------

def _iso(ddmmyyyy: str) -> str:
    day, month, year = ddmmyyyy.split(".")
    return f"{year}-{month}-{day}"


def page_lines(pages: list[str]) -> list[tuple[int, str]]:
    """(номер страницы, строка) без колонтитулов и пустых строк; пробелы схлопнуты."""
    out: list[tuple[int, str]] = []
    for number, text in enumerate(pages, start=1):
        footer = _FOOTER_RE.search(text)
        body = text[:footer.start()] if footer else text
        for raw in body.splitlines():
            line = " ".join(raw.split())
            if line:
                out.append((number, line))
    return out


def _is_row(line: str) -> bool:
    """Номер строки или записи в таблице выписки (короткое число), а не значение."""
    return line.isdigit() and len(line) <= 4


def _text_after(lines: list[tuple[int, str]], i: int) -> str:
    """Многострочное текстовое значение после метки — до следующего номера строки."""
    values = []
    j = i + 1
    while j < len(lines) and not _is_row(lines[j][1]):
        values.append(lines[j][1])
        j += 1
    return " ".join(values)


def _value_after(lines: list[tuple[int, str]], i: int) -> str | None:
    return lines[i + 1][1] if i + 1 < len(lines) else None


def _grn_date_after(lines: list[tuple[int, str]], i: int) -> tuple[str | None, str | None]:
    """ГРН (если указан) и дата после метки; продолжение многострочной метки пропускается."""
    j = i + 1
    while (j < len(lines) and not _GRN_RE.fullmatch(lines[j][1]) and not _DATE_RE.fullmatch(lines[j][1])
           and not _is_row(lines[j][1])):
        j += 1
    grn = date = None
    if j < len(lines) and _GRN_RE.fullmatch(lines[j][1]):
        grn = lines[j][1]
        j += 1
    if j < len(lines) and _DATE_RE.fullmatch(lines[j][1]):
        date = _iso(lines[j][1])
    return grn, date


def _find(lines: list[tuple[int, str]], label: str, start: bool = False) -> int | None:
    for i, (_, line) in enumerate(lines):
        if (line.startswith(label) if start else line == label):
            return i
    return None


def _section(lines: list[tuple[int, str]], heading: str, stops: tuple[str, ...]) -> list[tuple[int, str]]:
    begin = _find(lines, heading, start=True)
    if begin is None:
        return []
    end = next((i for i in range(begin + 1, len(lines)) if lines[i][1].startswith(stops)), len(lines))
    return lines[begin:end]


def _blocks(section: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """Блоки лиц внутри раздела: каждый начинается строкой «ГРН и дата … сведений о данном лице»."""
    starts = [i for i, (_, line) in enumerate(section) if line.startswith(PERSON_HEADER)]
    return [section[s:(starts[n + 1] if n + 1 < len(starts) else len(section))] for n, s in enumerate(starts)]


def _person_name(block: list[tuple[int, str]]) -> str | None:
    i = _find(block, "Отчество")
    return (_text_after(block, i) or None) if i is not None else None


def _field(block: list[tuple[int, str]], label: str, start: bool = False) -> str | None:
    i = _find(block, label, start=start)
    return _value_after(block, i) if i is not None else None


def _unreliable(block: list[tuple[int, str]]) -> bool:
    return any(line.startswith("Сведения о недостоверности") for _, line in block)


def _managers(lines: list[tuple[int, str]]) -> list[dict]:
    managers = []
    for block in _blocks(_section(lines, MANAGERS_HEADING, MANAGERS_STOP)):
        grn, date = _grn_date_after(block, 0)
        position = _find(block, "Должность")
        name_at = _find(block, "Отчество")
        managers.append({
            "name": _person_name(block),
            "inn": _field(block, "ИНН"),
            "position": _text_after(block, position) if position is not None else None,
            "grn": grn, "date": date,
            "page": block[name_at + 1][0] if name_at is not None and name_at + 1 < len(block) else block[0][0],
            "unreliable": _unreliable(block),
        })
    return managers


def _share_date(block: list[tuple[int, str]]) -> str | None:
    """Дата записи ЕГРЮЛ о размере доли: первая метка «ГРН и дата … записи» после размера доли."""
    percent = _find(block, "Размер доли (в процентах)", start=True)
    if percent is None:
        return None
    mark = next((i for i in range(percent + 1, len(block)) if block[i][1].startswith(RECORD_GRN_FIELD)), None)
    return _grn_date_after(block, mark)[1] if mark is not None else None


def _participants(lines: list[tuple[int, str]]) -> list[dict]:
    participants = []
    for block in _blocks(_section(lines, PARTICIPANTS_HEADING, PARTICIPANTS_STOP)):
        full_name = _find(block, "Полное наименование")
        is_org = _find(block, "ОГРН") is not None
        participants.append({
            "name": _text_after(block, full_name) if full_name is not None else _person_name(block),
            "ogrn": _field(block, "ОГРН") if is_org else None,
            "inn": _field(block, "ИНН"),
            "nominal": _field(block, "Номинальная стоимость доли", start=True),
            "percent": _field(block, "Размер доли (в процентах)", start=True),
            "since": _grn_date_after(block, 0)[1],
            "share_date": _share_date(block),
            "page": block[0][0],
            "unreliable": _unreliable(block),
        })
    return participants


def _company_share(lines: list[tuple[int, str]]) -> dict | None:
    """Доля в уставном капитале, принадлежащая самому обществу (ст. 24 14-ФЗ), или None."""
    begin = _find(lines, COMPANY_SHARE_HEADING, start=True)
    if begin is None:
        return None
    end = next((i for i in range(begin + 1, len(lines)) if lines[i][1].startswith("Сведения о")), len(lines))
    part = lines[begin:end]
    return {"nominal": _field(part, "Номинальная стоимость доли", start=True),
            "percent": _field(part, "Размер доли (в процентах)", start=True)}


def _registered(lines: list[tuple[int, str]]) -> str | None:
    """Дата государственной регистрации; у созданных до 01.07.2002 — дата той регистрации."""
    for label in ("Дата регистрации", "Дата регистрации до 1 июля 2002 года"):
        value = _field(lines, label)
        if value and _DATE_RE.fullmatch(value):
            return _iso(value)
    return None


def _charter_kind(reason: str, documents: list[dict]) -> str | None:
    """Вид записи об учредительном документе или None, если запись его не касается."""
    low = reason.lower()
    names = [d["name"].lower() for d in documents]
    charter = ("учредительн" in low and "не связ" not in low) or (
        "создани" in low and any("устав" in n or "учредительный документ" in n for n in names))
    if not charter:
        return None
    if any("новой редакции" in n for n in names):
        return "new_edition"
    if any("изменени" in n and ("учредительн" in n or "устав" in n) for n in names):
        return "amendments"
    return "creation" if "создани" in low else "change"


def _records(lines: list[tuple[int, str]]) -> list[dict]:
    starts = [i for i, (_, line) in enumerate(lines) if line == REASON]
    records = []
    for n, s in enumerate(starts):
        chunk = lines[s:(starts[n + 1] if n + 1 < len(starts) else len(lines))]
        grn = date = status = None
        documents: list[dict] = []
        for j, (_, line) in enumerate(chunk):
            if (line.startswith(RECORD_GRN) or line == "ГРН") and grn is None and date is None:
                grn, date = _grn_date_after(chunk, j)
            elif line == "Наименование документа":
                documents.append({"name": _text_after(chunk, j), "date": None})
            elif line == "Дата документа" and documents and documents[-1]["date"] is None:
                value = _value_after(chunk, j)
                documents[-1]["date"] = _iso(value) if value and _DATE_RE.fullmatch(value) else None
            elif line == "Статус записи":
                status = _text_after(chunk, j)
        reason = _text_after(chunk, 0)
        kind = _charter_kind(reason, documents)
        records.append({
            "index": n + 1, "reason": reason, "grn": grn, "date": date, "documents": documents,
            "status": status, "invalid": bool(status and "недействительн" in status.lower()),
            "charter": kind is not None, "charter_kind": kind, "page": chunk[0][0],
        })
    return records


def parse_pages(pages: list[str]) -> dict:
    """Разобрать выписку по текстам страниц (как их отдаёт PyMuPDF)."""
    first = pages[0] if pages else ""
    if "из Единого государственного реестра юридических лиц" not in first:
        raise NotEgrulExtract("это не выписка из ЕГРЮЛ (нет заголовка ФНС на первой странице)")
    ogrn = re.search(r"ОГРН((?:\s*\d){13})(?!\s*\d)", first)
    inn = re.search(r"ИНН((?:\s*\d){10})(?!\s*\d)", first)
    date = _DATE_RE.search(first)
    name = re.search(r"сведения о юридическом лице\s*\n(.*?)\n\s*полное наименование юридического лица", first,
                     re.S)
    lines = page_lines(pages)
    # в шапке части выписок ИНН нет: тогда он есть в разделе «Сведения об учете в налоговом органе»
    inn_value = re.sub(r"\s", "", inn.group(1)) if inn else _field(lines, "ИНН юридического лица")
    address = _find(lines, "Адрес юридического лица")
    return {
        "ogrn": re.sub(r"\s", "", ogrn.group(1)) if ogrn else None,
        "inn": inn_value,
        "full_name": " ".join(name.group(1).split()) if name else None,
        "extract_date": _iso(date.group(0)) if date else None,
        "address": (_text_after(lines, address) or None) if address is not None else None,
        "registered": _registered(lines),
        "company_share": _company_share(lines),
        "managers": _managers(lines),
        "participants": _participants(lines),
        "records": _records(lines),
        "pages": len(pages),
    }


def pdf_page_texts(path: str | Path) -> list[str]:
    """Текстовый слой каждой страницы PDF (выписка ФНС его содержит, OCR не нужен)."""
    import fitz  # noqa: PLC0415 — PyMuPDF нужен только для чтения PDF

    with fitz.open(str(path)) as doc:
        return [page.get_text() for page in doc]


def parse_pdf(path: str | Path) -> dict:
    return parse_pages(pdf_page_texts(path))


def record_by_grn(records: list[dict], grn: str) -> dict | None:
    return next((r for r in records if r["grn"] == grn), None)


def latest_charter_record(records: list[dict]) -> dict | None:
    """Последняя действующая запись об учредительном документе (записи в выписке идут по порядку)."""
    valid = [r for r in records if r["charter"] and not r["invalid"]]
    return valid[-1] if valid else None


def charter_records_after(records: list[dict], grn: str) -> list[dict]:
    """Действующие записи об учредительном документе, внесённые после записи с этим ГРН."""
    anchor = record_by_grn(records, grn)
    if anchor is None:
        return []
    return [r for r in records if r["index"] > anchor["index"] and r["charter"] and not r["invalid"]]


# ---------- получение с egrul.nalog.ru ----------

def _call(opener, url: str, data: dict | None, timeout: float) -> tuple[bytes, str]:
    body = urllib.parse.urlencode(data).encode("ascii") if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read(), str(response.headers.get("Content-Type", ""))
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise EgrulUnavailable(f"egrul.nalog.ru не ответил: {exc}") from exc


def _json(opener, url: str, data: dict | None, timeout: float) -> dict:
    raw, _ = _call(opener, url, data, timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise EgrulUnavailable(f"egrul.nalog.ru вернул не JSON ({url})") from exc


def fetch_extract(query: str, dest: str | Path, *, opener=None, sleep=time.sleep, clock=time.monotonic,
                  poll_seconds: float = 60, timeout: float = 30) -> dict:
    """Скачать выписку по ОГРН (13 цифр) или ИНН (10 цифр) юридического лица в файл dest.

    Возвращает {"ogrn", "inn", "name", "short_name", "path"}; при любой неудаче —
    EgrulUnavailable с причиной, файл при этом не создаётся.
    """
    q = str(query or "").strip()
    if not re.fullmatch(r"\d{10}|\d{13}", q):
        raise ValueError(f"нужен ОГРН (13 цифр) или ИНН (10 цифр) юридического лица, получено {query!r}")
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    started = _json(opener, f"{BASE_URL}/", {"vyp3CaptchaToken": "", "page": "", "query": q, "region": "",
                                             "PreventChromeAutocomplete": ""}, timeout)
    if started.get("captchaRequired"):
        raise EgrulUnavailable("ФНС запросила капчу: автоматический обход запрещён, выписку нужно получить вручную")
    token = started.get("t")
    if not token:
        raise EgrulUnavailable("egrul.nalog.ru не выдал токен поиска")
    rows = [r for r in _json(opener, f"{BASE_URL}/search-result/{token}", None, timeout).get("rows") or []
            if q in (r.get("o"), r.get("i"))]
    if len(rows) != 1:
        raise EgrulUnavailable(f"по запросу {q} найдено компаний: {len(rows)} (нужна ровно одна)")
    row = rows[0]
    requested = _json(opener, f"{BASE_URL}/vyp-request/{row['t']}", None, timeout)
    if requested.get("captchaRequired"):
        raise EgrulUnavailable("ФНС запросила капчу: автоматический обход запрещён, выписку нужно получить вручную")
    deadline = clock() + poll_seconds
    while _json(opener, f"{BASE_URL}/vyp-status/{row['t']}", None, timeout).get("status") != "ready":
        if clock() > deadline:
            raise EgrulUnavailable(f"выписка не сформировалась за {int(poll_seconds)} с, повторите позже")
        sleep(1)
    pdf, _ = _call(opener, f"{BASE_URL}/vyp-download/{row['t']}", None, timeout)
    if not pdf.startswith(b"%PDF"):
        raise EgrulUnavailable("ответ ФНС — не PDF-файл выписки")
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf)
    return {"ogrn": row.get("o"), "inn": row.get("i"), "name": row.get("n"), "short_name": row.get("c"),
            "path": str(target)}
