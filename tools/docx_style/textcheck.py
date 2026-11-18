#!/usr/bin/env python3
"""Сверка текста при переоформлении .docx: ни одно слово не потеряно и не добавлено.

Применяется, когда юрист просит оформить готовый документ по правилам проекта
(«оформи договор», «переложи в наш стиль») — текст при этом меняться не должен.
Сравнивает мультимножества слов исходника и результата: абзацы документа,
ячейки таблиц (объединённые ячейки учитываются один раз), колонтитулы не учитываются
(в результат они добавляются намеренно).

Допустимые расхождения, которые не считаются изменением текста:
- служебные знаки оформления: маркеры списков «▪ • – —», табуляции;
- разделители языков «/» между EN и RU (при раскладке двуязычного текста по колонкам).

Всё прочее «потеряно» / «добавлено» выводится юристу как расхождение.

Usage:
    python tools/docx_style/textcheck.py <исходник.docx> <результат.docx> [--ignore СЛОВО ...]
    python tools/docx_style/textcheck.py selftest
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from collections import Counter

from docx import Document

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

LAYOUT_TOKENS = {"▪", "•", "–", "—", "-"}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\s/]+", text) if w not in LAYOUT_TOKENS]


def document_words(path: str) -> Counter:
    doc = Document(path)
    words: list[str] = []
    for p in doc.paragraphs:
        words += _words(p.text)

    def walk_tables(tables):
        for tbl in tables:
            for row in tbl.rows:
                seen = []
                for c in row.cells:
                    if any(c._tc is s for s in seen):
                        continue
                    seen.append(c._tc)
                    for p in c.paragraphs:
                        words.extend(_words(p.text))
                    walk_tables(c.tables)

    walk_tables(doc.tables)
    return Counter(words)


def compare(src: str, out: str, ignore: tuple[str, ...] = ()) -> tuple[Counter, Counter]:
    cs, co = document_words(src), document_words(out)
    for w in ignore:
        cs.pop(w, None)
        co.pop(w, None)
    return cs - co, co - cs


def selftest() -> int:
    from docx.shared import Pt  # noqa: F401  (проверка, что python-docx доступен)
    tmp = tempfile.mkdtemp(prefix="textcheck_")
    a = Document()
    a.add_paragraph("1. Goods and Price / 1. Товар и цена")
    t = a.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "The Supplier delivers the Goods."
    t.rows[0].cells[1].text = "Поставщик поставляет Товар."
    src = os.path.join(tmp, "src.docx")
    a.save(src)

    b = Document()
    b.add_paragraph("1.\tGoods and Price")
    b.add_paragraph("1.\tТовар и цена")
    b.add_paragraph("▪\tThe Supplier delivers the Goods.")
    b.add_paragraph("Поставщик поставляет Товар.")
    ok_out = os.path.join(tmp, "ok.docx")
    b.save(ok_out)
    lost, added = compare(src, ok_out)
    assert not lost and not added, (lost, added)

    c = Document()
    c.add_paragraph("1. Goods and Price / 1. Товар и цена")
    c.add_paragraph("The Supplier delivers Goods.")  # потеряно «the»
    c.add_paragraph("Поставщик поставляет Товар. В срок.")  # добавлено «В срок.»
    bad_out = os.path.join(tmp, "bad.docx")
    c.save(bad_out)
    lost, added = compare(src, bad_out)
    assert lost == Counter({"the": 1}), lost
    assert added == Counter({"В": 1, "срок.": 1}), added
    lost, added = compare(src, bad_out, ignore=("the", "В", "срок."))
    assert not lost and not added, (lost, added)
    print("SELFTEST OK: 4 проверки пройдено")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source")
    ap.add_argument("result")
    ap.add_argument("--ignore", nargs="*", default=[], help="слова, которые разрешено добавить/убрать")
    args = ap.parse_args()
    lost, added = compare(args.source, args.result, tuple(args.ignore))
    total = sum(document_words(args.source).values())
    print(f"Слов в исходнике: {total}")
    print(f"Потеряно: {sum(lost.values())}" + (f" — {dict(lost)}" if lost else ""))
    print(f"Добавлено: {sum(added.values())}" + (f" — {dict(added)}" if added else ""))
    return 1 if lost or added else 0


if __name__ == "__main__":
    sys.exit(main())
