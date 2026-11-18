#!/usr/bin/env python3
"""Якорь доказательства: дословная цитата + место + проверка, что цитата есть в источнике.

Решение юриста 2026-10-13:
сверка дословная, допускается разница только в пробелах, переносах, кавычках и тире.

    anchor = {source_doc, quote, location, quote_check, checked_at}

quote_check:
- matched            — цитата найдена непрерывным фрагментом (после нормализации);
- location_mismatch  — цитата есть, но не рядом с указанным пунктом;
- ocr_fuzzy          — источник распознан OCR, цитата найдена нечётко (OCR недословный);
- mismatch           — цитаты в источнике нет (перефраз, собранная цитата, не тот документ);
- source_unavailable — файла нет или его нельзя читать (оригинал в `_anonymizer`);
- not_checked        — проверка не запускалась.

Текст источника берётся через `tools/doc_ingest/router.py` (`.md`/`.txt` — напрямую) и
кэшируется только в памяти процесса. Оригиналы из `workflow/_anonymizer/` не читаются —
только `*.anon.md` (CLAUDE.md, «Конфиденциальность»).

Usage:
    python -m tools.evidence_anchor.anchor check --doc PATH --quote TEXT [--location LOC]
    python -m tools.evidence_anchor.anchor selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

QUOTE_CHECKS = ("matched", "location_mismatch", "ocr_fuzzy", "mismatch", "source_unavailable", "not_checked")
VERIFIED_CHECKS = ("matched", "ocr_fuzzy")
OCR_THRESHOLD = 0.85
TEXT_SUFFIXES = (".md", ".txt")

_cache: dict[str, tuple[str, bool]] = {}


# ---------- нормализация ----------

_QUOTES = str.maketrans({c: '"' for c in "«»„“”‟″〝〞＂"} | {c: "'" for c in "‘’‚‛′"})
_DASHES = re.compile("[‐‑‒–—―−]")


def normalize(text: str) -> str:
    """Только то, что юрист разрешил: пробелы, переносы, кавычки, тире (+ разметка markdown)."""
    text = text.replace("\u00ad", "")                      # мягкий перенос
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)      # перенос слова на строке
    text = text.translate(_QUOTES)
    text = _DASHES.sub("-", text)
    text = re.sub(r"(\*\*|__|`)", "", text)                 # жирный/код из markdown
    text = re.sub(r"(?m)^\s*(#{1,6}|>|[-*+]\s)\s*", "", text)  # заголовки, цитаты, маркеры списков
    text = text.replace("|", " ")
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


# ---------- источник ----------

def _forbidden(path: Path) -> str | None:
    parts = [p.lower() for p in path.parts]
    if "_anonymizer" in parts and not path.name.lower().endswith(".anon.md"):
        return "оригинал из workflow/_anonymizer не читается — только *.anon.md"
    return None


def source_text(path: str | Path) -> tuple[str, bool]:
    """(текст, это_OCR). Исключения: FileNotFoundError, PermissionError."""
    path = Path(path).resolve()
    reason = _forbidden(path)
    if reason:
        raise PermissionError(reason)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    key = f"{path}:{path.stat().st_mtime_ns}"
    if key in _cache:
        return _cache[key]
    if path.suffix.lower() in TEXT_SUFFIXES:
        result = (path.read_text(encoding="utf-8", errors="replace"), False)
    else:
        from tools.doc_ingest.router import convert  # noqa: PLC0415
        conv = convert(path)
        backend = str((conv.get("metadata") or {}).get("backend") or "")
        result = (conv.get("markdown") or "", "ocr" in backend.lower() or "tesseract" in backend.lower())
    _cache[key] = result
    return result


# ---------- сверка ----------

def _fuzzy_score(quote: str, text: str) -> float:
    """Посимвольное сходство цитаты с лучшим фрагментом текста (OCR ошибается внутри слов).

    Кандидаты на начало фрагмента — места, где в тексте встречается любое слово цитаты
    (≥ 4 букв); фрагмент выравнивается по смещению этого слова в цитате.
    """
    q, t = quote.lower(), text.lower()
    if not q or not t:
        return 0.0
    starts: set[int] = set()
    for m in re.finditer(r"\w{4,}", q):
        for hit in re.finditer(re.escape(m.group(0)), t):
            starts.add(max(0, hit.start() - m.start()))
            if len(starts) > 500:
                break
    best = 0.0
    for s in sorted(starts):
        window = t[s:s + len(q) + 5]
        best = max(best, difflib.SequenceMatcher(None, q, window).ratio())
        if best >= 0.99:
            break
    return best


_HEAD = re.compile(r"(?:п\.\s*|пункт\s+|ст\.\s*|статья\s+)?(\d+(?:\.\d+)*)\.?(?=\s|$)", re.I)


def prepare(raw: str) -> tuple[str, list[tuple[str, int]]]:
    """Нормализованный текст и номера пунктов в начале строк с их позициями в этом тексте."""
    raw = raw.replace("\u00ad", "")
    raw = re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", raw)
    parts: list[str] = []
    heads: list[tuple[str, int]] = []
    off = 0
    for line in raw.splitlines():
        n = normalize(line)
        if not n:
            continue
        m = _HEAD.match(n)
        # заголовок пункта: «5.1.», «5.1 …», «п. 5.», — но не просто число в начале строки
        if m and ("." in m.group(1) or n[m.end(1):m.end(1) + 1] == "."):
            heads.append((m.group(1), off))
        parts.append(n)
        off += len(n) + 1
    return " ".join(parts), heads


def _location_ok(location: str, heads: list[tuple[str, int]], pos: int) -> bool | None:
    """Цитата стоит под пунктом из места (или его подпунктом)? None — проверить нельзя."""
    nums = re.findall(r"\d+(?:\.\d+)*", location or "")
    if not nums or not heads:
        return None
    num = nums[-1]
    if not any(h == num or h.startswith(num + ".") for h, _ in heads):
        return None  # в документе нет такой нумерации (автонумерация Word и т. п.)
    before = [h for h, o in heads if o <= pos]
    if not before:
        return False
    nearest = before[-1]
    return nearest == num or nearest.startswith(num + ".")


def check(doc: str | Path, quote: str, location: str | None = None) -> dict:
    """Проверить цитату по источнику. Возвращает {quote_check, detail, checked_at}."""
    now = dt.date.today().isoformat()
    if not (quote or "").strip():
        return {"quote_check": "mismatch", "detail": "пустая цитата", "checked_at": now}
    try:
        raw, is_ocr = source_text(doc)
    except PermissionError as exc:
        return {"quote_check": "source_unavailable", "detail": str(exc), "checked_at": now}
    except (FileNotFoundError, OSError) as exc:
        return {"quote_check": "source_unavailable", "detail": f"файл не найден или не читается: {exc}",
                "checked_at": now}
    except Exception as exc:  # noqa: BLE001 — сбой конвертера не роняет модель дела
        return {"quote_check": "source_unavailable", "detail": f"не удалось извлечь текст: {exc}",
                "checked_at": now}
    text, heads = prepare(raw)
    q = normalize(quote)
    pos = text.find(q)
    if pos < 0:
        low = text.lower().find(q.lower())
        if low >= 0:
            pos = low
    if pos >= 0:
        loc = _location_ok(location or "", heads, pos)
        if loc is False:
            return {"quote_check": "location_mismatch",
                    "detail": f"цитата есть в документе, но не рядом с «{location}»", "checked_at": now}
        return {"quote_check": "matched", "detail": "", "checked_at": now}
    if is_ocr:
        score = _fuzzy_score(q, text)
        if score >= OCR_THRESHOLD:
            return {"quote_check": "ocr_fuzzy", "detail": f"OCR, совпадение {score:.2f}", "checked_at": now}
        return {"quote_check": "mismatch", "detail": f"OCR, лучшее совпадение {score:.2f}", "checked_at": now}
    return {"quote_check": "mismatch", "detail": "фрагмента нет в источнике — перефраз или не тот документ",
            "checked_at": now}


def _anon_twin(path: Path) -> Path:
    """В проекте анонимайзера вместо оригинала читается его обезличенная копия."""
    if "_anonymizer" in [p.lower() for p in path.parts] and not path.name.lower().endswith(".anon.md"):
        twin = path.with_name(f"{path.stem}.anon.md")
        if twin.is_file():
            return twin
    return path


def resolve_doc(source_doc: str, base_dir: str | Path) -> Path:
    """Файл источника для записи модели дела.

    source_doc — путь относительно папки дела, абсолютный путь или просто имя файла
    (так его пишет matter-knowledge). Имя ищется по папке дела; при нескольких
    совпадениях берётся ближайшее к корню дела. Не найдено — возвращается исходный путь
    (check() вернёт source_unavailable).
    """
    p = Path(source_doc)
    base = Path(base_dir)
    direct = p if p.is_absolute() else base / p
    if direct.is_file():
        return _anon_twin(direct)
    if not p.is_absolute() and base.is_dir():
        stem_twin = f"{p.stem}.anon.md"
        hits = [x for x in base.rglob("*") if x.is_file() and x.name in (p.name, stem_twin)]
        if hits:
            hits.sort(key=lambda x: (x.name != p.name, len(x.relative_to(base).parts)))
            return _anon_twin(hits[0])
    return direct


def make_anchor(source_doc: str, quote: str, location: str | None, base_dir: str | Path) -> dict:
    res = check(resolve_doc(source_doc, base_dir), quote, location)
    return {"quote": quote, "location": location or "", "quote_check": res["quote_check"],
            "check_detail": res["detail"], "checked_at": res["checked_at"]}


def validate_anchor(anchor, where: str) -> list[str]:
    if anchor in (None, {}):
        return []
    if not isinstance(anchor, dict):
        return [f"{where}: anchor должен быть словарём"]
    errs = []
    if not str(anchor.get("quote", "")).strip():
        errs.append(f"{where}: пустая anchor.quote")
    if anchor.get("quote_check", "not_checked") not in QUOTE_CHECKS:
        errs.append(f"{where}: anchor.quote_check должен быть из {QUOTE_CHECKS}")
    return errs


def is_verified(anchor) -> bool:
    return isinstance(anchor, dict) and anchor.get("quote_check") in VERIFIED_CHECKS


# ---------- CLI ----------

def selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        doc = Path(d) / "dog.md"
        doc.write_text("5.1. Покупатель оплачивает товар в течение 10 (десяти)\nрабочих дней с «даты» поставки.\n"
                       "7.2. Поставщик отвечает за качество.", encoding="utf-8")
        assert check(doc, 'в течение 10 (десяти) рабочих дней с "даты" поставки', "п. 5.1")["quote_check"] == "matched"
        assert check(doc, "в течение 10 дней", "п. 5.1")["quote_check"] == "mismatch"
        assert check(doc, "Поставщик отвечает за качество", "п. 5.1")["quote_check"] == "location_mismatch"
        assert check(Path(d) / "нет.md", "x")["quote_check"] == "source_unavailable"
        anon = Path(d) / "_anonymizer" / "дело" / "оригинал.md"
        anon.parent.mkdir(parents=True)
        anon.write_text("секрет", encoding="utf-8")
        assert check(anon, "секрет")["quote_check"] == "source_unavailable"
    print("selftest OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--doc", required=True)
    c.add_argument("--quote", required=True)
    c.add_argument("--location")
    sub.add_parser("selftest")
    args = ap.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    res = check(args.doc, args.quote, args.location)
    print(f"{res['quote_check']}" + (f": {res['detail']}" if res["detail"] else ""))
    return 0 if res["quote_check"] in VERIFIED_CHECKS else 1


if __name__ == "__main__":
    sys.exit(main())
