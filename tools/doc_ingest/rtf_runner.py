# -*- coding: utf-8 -*-
"""
tools/doc_ingest/rtf_runner.py

RTF → обычный текст через striprtf, локально. markitdown 0.0.2 отдаёт .rtf
как есть, то есть сырой разметкой `{\\rtf1\\ansi…}` (дефект 2026-10-12).

Кодировка. RTF — 7-битный текст, кириллица приходит экранами `\\'xx` или
`\\uN`, но часть генераторов кладёт байты кодовой страницы без экранирования.
Поэтому файл декодируется кодовой страницей из `\\ansicpgN`; если её нет,
а в таблице шрифтов есть кириллический `\\fcharset204`, берётся cp1251,
иначе cp1252 (умолчание спецификации RTF). Та же страница передаётся
в striprtf для экранов `\\'xx`; шрифты со своим `\\fcharset` striprtf
декодирует по нему сам.

Python API:
    from tools.doc_ingest.rtf_runner import convert
    result = convert("Устав.rtf")   # {"markdown": str, "metadata": dict}
"""
from __future__ import annotations

import codecs
import re
import time
from pathlib import Path

from striprtf.striprtf import rtf_to_text

_ANSICPG = re.compile(rb"\\ansicpg(\d+)")
_CYRILLIC_FONT = re.compile(rb"\\fcharset204\b")


def _striprtf_version() -> str:
    try:
        from importlib.metadata import version
        return version("striprtf")
    except Exception:
        return "unknown"


def detect_codepage(raw: bytes) -> str:
    """Кодовая страница документа: `\\ansicpg`, затем `\\fcharset204`, затем cp1252."""
    match = _ANSICPG.search(raw[:4096])
    if match:
        candidate = f"cp{int(match.group(1))}"
        try:
            codecs.lookup(candidate)
            return candidate
        except LookupError:
            pass
    if _CYRILLIC_FONT.search(raw):
        return "cp1251"
    return "cp1252"


def convert(path: str | Path) -> dict:
    """Извлечь текст RTF. Возвращает {"markdown", "metadata"} как markitdown_runner."""
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Файл не найден: {p}")
    started = time.time()
    raw = p.read_bytes()
    codepage = detect_codepage(raw)
    text = rtf_to_text(raw.decode(codepage, errors="replace"),
                       encoding=codepage, errors="replace")
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()

    warnings: list[str] = []
    if "\ufffd" in text:
        warnings.append(
            f"[НЕ РАСПОЗНАНО] часть символов RTF не декодирована ({codepage}) — "
            "сверить с оригиналом"
        )
    return {
        "markdown": text,
        "metadata": {
            "source": p.name,
            "source_path": str(p),
            "extension": p.suffix.lower(),
            "size_bytes": len(raw),
            "backend": "striprtf",
            "backend_version": _striprtf_version(),
            "codepage": codepage,
            "duration_sec": round(time.time() - started, 3),
            "char_count": len(text),
            "line_count": text.count("\n") + 1,
            "warnings": warnings,
        },
    }
