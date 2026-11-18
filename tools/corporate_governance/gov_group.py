# -*- coding: utf-8 -*-
"""Реестр группы: компании, физические лица, владение долями, должности (group.yaml).

Реестр лежит рядом с entities/: profile/knowledge/corporate/group/ (group.yaml, audit.jsonl,
.lock). Записи вносят group-sync из выписки ЕГРЮЛ (apply_extract) и юрист вручную; у каждой
записи есть источник. Связь владения — отрезок с постоянной долей: since включительно,
until исключительно (с этой даты связи уже нет). Дата закрытия иностранной компании может
быть годом: для расчёта это 31.12 этого года, в документах печатается год.

Расчёт группы лиц, аффилированных лиц и связанных сторон — gov_group_calc.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_store as store  # noqa: E402

SCHEMA_VERSION = 1
KINDS = ("company", "person")
ROLES = ("eio", "board")
COLLECTIONS = ("entities", "links", "offices", "relatives", "pbu11_other")
APPROX = "не позднее"  # пометка даты окончания, установленной по выписке, а не по документу
UNKNOWN_SHARE = "размер доли до записи ЕГРЮЛ о текущем размере по выписке не виден"
_YEAR_RE = re.compile(r"\d{4}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_FORMS = (("ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ", "ООО"), ("НЕПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО", "НАО"),
          ("ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО", "ПАО"), ("АКЦИОНЕРНОЕ ОБЩЕСТВО", "АО"),
          ("ТОВАРИЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ", "ТОО"))


# ---------- даты и доли ----------

def check_date(value, field: str, *, year_ok: bool = False) -> str | None:
    """Дата ГГГГ-ММ-ДД (или год ГГГГ, если year_ok) как строка; пусто → None."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if _DATE_RE.fullmatch(text):
        try:
            dt.date.fromisoformat(text)
        except ValueError:
            pass
        else:
            return text
    elif year_ok and _YEAR_RE.fullmatch(text):
        return text
    raise store.GovError(f"{field}: нужна дата ГГГГ-ММ-ДД{' или год ГГГГ' if year_ok else ''}, получено {value!r}")


def as_date(value, *, end: bool = False) -> dt.date | None:
    """Строка реестра → дата; год → 01.01 (начало) или 31.12 (окончание)."""
    if value in (None, ""):
        return None
    text = str(value)
    if _YEAR_RE.fullmatch(text):
        return dt.date(int(text), 12, 31) if end else dt.date(int(text), 1, 1)
    return dt.date.fromisoformat(text)


def closure_end(entity: dict) -> dt.date | None:
    """С какой даты лица нет. Год закрытия — 31.12 этого года, но не позже даты, когда о закрытии
    стало известно (closed_reported): «закрыто в текущем году» значит, что на эту дату уже закрыто."""
    end = as_date(entity.get("closed"), end=True)
    reported = as_date(entity.get("closed_reported"))
    if end and reported and is_year(entity.get("closed")):
        end = min(end, reported)
    return end


def is_year(value) -> bool:
    return bool(value) and bool(_YEAR_RE.fullmatch(str(value)))


def fmt_date(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, dt.date):
        return value.strftime("%d.%m.%Y")
    return f"{value} г." if is_year(value) else dt.date.fromisoformat(str(value)).strftime("%d.%m.%Y")


def percent(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ".").replace("%", "").strip())
    except InvalidOperation:
        return None


def fmt_percent(value) -> str:
    p = percent(value)
    if p is None:
        return ""
    text = format(p.normalize(), "f")
    return text.replace(".", ",") + " %"


def fmt_money(value) -> str:
    """Сумма в рублях с разделителями разрядов: 5500000 → «5 500 000»."""
    if value in (None, ""):
        return ""
    amount = percent(value)
    if amount is None:
        return str(value)
    whole, _, frac = format(amount, "f").partition(".")
    return f"{int(whole):,}".replace(",", " ") + (f",{frac}" if frac else "")


def label(entity: dict) -> str:
    """Короткое имя для таблиц и схемы: организационная форма сокращена, кавычки «ёлочки»."""
    name = " ".join(str(entity.get("short_name") or entity["name"]).split())
    if entity.get("kind") == "person":
        return name.title() if name.isupper() else name
    for full, short in _FORMS:
        if name.upper().startswith(full):
            name = short + name[len(full):]
            break
    name = re.sub(r'"\s*([^"]*?)\s*"', r"«\1»", name)
    return name


# ---------- хранилище ----------

def empty() -> dict:
    return {"schema_version": SCHEMA_VERSION, "rev": 0, **{key: [] for key in COLLECTIONS}}


class GroupStore(store.Entity):
    """Реестр группы с той же атомарной записью, блокировкой и аудитом, что у компании."""

    def __init__(self, entities_dir: Path):
        super().__init__(Path(entities_dir).parent, "group")
        self.domain_dir = Path(entities_dir).parent

    @property
    def path(self) -> Path:
        return self.dir / "group.yaml"

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.path.exists():
            return empty()
        data = self._load(self.path, "entities")
        for key in COLLECTIONS:
            data.setdefault(key, [])
        return data

    def save(self, data: dict) -> int:
        self.ensure()
        return self._save(self.path, data)


def group_store(args) -> GroupStore:
    base = Path(args.entities_dir) if args.entities_dir else store.default_entities_dir()
    return GroupStore(base)


# ---------- поиск и записи ----------

def find_entity(data: dict, key) -> dict | None:
    """По id, ОГРН, ИНН, иностранному номеру или точному имени (если оно однозначно)."""
    text = " ".join(str(key or "").split())
    if not text:
        return None
    for entity in data["entities"]:
        if text in (entity["id"], entity.get("ogrn"), entity.get("inn"), entity.get("reg_id")):
            return entity
    same = [e for e in data["entities"] if e["name"].casefold() == text.casefold()
            or label(e).casefold() == text.casefold()]
    return same[0] if len(same) == 1 else None


def require_entity(data: dict, key) -> dict:
    entity = find_entity(data, key)
    if entity is None:
        raise store.GovError(f"в реестре группы нет лица {key!r} (id, ОГРН, ИНН или точное имя): "
                             "сначала group-sync или group-add")
    return entity


def entities_by_id(data: dict) -> dict:
    return {e["id"]: e for e in data["entities"]}


def upsert_entity(data: dict, *, kind: str, name: str, source: str, fill_only: bool = False,
                  **fields) -> tuple[dict, bool]:
    """Найти лицо по ОГРН, ИНН, иностранному номеру (у физлица ещё по имени без ИНН) или завести.
    fill_only: лицо встретилось в чужой выписке (участник, ЕИО) — у найденного только дополняются
    пустые поля, наименование и источник остаются из его собственной записи."""
    if kind not in KINDS:
        raise store.GovError(f"kind: {kind!r}, допустимо {KINDS}")
    name = " ".join(str(name or "").split())
    if not name:
        raise store.GovError("у лица нет имени")
    found = None
    for key in ("ogrn", "inn", "reg_id"):
        if fields.get(key):
            found = next((e for e in data["entities"] if e.get(key) == fields[key]), None)
            if found:
                break
    if found is None and kind == "person" and not fields.get("inn"):
        same = [e for e in data["entities"] if e["kind"] == "person" and e["name"].casefold() == name.casefold()]
        found = same[0] if len(same) == 1 else None
    if found is not None:
        if found["kind"] != kind:
            raise store.GovError(f"{found['id']} в реестре — {found['kind']}, а не {kind}")
        if fill_only:
            for key, value in fields.items():
                if value not in (None, "") and not found.get(key):
                    found[key] = value
            return found, False
        found["name"] = name
        found.update({k: v for k, v in fields.items() if v not in (None, "")})
        found["source"] = source
        return found, False
    entity = {"id": store.next_id("G", data["entities"], "id"), "kind": kind, "name": name,
              **{k: v for k, v in fields.items() if v not in (None, "")}, "source": source}
    entity.setdefault("status", "active")
    data["entities"].append(entity)
    return entity, True


def _overlaps(a_since, a_until, b_since, b_until) -> bool:
    lo = max(as_date(a_since) or dt.date.min, as_date(b_since) or dt.date.min)
    hi = min(as_date(a_until, end=True) or dt.date.max, as_date(b_until, end=True) or dt.date.max)
    return lo < hi


def add_link(data: dict, *, owner: str, target: str, source: str, percent_value=None, nominal=None,
             since=None, until=None, share_date=None, paid=None, basis=None, note=None) -> tuple[dict, bool]:
    """Отрезок владения. Тот же отрезок (владелец, общество, начало, окончание) обновляется."""
    if owner == target:
        raise store.GovError("лицо не может владеть долей в самом себе: для доли общества — group-add --own-share")
    since, until = check_date(since, "since"), check_date(until, "until")
    if since and until and as_date(until) <= as_date(since):
        raise store.GovError(f"until {until} не позже since {since}")
    if percent_value not in (None, "") and percent(percent_value) is None:
        raise store.GovError(f"доля {percent_value!r}: нужно число процентов")
    fields = {"percent": None if percent_value in (None, "") else str(percent_value).replace(",", "."),
              "nominal": nominal, "share_date": check_date(share_date, "share_date"), "paid": paid,
              "basis": basis, "note": note, "source": source}
    same = [l for l in data["links"] if l["owner"] == owner and l["target"] == target]
    for link in same:
        if link.get("since") == since and link.get("until") == until:
            link.update({k: v for k, v in fields.items() if v not in (None, "")})
            if fields["percent"] is not None and link.get("note") == UNKNOWN_SHARE and not note:
                link.pop("note")  # юрист внёс долю, которую выписка не показывала
            return link, False
    for link in same:
        if _overlaps(link.get("since"), link.get("until"), since, until):
            raise store.GovError(f"отрезок пересекается с {link['id']} ({link.get('since')} — "
                                 f"{link.get('until') or 'н. в.'}): исправьте даты того отрезка или этого")
    link = {"id": store.next_id("L", data["links"], "id"), "owner": owner, "target": target,
            "since": since, "until": until, **{k: v for k, v in fields.items() if v not in (None, "")}}
    data["links"].append(link)
    return link, True


def add_office(data: dict, *, person: str, company: str, role: str, source: str, since=None, until=None,
               title=None) -> tuple[dict, bool]:
    if role not in ROLES:
        raise store.GovError(f"role: {role!r}, допустимо {ROLES}")
    since, until = check_date(since, "since"), check_date(until, "until")
    for office in data["offices"]:
        if (office["person"], office["company"], office["role"], office.get("since")) == (person, company, role, since):
            office.update({k: v for k, v in {"until": until, "title": title, "source": source}.items() if v})
            return office, False
    office = {"id": store.next_id("O", data["offices"], "id"), "person": person, "company": company,
              "role": role, "title": title, "since": since, "until": until, "source": source}
    data["offices"].append(office)
    return office, True


def close(record: dict, until: str, *, approx: bool) -> None:
    record["until"] = until
    if approx:
        record["until_note"] = APPROX


# ---------- выписка ЕГРЮЛ → реестр ----------

def _sync_link(data: dict, owner: dict, company: dict, p: dict, source: str) -> list[str]:
    log = []
    same = sorted((l for l in data["links"] if l["owner"] == owner["id"] and l["target"] == company["id"]),
                  key=lambda l: as_date(l.get("since")) or dt.date.min)
    open_link = next((l for l in same if not l.get("until")), None)
    start = p.get("share_date") or p.get("since")
    share = p.get("percent")
    if open_link is not None and percent(open_link.get("percent")) == percent(share):
        open_link.update({k: v for k, v in {"nominal": p.get("nominal"), "share_date": p.get("share_date"),
                                            "source": source}.items() if v})
        return log
    if open_link is not None:
        if start and as_date(start) > (as_date(open_link.get("since")) or dt.date.min):
            close(open_link, start, approx=False)
            log.append(f"  {label(owner)} → {label(company)}: доля {fmt_percent(open_link.get('percent'))} "
                       f"до {fmt_date(start)}")
        else:  # тот же отрезок, доля в реестре была неизвестна или внесена с ошибкой
            open_link.update(percent=share, nominal=p.get("nominal"), share_date=p.get("share_date"),
                             source=source)
            open_link.pop("note", None)
            log.append(f"  {label(owner)} → {label(company)}: доля уточнена {fmt_percent(share)}")
            return log
    link, _ = add_link(data, owner=owner["id"], target=company["id"], source=source, percent_value=share,
                       nominal=p.get("nominal"), since=start, share_date=p.get("share_date"),
                       note=None if share else "размер доли в выписке не в процентах [ПРОВЕРИТЬ ФАКТ]")
    log.append(f"  {label(owner)} → {label(company)}: {fmt_percent(share) or 'доля ?'} с {fmt_date(start)}")
    since = p.get("since")
    covered = any((as_date(l.get("since")) or dt.date.min) <= as_date(since) < (as_date(l.get("until")) or dt.date.max)
                  for l in same) if since else True
    if since and start != since and not covered:
        add_link(data, owner=owner["id"], target=company["id"], source=source, since=since, until=start,
                 note=UNKNOWN_SHARE)
        log.append(f"  {label(owner)} → {label(company)}: участник с {fmt_date(since)}, доля до "
                   f"{fmt_date(start)} не видна [ПРОВЕРИТЬ ФАКТ]")
    return log


def _sync_offices(data: dict, company: dict, managers: list[dict], date: str, source: str) -> list[str]:
    log, current = [], []
    for m in managers:
        person, _ = upsert_entity(data, kind="person", name=m["name"], inn=m.get("inn"), source=source,
                                  fill_only=True)
        current.append(person["id"])
        open_same = next((o for o in data["offices"] if o["company"] == company["id"] and o["role"] == "eio"
                          and o["person"] == person["id"] and not o.get("until")), None)
        if open_same is not None:
            open_same["title"] = m.get("position") or open_same.get("title")
            if str(open_same.get("source", "")).startswith("выписка ЕГРЮЛ"):
                open_same["source"] = source  # дату, внесённую по документу или со слов юриста, не трогаем
            continue
        add_office(data, person=person["id"], company=company["id"], role="eio", since=m.get("date"),
                   title=m.get("position"), source=source)
        log.append(f"  ЕИО {label(company)}: {label(person)} с {fmt_date(m.get('date'))}")
    new_starts = sorted(m["date"] for m in managers if m.get("date"))
    for office in data["offices"]:
        if (office["company"] == company["id"] and office["role"] == "eio" and not office.get("until")
                and office["person"] not in current):
            later = [d for d in new_starts if as_date(d) > (as_date(office.get("since")) or dt.date.min)]
            close(office, later[0] if later else date, approx=not later)
            person = entities_by_id(data)[office["person"]]
            log.append(f"  ЕИО {label(company)}: {label(person)} до {fmt_date(office['until'])}"
                       + (f" ({APPROX})" if not later else ""))
    return log


def apply_extract(data: dict, info: dict, source: str) -> tuple[dict, list[str]]:
    """Внести в реестр общество из разобранной выписки (gov_egrul.parse_pages): реквизиты,
    участников с долями и датами записей, ЕИО. Чего в выписке больше нет — закрывается."""
    date = info["extract_date"]
    own = (info.get("company_share") or {}).get("percent")
    company, created = upsert_entity(
        data, kind="company", name=info["full_name"], source=source, ogrn=info["ogrn"], inn=info["inn"],
        country="Россия", address=info.get("address"), registered=info.get("registered"), status="active")
    if own:
        company["own_share"] = own
    else:
        company.pop("own_share", None)
    log = [f"{label(company)} ({company['id']}): {'заведена' if created else 'обновлена'} по выписке от "
           f"{fmt_date(date)}"]
    seen = set()
    for p in info["participants"]:
        kind = "company" if p.get("ogrn") else "person"
        owner, _ = upsert_entity(data, kind=kind, name=p["name"], source=source, ogrn=p.get("ogrn"),
                                 inn=p.get("inn"), country="Россия" if kind == "company" else None,
                                 fill_only=True)
        seen.add(owner["id"])
        log += _sync_link(data, owner, company, p, source)
    for link in data["links"]:
        if link["target"] == company["id"] and not link.get("until") and link["owner"] not in seen:
            close(link, date, approx=True)
            owner = entities_by_id(data)[link["owner"]]
            log.append(f"  {label(owner)} → {label(company)}: в выписке не участник, связь закрыта "
                       f"{APPROX} {fmt_date(date)} [ПРОВЕРИТЬ ФАКТ]")
    log += _sync_offices(data, company, info["managers"], date, source)
    return company, log
