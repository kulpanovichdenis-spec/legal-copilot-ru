"""registry.yaml: индекс досье. Точное совпадение только по ключу и алиасам-номерам;
ИНН и название контрагента дают частичное (у контрагента может быть несколько договоров)."""
from __future__ import annotations

from pathlib import Path

import yaml

from .keys import number_key
from .paths import RegistryError, guard

FILE = "registry.yaml"


def load(root: Path) -> dict:
    path = guard(Path(root)) / FILE
    if not path.is_file():
        return {"version": 1, "contracts": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("contracts", []), list):
        raise RegistryError(f"{path}: contracts должен быть списком")
    data.setdefault("version", 1)
    data.setdefault("contracts", [])
    return data


def save(root: Path, data: dict) -> None:
    root = guard(Path(root))
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (FILE + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(root / FILE)


def _exact_keys(entry: dict) -> set[str]:
    """Ключ и алиасы. ИНН сюда не входит (FNM-CD-01): он общий для всех договоров контрагента."""
    values = [entry["key"]] + list(entry.get("aliases", []))
    return {number_key(v) for v in values if str(v).strip()}


def _partial(entry: dict, q: str, k: str) -> bool:
    inn = str(entry.get("inn", "") or "").strip()
    if k and inn and number_key(inn) == k:
        return True
    return bool(q) and any(q in str(v).lower() for v in [entry["counterparty"], *entry.get("aliases", [])])


def find_entry(data: dict, key: str) -> dict | None:
    k = number_key(key)
    for entry in data["contracts"]:
        if k in _exact_keys(entry):
            return entry
    return None


def lookup(root: Path, query: str) -> list[dict]:
    data = load(root)
    k = number_key(query)
    q = (query or "").strip().lower()
    hits = []
    for entry in data["contracts"]:
        if k and k in _exact_keys(entry):
            match = "exact"
        elif _partial(entry, q, k):
            match = "partial"
        else:
            continue
        hits.append({"key": entry["key"], "folder": entry["folder"],
                     "counterparty": entry["counterparty"], "match": match})
    hits.sort(key=lambda h: h["match"] != "exact")
    return hits
