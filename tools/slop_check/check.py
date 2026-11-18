#!/usr/bin/env python3
"""Slop-линтер: подсвечивает AI-slop в готовом тексте (.txt/.md/.docx).

Ничего не переписывает сам — только показывает кандидатов с местом и категорией,
как cross-ref-checker не удаляет ссылки. Решение убрать/оставить — за человеком.
Реестр — references/anti-slop.md (единственный источник): фразовые паттерны и
структурные проверки с порогами; patterns.py его загружает, здесь — функции
структурных проверок (STRUCTURAL).

Запуск:
    python tools/slop_check/check.py <файл> [<файл> ...]
    python tools/slop_check/check.py --help

Код возврата: 1, если найден хотя бы один паттерн severity=high; иначе 0.
(«review»-находки сами по себе код возврата не меняют.)
.docx читается с принятыми исправлениями: удалённое рецензированием не проверяется.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from patterns import CHECKS, PATTERNS  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


@dataclass
class Finding:
    line: int
    category: str
    severity: str
    matched: str
    message: str


def scan_text(text: str) -> list[Finding]:
    """Фразовые паттерны построчно + структурные проверки на весь текст."""
    lines = text.splitlines() or [text]
    findings: list[Finding] = []
    for lineno, line in enumerate(lines, start=1):
        for pat in PATTERNS:
            m = pat.regex.search(line)
            if m:
                findings.append(Finding(lineno, pat.category, pat.severity,
                                        m.group(0).strip(), pat.message))
    for chk in CHECKS:
        for lineno, matched in STRUCTURAL[chk.name](lines, text, **chk.params):
            findings.append(Finding(lineno, chk.category, chk.severity, matched, chk.message))
    findings.sort(key=lambda f: f.line)
    return findings


# --- Структурные проверки (пороги — в anti-slop.md) -----------------------------

_STOP = set("""и в во на по с со к ко о об от до из за для при без над под про а но или
что как это то так же ли не ни бы был была были быть его её ее их он она они оно мы вы
также который которая которое которые этот эта эти том тем этой этого всё все уже ещё
""".split())
_WORD = re.compile(r"[a-zа-яё]+", re.IGNORECASE)
_MARKER = re.compile(r"\[[^\]]*\]")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁ«])")
_LIST_ITEM = re.compile(r"^\s*\d+[.)]\s")
_PREAMBLE = re.compile(r"именуем\w*\s+в\s+дальнейшем", re.IGNORECASE)  # преамбулы сторон
TABLE_MARK = "⁣"  # невидимый разделитель: так _read_docx помечает абзацы из ячеек таблиц


def _stems(s: str) -> list[str]:
    return [w.lower()[:5] for w in _WORD.findall(_MARKER.sub(" ", s))
            if len(w) > 2 and w.lower() not in _STOP]


def _grams(stems: list[str], n: int = 3) -> set[tuple]:
    return {tuple(stems[i:i + n]) for i in range(len(stems) - n + 1)}


def _is_heading(line: str) -> bool:
    s = line.strip()
    return 0 < len(s) <= 120 and not s.endswith((".", ":", ";", ",")) and (
        bool(re.match(r"^\d+(\.\d+)*\.?\s", s)) or len(s.split()) <= 10)


def dash_density(lines, text, *, min_count: int, per_1000: float):
    n, size = text.count("—"), len(text)
    if size and n >= min_count and n * 1000 / size > per_1000:
        yield 0, f"{n} тире на {size} знаков"


def rhetorical_heading(lines, text, *, max_len: int):
    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if s.endswith("?") and len(s) <= max_len and _is_heading(s[:-1]):
            yield i, s


def heading_echo(lines, text, *, min_words: int, overlap: float):
    for i, line in enumerate(lines[:-1]):
        if line.startswith(TABLE_MARK) or not _is_heading(line):
            continue
        head = set(_stems(re.sub(r"^\s*\d+(\.\d+)*\.?\s", "", line)))
        if len(head) < min_words:
            continue
        j = next((k for k in range(i + 1, len(lines)) if lines[k].strip()), None)
        if j is None or lines[j].startswith(TABLE_MARK) or _is_heading(lines[j]):
            continue
        first = _SENT.split(lines[j].strip())[0]
        if len(head & set(_stems(first))) / len(head) >= overlap:
            yield j + 1, first[:80]


def repeated_content(lines, text, *, min_words: int, overlap: float, verbatim: float):
    """Пересказ уже сказанного: большая доля 3-грамм короткого предложения есть в другом.
    Почти дословная копия (≥ verbatim по Жаккару) — намеренная формула (преамбулы приложений,
    повтор условия), не флагуется. Ячейки таблиц и фрагменты со строчной буквы не сравниваются."""
    sents = []  # (line, sentence, grams)
    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if (not s or s.startswith(TABLE_MARK) or s[0].islower() or _is_heading(s)
                or (_LIST_ITEM.match(s) and len(s) < 200) or _PREAMBLE.search(s)):
            continue
        for s in _SENT.split(line.strip()):
            st = _stems(s)
            if len(st) >= min_words:
                sents.append((i, s, _grams(st)))
    for b in range(1, len(sents)):
        lb, sb, gb = sents[b]
        for a in range(b):
            la, _, ga = sents[a]
            if la == lb or not ga or not gb:
                continue
            common = len(ga & gb)
            small = min(len(ga), len(gb))
            if common / small >= overlap and common / len(ga | gb) < verbatim:
                yield lb, f"{sb[:70]}… ≈ стр.{la}"
                break


STRUCTURAL = {f.__name__: f for f in (dash_density, rhetorical_heading, heading_echo, repeated_content)}
_unknown = {c.name for c in CHECKS} - set(STRUCTURAL)
if _unknown:
    raise SystemExit(f"anti-slop.md объявляет проверки, которых нет в check.py: {sorted(_unknown)}")


def _read_docx(path: Path) -> str:
    """Текст .docx с принятыми исправлениями: w:ins учитывается, w:del и удалённые абзацы — нет."""
    try:
        from docx import Document  # python-docx
        from docx.oxml.ns import qn
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError("Для .docx нужен python-docx (pip install python-docx).") from e
    body = Document(str(path)).element.body
    out = []
    for p in body.iter(qn("w:p")):
        ppr = p.find(qn("w:pPr"))
        if ppr is not None and ppr.find(qn("w:rPr") + "/" + qn("w:del")) is not None:
            continue
        # Каждый абзац — отдельная «строка», чтобы номера соответствовали структуре.
        in_table = any(a.tag == qn("w:tc") for a in p.iterancestors())
        out.append((TABLE_MARK if in_table else "") + "".join(t.text or "" for t in p.iter(qn("w:t"))))
    return "\n".join(out)

def scan_file(path: str | Path) -> list[Finding]:
    p = Path(path)
    if p.suffix.lower() == ".docx":
        text = _read_docx(p)
    else:
        text = p.read_text(encoding="utf-8", errors="replace")
    return scan_text(text)


def _format_report(path: str, findings: list[Finding]) -> str:
    highs = [f for f in findings if f.severity == "high"]
    reviews = [f for f in findings if f.severity == "review"]
    lines = [f"\n=== {path} ==="]
    if not findings:
        lines.append("  чисто: slop-паттернов не найдено.")
        return "\n".join(lines)
    if highs:
        lines.append(f"  HIGH ({len(highs)}) — снять перед сохранением:")
        for f in highs:
            lines.append(f"    стр.{f.line} [{f.category}] «{f.matched}» — {f.message}")
    if reviews:
        lines.append(f"  REVIEW ({len(reviews)}) — проверить вручную (может быть легитимно):")
        for f in reviews:
            where = f"стр.{f.line}" if f.line else "весь текст"
            lines.append(f"    {where} [{f.category}] «{f.matched}» — {f.message}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    if not args or "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    total_high = 0
    total_review = 0
    for path in args:
        try:
            findings = scan_file(path)
        except (FileNotFoundError, RuntimeError) as e:
            print(f"\n=== {path} ===\n  ОШИБКА: {e}")
            continue
        total_high += sum(1 for f in findings if f.severity == "high")
        total_review += sum(1 for f in findings if f.severity == "review")
        print(_format_report(path, findings))
    print(f"\nИтого: HIGH={total_high}, REVIEW={total_review}.")
    if total_high:
        print("Есть HIGH-находки — вычистить по references/anti-slop.md перед сохранением.")
    return 1 if total_high else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
