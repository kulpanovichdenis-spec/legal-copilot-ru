#!/usr/bin/env python3
"""Перекрёстные ссылки в тексте договора: кто ссылается на пункт и какие ссылки висят.

Работает с нормализованным текстом договора (markdown / txt после tools/doc_ingest).
Не толкует договор: только находит упоминания номеров пунктов, разделов и
приложений и сопоставляет их с номерами пунктов, которые есть в тексте.

Команды:
  find     — все места, где упоминаются заданные пункты (и, по желанию, термины):
             карта влияния для amendment-drafter («что ещё затронет изменение п. 5.2»).
  dangling — ссылки на номера пунктов, которых в документе нет: проверка после
             перенумерации (contract-redesign) и после «исключить пункт» в ДС.

Нумерация пунктов распознаётся по началу строки: «5.2.», «5.2», «**5.2.**», «## 5.».
Ссылки — после слов пункт/п./пп./подпункт/раздел/статья/ст. (в любом падеже),
включая перечисления «пп. 5.1, 5.3 и 7.2» и диапазоны «5.1–5.4» одного уровня.

Usage:
    python tools/contract_redesign/xref.py find --file PATH --clause 5.2 [--clause 7] [--term "Упаковочные материалы"]
    python tools/contract_redesign/xref.py dangling --file PATH [--exclude 8.13]
    python tools/contract_redesign/xref.py selftest
"""
from __future__ import annotations

import argparse
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

NUM = r"\d+(?:\.\d+)*"
HEAD_RE = re.compile(rf"^\s*(?:#+\s*)?(?:\*\*)?\s*({NUM})\.?(?:\*\*)?[\s\t]")
KEYWORD = (r"(?:п\.|пп\.|пункт\w*|подпункт\w*|раздел\w*|стать\w*|ст\.|абзац\w*\s+\w+\s+(?:п\.|пункт\w*))")
# ключевое слово, затем перечень номеров: «5.1, 5.3 и 7.2», «5.1–5.4», «5.1 - 5.4»
REF_RE = re.compile(
    rf"(?<![\w]){KEYWORD}\s*({NUM}(?:\s*(?:,|и|или|–|—|-)\s*{NUM})*)",
    re.IGNORECASE,
)
ITEM_RE = re.compile(rf"({NUM})(?:\s*(–|—|-)\s*({NUM}))?")
APPENDIX_RE = re.compile(r"приложени\w*\s*№?\s*(\d+)", re.IGNORECASE)
# ссылка на норму закона, а не на пункт договора: «ст. 1296 ГК РФ», «п. 1 ст. 450 ГК РФ», «ч. 5 ст. 14.3 КоАП»
LAW_TAIL_RE = re.compile(
    r"^[\s,]*(?:(?:ч\.|част\w*|п\.|пункт\w*|ст\.|стать\w*|подп\.)\s*\d+(?:\.\d+)*[\s,]*)*"
    r"(?:ГК|АПК|ГПК|НК|ТК|КоАП|УК|ЖК|ЗК|БК|КАС|Кодекс\w*|Закон\w*|ФЗ|Федеральн\w*|Постановлени\w*|Приказ\w*|Конституци\w*)",
    re.IGNORECASE,
)


def _plausible(num: str) -> bool:
    # «354551 …» в начале строки — индекс/сумма, не пункт; реальные номера пунктов короткие
    return all(len(part) <= 3 for part in num.split("."))


def headings(lines: list[str]) -> dict[str, int]:
    """Номер пункта → номер строки, где он начинается."""
    out: dict[str, int] = {}
    for i, line in enumerate(lines, 1):
        m = HEAD_RE.match(line)
        if m and _plausible(m.group(1)):
            out.setdefault(m.group(1).rstrip("."), i)
    return out


def _expand(a: str, b: str) -> list[str]:
    pa, pb = a.split("."), b.split(".")
    if len(pa) != len(pb) or pa[:-1] != pb[:-1] or int(pb[-1]) < int(pa[-1]) or int(pb[-1]) - int(pa[-1]) > 200:
        return [a, b]
    prefix = ".".join(pa[:-1])
    return [f"{prefix}.{n}" if prefix else str(n) for n in range(int(pa[-1]), int(pb[-1]) + 1)]


def references(lines: list[str], skip_qualified: tuple[str, ...] = ()) -> list[tuple[int, str, str]]:
    """(номер строки, номер пункта, контекст) для каждой ссылки на пункт.

    Ссылки на нормы закона пропускаются. skip_qualified — слова-указатели другого
    документа сразу после номера («Договора» в ДС/приложении): такие ссылки ведут
    не в этот текст и пропускаются."""
    heads = headings(lines)
    head_lines = {ln: num for num, ln in heads.items()}
    refs = []
    for i, line in enumerate(lines, 1):
        for m in REF_RE.finditer(line):
            tail = line[m.end():]
            if LAW_TAIL_RE.match(tail):
                continue
            if skip_qualified and re.match(r"^\s*(?:" + "|".join(re.escape(w) for w in skip_qualified) + r")",
                                           tail, re.IGNORECASE):
                continue
            for im in ITEM_RE.finditer(m.group(1)):
                nums = _expand(im.group(1), im.group(3)) if im.group(3) else [im.group(1)]
                for n in nums:
                    n = n.rstrip(".")
                    if head_lines.get(i) == n and m.start() < 3:
                        continue  # сам заголовок пункта
                    refs.append((i, n, line.strip()))
    return refs


def owner(lines: list[str], line_no: int) -> str:
    """Какому пункту принадлежит строка (последний номер-заголовок выше)."""
    cur = "преамбула"
    for i in range(line_no, 0, -1):
        m = HEAD_RE.match(lines[i - 1])
        if m:
            return m.group(1).rstrip(".")
    return cur


def _under(ref: str, clause: str) -> bool:
    return ref == clause or ref.startswith(clause + ".") or clause.startswith(ref + ".")


def find(text: str, clauses: list[str], terms: list[str]) -> list[str]:
    lines = text.splitlines()
    out = []
    for c in clauses:
        hits = [(ln, n, ctx) for ln, n, ctx in references(lines) if _under(n, c)]
        out.append(f"## Ссылки на п. {c}: {len(hits)}")
        for ln, n, ctx in hits:
            out.append(f"- строка {ln} (в п. {owner(lines, ln)}), ссылка на {n}: {ctx[:160]}")
    for t in terms:
        stem = re.escape(t[:-2] if len(t) > 5 else t)
        rx = re.compile(stem, re.IGNORECASE)
        hits = [(i, line.strip()) for i, line in enumerate(lines, 1) if rx.search(line)]
        out.append(f"## Термин «{t}»: {len(hits)} строк")
        for ln, ctx in hits:
            out.append(f"- строка {ln} (в п. {owner(lines, ln)}): {ctx[:160]}")
    apps = sorted({m.group(1) for line in lines for m in APPENDIX_RE.finditer(line)}, key=int)
    if apps:
        out.append("## Упоминаемые приложения: " + ", ".join(f"№ {a}" for a in apps))
    return out


def dangling(text: str, exclude: list[str], skip_qualified: tuple[str, ...] = ()) -> list[tuple[int, str, str]]:
    lines = text.splitlines()
    existing = set(headings(lines))
    bad = []
    for ln, n, ctx in references(lines, skip_qualified):
        if n in exclude or n not in existing and not any(e.startswith(n + ".") for e in existing):
            bad.append((ln, n, ctx))
    return bad


SAMPLE = """ДОГОВОР ПОСТАВКИ
1. Предмет
1.1. Поставщик передаёт Товар по Спецификации (Приложение № 1).
5. Приёмка
5.1. Покупатель осматривает Товар в течение 5 рабочих дней.
5.2. Покупатель оплачивает Товар в течение 30 дней после подписания УПД.
5.3. При нарушении срока, указанного в п. 5.2 Договора, Покупатель уплачивает неустойку.
7. Ответственность
7.1. За нарушение обязательств, предусмотренных пунктами 5.1–5.3, Стороны отвечают по закону.
7.2. Порядок согласно разделу 9 и пп. 5.2, 8.4 применяется к расчётам.
**8.1.** Претензионный порядок (Приложение № 2), с учётом ст. 1296 ГК РФ и п. 1 ст. 450 ГК РФ.
8.2. Условия п. 12.4 Договора поставки № 1 применяются к Спецификации.
354551, г. Москва, ул. Примерная
"""


def selftest() -> int:
    lines = SAMPLE.splitlines()
    heads = headings(lines)
    assert {"1", "1.1", "5", "5.1", "5.2", "5.3", "7", "7.1", "7.2", "8.1"} <= set(heads), heads
    assert "354551" not in heads, heads                # индекс в начале строки — не пункт
    got = find(SAMPLE, ["5.2"], ["Товар"])
    txt = "\n".join(got)
    assert "Ссылки на п. 5.2: 3" in txt, txt           # п. 5.3, диапазон 5.1–5.3 в 7.1, пп. 5.2 в 7.2
    assert "(в п. 5.3)" in txt and "(в п. 7.1)" in txt and "(в п. 7.2)" in txt, txt
    assert "Упоминаемые приложения: № 1, № 2" in txt, txt
    bad = {n for _, n, _ in dangling(SAMPLE, [])}
    assert bad == {"9", "8.4", "12.4"}, bad            # нормы ГК РФ не считаются ссылками на пункты
    bad = {n for _, n, _ in dangling(SAMPLE, [], ("Договора",))}
    assert bad == {"9", "8.4"}, bad                    # «п. 12.4 Договора поставки» ведёт в другой документ
    bad = {n for _, n, _ in dangling(SAMPLE, ["5.2"])}
    assert "5.2" in bad, bad                           # после «исключить п. 5.2» ссылки на него висят
    assert _expand("5.1", "5.3") == ["5.1", "5.2", "5.3"]
    print("SELFTEST OK: 10 проверок пройдено")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("find")
    p.add_argument("--file", required=True)
    p.add_argument("--clause", action="append", default=[])
    p.add_argument("--term", action="append", default=[])
    p = sub.add_parser("dangling")
    p.add_argument("--file", required=True)
    p.add_argument("--exclude", action="append", default=[], help="пункты, исключаемые ДС")
    p.add_argument("--skip-qualified", action="append", default=[],
                   help="слово после номера, указывающее на другой документ (напр. «Договора» при проверке ДС или приложения)")
    sub.add_parser("selftest")
    args = ap.parse_args()
    if args.cmd == "selftest":
        return selftest()
    text = open(args.file, encoding="utf-8").read()
    if args.cmd == "find":
        if not args.clause and not args.term:
            ap.error("укажите --clause и/или --term")
        print("\n".join(find(text, args.clause, args.term)))
        return 0
    bad = dangling(text, args.exclude, tuple(args.skip_qualified))
    for ln, n, ctx in bad:
        print(f"строка {ln}: ссылка на отсутствующий п. {n}: {ctx[:160]}")
    print(f"Итог: висящих ссылок {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
