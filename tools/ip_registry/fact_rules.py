"""Правила внесения фактов из документов: чистые функции без ввода-вывода. Класс A."""
from __future__ import annotations

import copy
import datetime as dt
import re

from .journal import DERIVED, TERRITORY_PREFIX
from .normalize import _LOOKALIKE, RECORD_STATUS_LABELS, TERRITORY_STATUS_LABELS, CountryBook, number_key
from .publish import NO_PRODUCT_DOC

DOC_TYPES = ("ru_certificate", "ru_registration_decision", "ru_refusal_decision", "ru_renewal", "ru_fips_card",
             "wipo_certificate", "wipo_grant", "wipo_refusal", "wipo_renewal", "wipo_madrid_page", "unknown")
CREATE_TYPES = {"ru_certificate", "ru_registration_decision", "wipo_certificate"}
REFUSAL_BASIS = {"ru_refusal_decision", "wipo_refusal", "wipo_madrid_page", "ru_fips_card"}
RENEWAL_TYPES = {"ru_renewal", "wipo_renewal"}
FACT_STATUSES = ("active", "pending", "refused", "withdrawn", "inactive")
VALUE_FIELDS = ("registration_no", "application_no", "mark_text", "nice_classes", "priority_date", "expiry_date",
                "status")
DATE_FIELDS = ("priority_date", "expiry_date")
NUMBER_FIELDS = ("registration_no", "application_no")
WORSE_STATUS = {"refused", "inactive", "withdrawn"}
WORSE_TERRITORY = {"refused", "lapsed"}
NOT_IN_QUOTE = "значение не следует из цитаты"
HAS_CONTACTS = "цитата содержит контактные данные"
TYPE_NOT_CONFIRMED = "тип документа не подтверждён цитатой"
NO_DOC_DATE = "дата документа не указана"
QUOTE_LIMIT = 200
DERIVED_NOTE = "выведены из типа документа, не из цитаты [СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ]"

# Маркеры статуса в цитате (без учёта регистра). Отрицания («не действует», «недействительна») вырезаются
# до поиска маркеров «действует»; цитата с маркером прекращения не подтверждает «действует».
_ACTIVE = ("зарегистрир", "охраня", "действ", "registered", "protected", "in force", "granted")
_REFUSED = ("отказ", "refus")
_WITHDRAWN = ("отозван", "withdraw")
# «истёк/истекла/истёкший» — прошедшее время; «истекает», «истечения» срок не прекращают.
_INACTIVE = ("прекращ", "не действ", re.compile(r"истек(?:л|ш|\b)"), "expired", "lapsed", "invalid", "недействит",
             "не продл", "not renewed")
_PENDING = ("рассмотр", "pending", "examination", "экспертиз")  # одно слово «заявка» статуса не подтверждает
STATUS_MARKERS = {"active": _ACTIVE, "refused": _REFUSED, "withdrawn": _WITHDRAWN, "inactive": _INACTIVE,
                  "pending": _PENDING}
TERRITORY_MARKERS = {"protected": _ACTIVE + ("предоставл", "grant"), "refused": _REFUSED, "lapsed": _INACTIVE,
                     "pending": _PENDING, "withdrawn": _WITHDRAWN,
                     "not_registered": ("не зарегистрир", "not registered")}
_NEGATED = re.compile(r"\bне\s+(?:действ|охраня|зарегистрир|предоставл)\w*|недействит\w*|"
                      r"\bnot\s+(?:registered|protected|in\s+force|granted)", re.IGNORECASE)
_POSITIVE = {"active", "protected"}

_WIPO_BASE = ("wipo", "воис", "madrid", "мадрид")
DOC_TYPE_MARKERS = {
    "ru_certificate": ((), ("свидетельство",)),
    "ru_registration_decision": ((), ("решение о государственной регистрации", "о регистрации")),
    "ru_refusal_decision": ((), ("отказ",)),
    "ru_renewal": ((), ("продлен",)),
    "ru_fips_card": ((), ("фипс", "открытые реестры", "выписка из государственного реестра")),
    "wipo_certificate": (_WIPO_BASE, ("certificate", "international registration")),
    "wipo_grant": (_WIPO_BASE, ("grant", "protection")),
    "wipo_refusal": (_WIPO_BASE, ("refus",)),
    "wipo_renewal": (_WIPO_BASE, ("renew",)),
    "wipo_madrid_page": (_WIPO_BASE, ("madrid monitor", "designation")),
}

_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_PHONES = (
    re.compile(r"\+\s?\d[\d\s().\-]{6,}\d"),                                  # международный
    re.compile(r"\(\d{2,5}\)\s?\d{1,4}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"),           # код в скобках
    re.compile(r"(?:\bтел|\btel|\bphone|\bфакс|\bfax|\bмоб)\w*\.?\s*[:.]?\s*[+(\d]", re.IGNORECASE),
    re.compile(r"(?<![\d\-])\d{3}-\d{2}-\d{2}(?![\d\-])"),                          # 123-45-67
)


# ---------- значение должно следовать из цитаты ----------

def _plain_text(value) -> str:
    return " ".join(str(value or "").split()).casefold()


_MONTHS_RU = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря")
_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")
_ALNUM = "0-9A-Za-zА-Яа-яЁё"


def _date_in_quote(day: dt.date, quote: str) -> bool:
    d, m, y = day.day, day.month, day.year
    ru, en = _MONTHS_RU[m - 1], _MONTHS_EN[m - 1]
    month_en = rf"(?:{en}|{en[:3]})\.?"
    patterns = [
        rf"(?<!\d){y}-{m:02d}-{d:02d}(?!\d)",
        rf"(?<!\d)0?{d}(?P<s>[./-])0?{m}(?P=s){y}(?!\d)",
        rf"(?<!\d)[«\"“„]?0?{d}[»\"”“]?\s+{ru}\s+{y}(?!\d)",
        rf"(?<!\d)0?{d}(?:st|nd|rd|th)?\s+{month_en}\s+{y}(?!\d)",
        rf"(?<![{_ALNUM}]){month_en}\s+0?{d}(?:st|nd|rd|th)?,?\s+{y}(?!\d)",
    ]
    if 2000 <= y <= 2099:
        patterns.append(rf"(?<!\d)0?{d}\.0?{m}\.{y % 100:02d}(?!\d)")
    return any(re.search(p, quote, re.IGNORECASE) for p in patterns)


def _number_in_quote(value, quote: str) -> bool:
    """Ключ значения входит в цитату как отдельный токен (границы — не буква и не цифра)."""
    key = number_key(value)
    if not key:
        return False
    text = quote.upper().translate(_LOOKALIKE)
    variants = [re.sub(r"(?<=\d)[\s ](?=\d)", "", text)]
    variants.append(re.sub(r"(?<=[0-9A-Z])[/\-](?=[0-9A-Z])", "", variants[0]))
    pattern = rf"(?<![{_ALNUM}]){re.escape(key)}(?![{_ALNUM}])"
    return any(re.search(pattern, v) for v in variants)


def _has_marker(text: str, markers) -> bool:
    """Маркер — подстрока или регулярное выражение; ё приравнивается к е."""
    low = _plain_text(text).replace("ё", "е")
    return any(marker.search(low) if isinstance(marker, re.Pattern) else marker.replace("ё", "е") in low
               for marker in markers)


def status_in_quote(status: str, quote: str, markers: dict = STATUS_MARKERS) -> bool:
    """Статус подтверждён, если в цитате есть его маркер (отрицания не считаются утверждением)."""
    if status not in markers:
        return False
    if status in _POSITIVE:
        return _has_marker(_NEGATED.sub(" ", quote), markers[status]) and not _has_marker(quote, _INACTIVE)
    return _has_marker(quote, markers[status])


def country_in_quote(code: str, quote: str, book: CountryBook) -> bool:
    """Страна названа в цитате: ISO-код отдельным токеном (заглавными) или название/синоним из справочника."""
    code = code.upper()
    latin = quote.translate(_LOOKALIKE)
    if re.search(rf"(?<![{_ALNUM}]){re.escape(code)}(?![{_ALNUM}])", latin):
        return True
    low = " ".join(quote.split()).casefold().replace("ё", "е")
    return any(other == code and re.search(rf"(?<![{_ALNUM}]){re.escape(name)}(?![{_ALNUM}])", low)
               for name, other in book.names())


def territory_in_quote(code: str, status: str, quote: str, book: CountryBook) -> bool:
    return country_in_quote(code, quote, book) and status_in_quote(status, quote, TERRITORY_MARKERS)


def doc_type_in_quote(doc_type: str, quote: str | None) -> bool:
    """Тип документа подтверждён заголовком: маркер типа (для WIPO — ещё и маркер ведомства)."""
    if not quote or doc_type not in DOC_TYPE_MARKERS:
        return False
    base, markers = DOC_TYPE_MARKERS[doc_type]
    return (not base or _has_marker(quote, base)) and _has_marker(quote, markers)


def has_contacts(text: str | None) -> bool:
    """E-mail или телефон в тексте: такую цитату или заметку не вносим и не показываем."""
    text = text or ""
    return bool(_EMAIL.search(text)) or any(p.search(text) for p in _PHONES)


def date_in_quote(value: str, quote: str) -> bool:
    return _date_in_quote(dt.date.fromisoformat(value), quote)


def value_in_quote(field: str, value, quote: str) -> bool:
    """Детерминированная проверка, что значение действительно содержится в цитате."""
    if field in DATE_FIELDS:
        return _date_in_quote(dt.date.fromisoformat(value), quote)
    if field in NUMBER_FIELDS:
        return _number_in_quote(value, quote)
    if field == "nice_classes":
        found = {int(n) for n in re.findall(r"(?<!\d)\d{1,3}(?!\d)", quote)}
        return all(c in found for c in value)
    if field == "mark_text":
        return _plain_text(value) in _plain_text(quote)
    if field == "status":
        return status_in_quote(value, quote)
    return False


# ---------- сравнение со значением базы ----------

def same_value(field: str, old, new) -> bool:
    if old is None or new is None:
        return old == new
    if field in NUMBER_FIELDS:
        return number_key(old) == number_key(new)
    if field == "nice_classes":
        return sorted(set(old)) == sorted(set(new))
    if field == "mark_text":
        return _plain_text(old) == _plain_text(new)
    return old == new


# ---------- новый знак, страны, кандидаты ----------

def territory(old: dict | None, code: str, item: dict, book: CountryBook) -> dict:
    country = book.by_iso(code)
    base = old or {"code": code, "basis": None, "note": None}
    return {**base, "code": code, "name": base.get("name") or (country.name if country else code),
            "status": item["status"]}


def new_mark(mark_id: str, facts: dict, values: dict, territories: dict, book: CountryBook) -> dict:
    get = {field: value for field, (value, _anchor) in values.items()}
    madrid = facts["doc_type"].startswith("wipo")
    if territories:
        terr = [territory(None, code, item, book) for code, (item, _a) in territories.items()]
    elif not madrid:
        terr = [territory(None, "RU", {"status": "protected"}, book)]
    else:
        terr = []
    return {
        "id": mark_id, "sheet_row": None, "row_no": None,
        "mark_text": get.get("mark_text"), "mark_kind": "word" if get.get("mark_text") else "unknown",
        "image": None, "image_note": None, "reg_type": "madrid" if madrid else "national", "reg_kind_raw": None,
        "application_no": get.get("application_no"), "registration_no": get.get("registration_no"),
        "number_note": None, "product": NO_PRODUCT_DOC, "product_raw": None, "purpose": None,
        "nice_classes": get.get("nice_classes", []), "nice_raw": None,
        "priority_date": get.get("priority_date"), "expiry_date": get.get("expiry_date"),
        "next_payment_date": get.get("expiry_date"), "status": get.get("status", "active"), "status_raw": None,
        "territories": terr, "territory_raw": None, "territory_notes": [], "attorney": None, "warnings": [],
    }


def derived_defaults(facts: dict, values: dict, territories: dict) -> list[str]:
    """Поля нового знака, выведенные из типа документа, а не из цитаты (осознанное исключение)."""
    derived = []
    if "status" not in values:
        derived.append("status")
    if not territories and not facts["doc_type"].startswith("wipo"):
        derived.append(TERRITORY_PREFIX + "RU")
    if "expiry_date" in values:  # дата следующей оплаты нового знака = срок окончания (правило, не цитата)
        derived.append("next_payment_date")
    return derived


def derived_anchors(derived: list[str]) -> list[dict]:
    return [{"field": field, "quote": None, "quote_check": DERIVED} for field in derived]


def candidates(mark: dict, values: dict, territories: dict, book: CountryBook) -> dict:
    """Изменённые поля: {поле: (старое, новое, якорь)}; равнозначные значения не меняются."""
    result: dict = {}
    for field, (value, anchor_) in values.items():
        if not same_value(field, mark.get(field), value):
            result[field] = (mark.get(field), value, anchor_)
    current = {t["code"]: t for t in mark.get("territories") or []}
    for code, (item, anchor_) in territories.items():
        old = current.get(code)
        if old is None or old.get("status") != item["status"]:
            result[TERRITORY_PREFIX + code] = (copy.deepcopy(old), territory(old, code, item, book), anchor_)
    return result


# ---------- конфликты и решение ----------

def is_worsening(field: str, old, new) -> bool:
    if field == "status":
        return old == "active" and new in WORSE_STATUS
    if field.startswith(TERRITORY_PREFIX):
        return (old or {}).get("status") == "protected" and (new or {}).get("status") in WORSE_TERRITORY
    return False


def status_changed(field: str, old, new) -> bool:
    if field == "status":
        return old != new
    if field.startswith(TERRITORY_PREFIX):
        return (old or {}).get("status") != (new or {}).get("status")
    return False


def conflict(field: str, old, new, doc_type: str, type_confirmed: bool = False) -> str | None:
    if field in NUMBER_FIELDS and old and not same_value(field, old, new):
        return "номер в документе отличается от номера в базе"
    if field == "expiry_date" and old and new < old:
        return "срок окончания в документе раньше, чем в базе"
    if status_changed(field, old, new) and not type_confirmed:
        where = "статуса" if field == "status" else f"статуса страны {field[len(TERRITORY_PREFIX):]}"
        return f"изменение {where}: {TYPE_NOT_CONFIRMED}"
    if is_worsening(field, old, new) and doc_type not in REFUSAL_BASIS:
        if field == "status":
            return "ухудшение статуса без документа-основания"
        return f"ухудшение статуса страны {field[len(TERRITORY_PREFIX):]} без документа-основания"
    return None


def decide(mark: dict, cands: dict, facts: dict, force_fields, label: str) -> dict:
    """Всё-или-ничего: {changes, anchors, forced, stale, conflicts}.

    facts — сведения о документе после проверки цитат: doc_date (только подтверждённая цитатой, иначе None),
    doc_type и doc_type_confirmed (тип подтверждён заголовком из doc_type_quote).
    """
    doc_date, doc_type = facts.get("doc_date"), facts["doc_type"]
    confirmed = bool(facts.get("doc_type_confirmed"))
    out = {"changes": {}, "anchors": [], "forced": [], "stale": [], "conflicts": {}}
    for field, (old, new, anchor_) in cands.items():
        known = (mark.get("provenance") or {}).get(field, {}).get("doc_date")
        if doc_date and known and doc_date < known:
            out["stale"].append({"mark": label, "field": field, "doc_date": doc_date, "current_doc_date": known})
            continue
        reason = conflict(field, old, new, doc_type, confirmed)
        if not reason and not doc_date and known:
            reason = f"{NO_DOC_DATE}, а значение в базе взято из документа от {known}"
        if reason and (field in force_fields or (field.startswith(TERRITORY_PREFIX) and "territories" in force_fields)):
            out["forced"].append(field)
        elif reason:
            out["conflicts"][field] = reason
            continue
        out["changes"][field] = [old, new]
        out["anchors"].append(anchor_)
    if "expiry_date" in out["changes"] and doc_type in RENEWAL_TYPES and confirmed \
            and mark.get("next_payment_date") and mark.get("next_payment_date") == mark.get("expiry_date"):
        out["changes"]["next_payment_date"] = [mark["next_payment_date"], out["changes"]["expiry_date"][1]]
    return out


def force_names(cands: dict) -> set[str]:
    """Имена, допустимые в force_fields для этих кандидатов."""
    names = set(cands)
    if any(name.startswith(TERRITORY_PREFIX) for name in cands):
        names.add("territories")
    return names


def worsened(mark: dict, changes: dict, document: str, quotes: dict | None = None) -> list[dict]:
    rows = []
    for field, (old, new) in changes.items():
        if is_worsening(field, old, new):
            territory_ = field.startswith(TERRITORY_PREFIX)
            row = {"mark": mark.get("mark_text") or "[изобразительный знак]",
                   "number": mark.get("registration_no") or mark.get("application_no") or "без номера",
                   "field": field, "old": old["status"] if territory_ else old,
                   "new": new["status"] if territory_ else new, "document": document}
            if quotes and quotes.get(field):
                row["quote"] = quotes[field]
            rows.append(row)
    return rows


# ---------- отчёт ----------

def fmt(value) -> str:
    if isinstance(value, dict):
        return f"{value.get('name') or value.get('code')}: {TERRITORY_STATUS_LABELS.get(value.get('status'), value.get('status'))}"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "—"
    if value in RECORD_STATUS_LABELS:
        return RECORD_STATUS_LABELS[value]
    if value in TERRITORY_STATUS_LABELS:
        return TERRITORY_STATUS_LABELS[value]
    return "—" if value is None else str(value)


def _quoted(quote: str | None) -> str:
    if not quote:
        return ""
    text = " ".join(quote.split())
    if len(text) > QUOTE_LIMIT:
        text = text[:QUOTE_LIMIT] + "…"
    return f"; цитата: «{text}»"


def render_report(stem: str, card: dict, facts: dict, report: dict) -> str:
    confirmed = facts.get("doc_type_confirmed")
    kind = facts["doc_type"] + ("" if confirmed is None else
                                " (подтверждён цитатой)" if confirmed else f" ({TYPE_NOT_CONFIRMED})")
    lines = [f"# Документ {stem}", "", f"- Файл: {card['document']}", f"- Тип: {kind}",
             f"- Дата документа: {facts.get('doc_date') or NO_DOC_DATE}",
             f"- Ведомство: {facts.get('office') or '—'}", "", "## Внесено", ""]
    for item in report["applied"]:
        quotes = item.get("quotes") or {}
        lines.append(f"- {item['label']}:")
        lines += [f"  - {field}: {fmt(old)} → {fmt(new)}{_quoted(quotes.get(field))}"
                  for field, (old, new) in item["changes"].items()]
    lines += ["", "## Ухудшение статуса", ""]
    lines += [f"- {w['mark']} (№ {w['number']}), {w['field']}: {fmt(w['old'])} → {fmt(w['new'])}; "
              f"документ {w['document']}{_quoted(w.get('quote'))}" for w in report["worsened"]]
    lines += ["", "## Новые знаки", ""]
    for item in report["created"]:
        lines.append(f"- {item['label']} — укажите препарат (сейчас «{NO_PRODUCT_DOC}»)")
        if item.get("derived"):
            lines.append(f"  - {', '.join(item['derived'])}: {DERIVED_NOTE}")
    lines += ["", "## Устаревшие значения", ""]
    lines += [f"- {item['mark']}: {item['field']} — документ от {item['doc_date']} старше источника "
              f"текущего значения ({item['current_doc_date']})" for item in report["stale"]]
    lines += ["", "## Отброшено (нет подтверждения цитатой)", ""]
    lines += [f"- {item['field']}: {item['reason']}" for item in report["dropped"]]
    lines += ["", "## Ждут решения юриста", ""]
    lines += [f"- {item['mark'] or 'документ'}: {item['reason']}"
              + (f" (поля: {', '.join(item['fields'])})" if item["fields"] else "") for item in report["decisions"]]
    return "\n".join(lines) + "\n"
