# -*- coding: utf-8 -*-
"""CLI фирменного стиля.

    python -m tools.brand_kit scan [--root DIR] [--force]   разбор _inbox/ и originals/ → brand.yaml
    python -m tools.brand_kit list [--manifest FILE]        бланки, назначение и слоты
    python -m tools.brand_kit demo <blank_id> <out.docx>    макет письма на бланке (только маркеры)
"""
from __future__ import annotations

import argparse
import json
import sys

from .letterhead import LetterheadDoc, load_manifest
from .scan import scan


def _demo(blank: str | None, out: str, manifest: str | None) -> dict:
    d = LetterheadDoc(blank, manifest=manifest)
    samples = {
        "date": "[ДАТА]", "addressee": ["[ДОЛЖНОСТЬ АДРЕСАТА]", "[НАИМЕНОВАНИЕ]", "[И. О. ФАМИЛИЯ]", "[АДРЕС]"],
        "addressee_name": "[И. О. ФАМИЛИЯ]", "addressee_position": "[ДОЛЖНОСТЬ]", "addressee_org": "[НАИМЕНОВАНИЕ]",
        "addressee_address": "[АДРЕС]", "title": "О [ПРЕДМЕТ ПИСЬМА]", "salutation": "Уважаемый [ИМЯ ОТЧЕСТВО]!",
        "salutation_name": "[ИМЯ ОТЧЕСТВО]", "reply_to": "На № [ПРОВЕРИТЬ РЕКВИЗИТЫ] от [ПРОВЕРИТЬ ДАТУ]",
        "signer_name": "[И. О. ФАМИЛИЯ]", "signer_position": "[ДОЛЖНОСТЬ]",
        "executor": "[ФИО]", "executor_phone": "[ТЕЛЕФОН]", "executor_email": "[ПОЧТА]",
    }
    for slot in d.slots():
        if slot in samples:
            d.fill(slot, samples[slot])
    d.para("[Первый абзац: цель письма и ответ по существу.]")
    d.point("1.", "[Пункт с привязкой к документу.]")
    d.point("2.", "[Пункт.]")
    d.para("[Просьба, действие и срок.]")
    if not any(s.startswith("signer_") for s in d.slots()):
        d.signature(["[Должность]", "________________ / [И. О. Фамилия]"])
    return d.save(out)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m tools.brand_kit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--root")
    s.add_argument("--force", action="store_true", help="перезаписать brand.yaml (иначе brand.draft.yaml)")
    ls = sub.add_parser("list")
    ls.add_argument("--manifest")
    dm = sub.add_parser("demo")
    dm.add_argument("blank")
    dm.add_argument("out")
    dm.add_argument("--manifest")
    a = ap.parse_args()
    if a.cmd == "scan":
        print(json.dumps(scan(a.root, force=a.force), ensure_ascii=False, indent=2))
    elif a.cmd == "list":
        m, root = load_manifest(a.manifest)
        print(f"{root}  status: {m.get('status')}  company: {m.get('company')}  default: {m.get('default_blank')}")
        for b in m.get("blanks") or []:
            print(f"- {b['id']}: {b.get('title')} | use_for={b.get('use_for')} | слоты: {', '.join(b.get('slots') or {})}")
    elif a.cmd == "demo":
        print(json.dumps(_demo(a.blank, a.out, a.manifest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
