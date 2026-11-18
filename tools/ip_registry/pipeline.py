"""Реестр ТЗ: Excel однажды сеет журнал, дальше только сверка; миграция registry.json → журнал; query по снимку."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .diff import counts, diff_registries, mark_key, render_changes
from .journal import make_event, new_mark_id, read_events, replay
from .publish import BASE, EVENTS, PUBLISHED, _free_name, _publish, _remove, _replace, load_base, publish  # noqa: F401
from .normalize import CountryBook, number_key, product_key
from .records import build_records, load_products, plan_products, product_mapping, save_products
from .verifications import FILE_NAME as VERIFICATIONS_FILE, apply_verifications, load_verifications
from .xlsx_reader import read_images, read_rows

_DATE_IN_NAME = re.compile(r"^(\d{4})[-.](\d{2})[-.](\d{2})[ _-]*")


@dataclass
class BuildResult:
    registry_path: Path
    catalog_path: Path
    marks: int
    warnings: int
    changes_path: Path | None = None
    diff_counts: dict[str, int] = field(default_factory=dict)
    new_products: list[str] = field(default_factory=list)
    mode: str = "seed"
    messages: list[str] = field(default_factory=list)


def default_root() -> Path:
    from tools.watch.paths import RuntimePaths

    return RuntimePaths.discover().profile_root / "knowledge" / "ip"


def _name_date(name: str) -> dt.date | None:
    """Дата в начале имени файла; несуществующая дата (2026-13-45) считается отсутствием даты."""
    match = _DATE_IN_NAME.match(name)
    if not match:
        return None
    try:
        return dt.date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _export_date(path: Path) -> str:
    named = _name_date(path.name)
    if named:
        return named.isoformat()
    return dt.date.fromtimestamp(path.stat().st_mtime).isoformat()


def _exported(source: Path, source_label: str) -> str:
    label = Path(source_label)
    return label_date.isoformat() if (label_date := _name_date(label.name)) else _export_date(source)


_COLLISION = re.compile(r"-(\d{1,3})$")


def _original_key(path: Path) -> tuple[dt.date, int, str]:
    suffix = _COLLISION.search(path.stem)
    return (_name_date(path.name) or dt.date.min, int(suffix.group(1)) if suffix else 1, path.name)


def latest_original(root: Path) -> Path:
    candidates = list((root / "originals").glob("*.xlsx"))
    if not candidates:
        raise FileNotFoundError(f"в {root / 'originals'} нет выгрузок реестра (.xlsx)")
    return max(candidates, key=_original_key)


def _load_registry(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_events(marks: list[dict], source: dict, today: dt.date) -> list[dict]:
    events: list[dict] = []
    used: set[str] = set()
    for mark in marks:
        mark_id = new_mark_id(used)
        used.add(mark_id)
        card = {key: copy.deepcopy(value) for key, value in mark.items() if key != "search_numbers"}
        events.append(make_event(events=events, today=today, kind="seed", mark_id=mark_id, op="create",
                                 source=dict(source), mark=card))
    return events


def _verification_events(events: list[dict], marks: list[dict], items: list[dict], book: CountryBook,
                         today: dt.date) -> list[str]:
    """Дописывает события сверок; marks - рабочее состояние (по записям seed-событий), меняется на месте."""
    ids = {event["mark"]["id"]: event["mark_id"] for event in events if event["kind"] == "seed"}
    warnings: list[str] = []
    for item in items:
        key = number_key(item["registration_no"])
        matched = [m for m in marks if key and number_key(m.get("registration_no")) == key]
        before = {m["id"]: {t["code"]: copy.deepcopy(t) for t in m["territories"]} for m in matched}
        previous = {m["id"]: copy.deepcopy(m.get("verification")) for m in matched}
        warnings += apply_verifications(marks, [item], book)
        source = {"file": VERIFICATIONS_FILE, "sha256": None, "doc_type": "verification",
                  "doc_date": item["checked"], "office": item["source"]}
        for mark in matched:
            old = before[mark["id"]]
            new = {t["code"]: t for t in mark["territories"]}
            changes: dict = {"verification": [previous[mark["id"]], dict(mark["verification"])]}
            for code, territory in new.items():
                changes[f"territories.{code}"] = [old.get(code), copy.deepcopy(territory)]
            for code, territory in old.items():
                if code not in new:
                    changes[f"territories.{code}"] = [territory, None]
            events.append(make_event(events=events, today=today, kind="verification", mark_id=ids[mark["id"]],
                                     op="update", source=dict(source), changes=changes))
    return warnings


def _seed_registry(marks: list[dict], source: dict, items: list[dict], book: CountryBook,
                   today: dt.date) -> tuple[list[dict], list[str]]:
    events = _seed_events(marks, source, today)
    warnings = _verification_events(events, copy.deepcopy(marks), items, book, today)
    return events, warnings


def build(root: Path, source: Path | None = None, *, today: dt.date | None = None,
          source_label: str | None = None, _state: dict | None = None) -> BuildResult:
    today = today or dt.date.today()
    source = source or latest_original(root)
    if not read_events(root / "data" / EVENTS) and (root / "data" / "registry.json").exists():
        raise ValueError("в папке старый формат базы (data/registry.json): сначала выполните migrate")
    rows = read_rows(source)
    images = read_images(source)
    products_path = root / "products.yaml"
    known_products = load_products(products_path)
    products = plan_products(known_products, [row.values.get("product_raw") for row in rows])
    book = CountryBook.load()
    marks, blobs, warnings = build_records(rows, images, book, product_mapping(products))
    if source_label is None:
        try:
            source_label = source.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            source_label = source.name
    exported = _exported(source, source_label)
    verifications_path = root / VERIFICATIONS_FILE

    if read_events(root / "data" / EVENTS):
        base = load_base(root)
        if base is None:
            raise FileNotFoundError("журнал есть, а снимка нет: нет data/base.json")
        messages = []
        if verifications_path.exists():
            messages.append("verifications.yaml не используется: сверки внесены в журнал")
        excel_by_key = {mark_key(m): m for m in reversed(marks)}
        old_view = copy.deepcopy(base)
        for mark in old_view["marks"]:  # территории сверенных знаков намеренно отличаются от Excel
            twin = excel_by_key.get(mark_key(mark))
            if mark.get("verification") and twin is not None:
                mark["territories"] = copy.deepcopy(twin["territories"])
        diff = diff_registries(old_view, {"marks": marks})
        changes_dir = root / "changes"
        changes_dir.mkdir(exist_ok=True)
        changes_path = _free_name(changes_dir, f"{today.isoformat()}-сверка-excel.md")
        text = render_changes(diff, base["source"], {"exported": exported})
        if messages:
            text += "\n" + "\n".join(f"Примечание: {m}" for m in messages) + "\n"
        changes_path.write_text(text, encoding="utf-8")
        return BuildResult(root / "data" / BASE, root / "catalog.html", base["stats"]["marks"],
                           base["stats"]["warnings"], changes_path=changes_path, diff_counts=counts(diff),
                           mode="reconcile", messages=messages)

    items = load_verifications(verifications_path)
    event_source = {"file": source_label, "sha256": _sha256(source), "doc_type": "registry_xlsx",
                    "doc_date": exported, "office": None}
    events, verify_warnings = _seed_registry(marks, event_source, items, book, today)
    view = publish(root, events, today=today, images=blobs, warnings=warnings + verify_warnings)
    if _state is not None:
        _state["published"] = True
    new_products = sorted(set(products) - set(known_products), key=str.casefold)
    if products != known_products:
        save_products(products_path, products)
    return BuildResult(root / "data" / BASE, root / "catalog.html", view["stats"]["marks"],
                       view["stats"]["warnings"], new_products=new_products, mode="seed")


_MIGRATE_FIELDS = ("mark_text", "registration_no", "application_no", "product", "status", "expiry_date",
                   "next_payment_date", "nice_classes")


def _unwind_verification(mark: dict) -> dict | None:
    """Возвращает знак в состояние до сверки; результат - ранее применённая сверка (или None)."""
    stored = mark.pop("verification", None)
    registry_territories = mark.pop("registry_territories", None)
    if stored is None:
        return None
    applied = {"registration_no": mark.get("registration_no"), "source": stored["source"],
               "checked": stored["checked"], "reference": stored.get("reference"),
               "countries": {t["code"]: {"status": t["status"], "note": t.get("note"), "since": t.get("since")}
                             for t in mark["territories"]}}
    if registry_territories is not None:
        mark["territories"] = registry_territories
    return applied


def migrate(root: Path, *, today: dt.date) -> dict:
    if read_events(root / "data" / EVENTS):
        raise ValueError("миграция уже выполнена")
    legacy_path = root / "data" / "registry.json"
    registry = _load_registry(legacy_path)
    if registry is None:
        raise FileNotFoundError("нечего мигрировать: нет data/registry.json")
    legacy_bytes = legacy_path.read_bytes()
    book = CountryBook.load()
    items = load_verifications(root / VERIFICATIONS_FILE)
    yaml_keys = {number_key(i["registration_no"]) for i in items}
    seed_marks = copy.deepcopy(registry["marks"])
    applied: list[dict] = []
    for mark in seed_marks:
        item = _unwind_verification(mark)
        key = number_key(item["registration_no"]) if item else None
        if item and key not in yaml_keys and all(number_key(a["registration_no"]) != key for a in applied):
            applied.append(item)
    old = registry["source"]
    source = {"file": old.get("file"), "sha256": None, "doc_type": "registry_xlsx",
              "doc_date": old.get("exported"), "office": None}
    events, verify_warnings = _seed_registry(seed_marks, source, items + applied, book, today)

    expected = copy.deepcopy(registry["marks"])
    apply_verifications(expected, items, book)
    actual = {m["id"]: m for m in replay(events)}
    problems: list[str] = []
    for mark in expected:
        new = actual.get(mark["id"])
        label = f"{mark['id']} ({mark.get('mark_text')})"
        if new is None:
            problems.append(f"{label}: знак не найден после миграции")
            continue
        for name in _MIGRATE_FIELDS:
            if mark.get(name) != new.get(name):
                problems.append(f"{label}: {name}: {mark.get(name)!r} → {new.get(name)!r}")
        if {(t["code"], t["status"]) for t in mark["territories"]} != \
                {(t["code"], t["status"]) for t in new["territories"]}:
            problems.append(f"{label}: территории не совпадают")
    if len(actual) != len(expected):
        problems.append(f"число знаков: {len(expected)} → {len(actual)}")

    old_images = {m["image"] for m in registry["marks"] if m.get("image")}
    new_images = {m["image"] for m in actual.values() if m.get("image")}
    if old_images != new_images:
        problems.append(f"изображения: {sorted(old_images ^ new_images)} различаются")
    blobs: dict[str, bytes] = {}
    for name in sorted(old_images):
        file = root / "data" / name
        if file.is_file():
            blobs[name] = file.read_bytes()
        else:
            problems.append(f"нет файла изображения {name}")
    if problems:
        raise RuntimeError("миграция не совпала со старым снимком: " + "; ".join(problems))

    backup = root / "registry.json.migrating.bak"
    backup.write_bytes(legacy_bytes)
    view = publish(root, events, today=today, images=blobs,
                   warnings=list(registry.get("warnings", [])) + verify_warnings)
    after: list[str] = []
    for name, data in blobs.items():
        file = root / "data" / name
        if not file.is_file() or file.read_bytes() != data:
            after.append(f"изображение {name} не перенесено или отличается")
    if view["stats"]["with_image"] != len(old_images):
        after.append(f"with_image: {len(old_images)} → {view['stats']['with_image']}")
    if after:
        raise RuntimeError("после публикации: " + "; ".join(after))
    (root / "backups").mkdir(parents=True, exist_ok=True)  # вне data/: публикация подменяет data/ целиком
    _replace(backup, root / "backups" / "registry.json.bak")
    return {"marks": len(expected), "events": len(events)}


def ingest_file(root: Path, path: Path, *, today: dt.date | None = None) -> BuildResult:
    today = today or dt.date.today()
    name = path.name if _name_date(path.name) else f"{today.isoformat()}_{path.name}"
    originals = root / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    target = _free_name(originals, name)
    shutil.move(str(path), str(target))
    state: dict = {}
    try:
        return build(root, target, today=today, source_label=f"originals/{target.name}", _state=state)
    except BaseException:
        if not state.get("published"):  # после публикации каталог уже новый: выгрузку не возвращаем
            shutil.move(str(target), str(path))
        raise


def _resolve_country(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"[A-Za-z]{2}", text):
        if CountryBook.load().by_iso(text) is None:
            raise ValueError(f"страна не распознана: «{value}»; укажите ISO-код")
        return text.upper()
    found = CountryBook.load().find_in(text)
    if found is None:
        raise ValueError(f"страна не распознана: «{value}»; укажите ISO-код")
    return found.code


def query(root: Path, *, number: str | None = None, product: str | None = None,
          country: str | None = None) -> list[dict]:
    registry = load_base(root)
    if registry is None:
        raise FileNotFoundError("каталог не собран: нет data/base.json")
    wanted_number = number_key(number) if number else None
    if number and not wanted_number:
        raise ValueError("номер пуст после нормализации")
    wanted_product = product_key(product) if product else None
    wanted_country = _resolve_country(country) if country else None
    result = []
    for mark in registry["marks"]:
        if wanted_number and not any(wanted_number in item for item in mark["search_numbers"]):
            continue
        if wanted_product and wanted_product not in product_key(mark["product"]) \
                and wanted_product not in product_key(mark.get("product_raw")):
            continue
        if wanted_country and wanted_country not in {t["code"] for t in mark["territories"]}:
            continue
        result.append({key: value for key, value in mark.items() if key != "attorney_contacts"})
    return result
