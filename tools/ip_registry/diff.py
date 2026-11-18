"""Изменения между двумя сборками реестра."""
from __future__ import annotations

from .normalize import number_key

TRACKED = ("mark_text", "product", "status", "expiry_date", "next_payment_date", "nice_classes")


def mark_key(mark: dict) -> str:
    if mark.get("registration_no"):
        return f"{mark['reg_type']}:reg:{number_key(mark['registration_no'])}"
    if mark.get("application_no"):
        return f"{mark['reg_type']}:app:{number_key(mark['application_no'])}"
    text = (mark.get("mark_text") or "").casefold()
    return f"{mark['reg_type']}:row:{text}|{mark['product']}|{mark.get('territory_raw') or ''}"


def _keyed(registry: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for mark in registry["marks"]:
        key = base = mark_key(mark)
        index = 2
        while key in result:
            key = f"{base}#{index}"
            index += 1
        result[key] = mark
    return result


def _label(mark: dict) -> str:
    number = mark.get("registration_no") or mark.get("application_no") or "без номера"
    return f"{mark.get('mark_text') or '[изобразительный знак]'} — {mark['product']} — № {number}"


def _territories(mark: dict) -> list[str]:
    return sorted(f"{t['code']}:{t['status']}" for t in mark["territories"])


def diff_registries(old: dict, new: dict) -> dict:
    before, after = _keyed(old), _keyed(new)
    changed = []
    for key in sorted(before.keys() & after.keys()):
        fields = {field: [before[key].get(field), after[key].get(field)]
                  for field in TRACKED if before[key].get(field) != after[key].get(field)}
        if _territories(before[key]) != _territories(after[key]):
            fields["territories"] = [_territories(before[key]), _territories(after[key])]
        if fields:
            changed.append({"label": _label(after[key]), "fields": fields})
    return {
        "added": [_label(after[key]) for key in sorted(after.keys() - before.keys())],
        "removed": [_label(before[key]) for key in sorted(before.keys() - after.keys())],
        "changed": changed,
    }


def counts(diff: dict) -> dict[str, int]:
    return {name: len(diff[name]) for name in ("added", "removed", "changed")}


def _date(value: str | None) -> str:
    return ".".join(reversed(value.split("-"))) if value else "—"


def render_changes(diff: dict, old_source: dict, new_source: dict) -> str:
    total = counts(diff)
    lines = [
        f"# Изменения реестра ТЗ: выгрузка {_date(old_source.get('exported'))} → {_date(new_source.get('exported'))}",
        "",
        f"Добавлено: {total['added']}. Удалено: {total['removed']}. Изменено: {total['changed']}.",
        "",
    ]
    for title, items in (("Добавлено", diff["added"]), ("Удалено", diff["removed"])):
        if items:
            lines += [f"## {title}", ""] + [f"- {item}" for item in items] + [""]
    if diff["changed"]:
        lines += ["## Изменено", ""]
        for item in diff["changed"]:
            lines.append(f"- {item['label']}")
            for field, (old, new) in item["fields"].items():
                lines.append(f"  - {field}: {old} → {new}")
        lines.append("")
    return "\n".join(lines)
