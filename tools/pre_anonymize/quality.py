"""Проверка качества обезличивания на выходе (фикс 2026-09-30).

До этого результат анонимайзера молча становился рабочим текстом / оригиналом
образца: ни остатки реальных данных, ни ложные замены никто не считал.

Детекторы остатков намеренно НЕ переиспользуют паттерны anonymizer.py — они
шире и грубее: их задача найти то, что движок пропустил (dlp_scan на тех же
паттернах видит только то, что движок и так замаскировал). Ложные замены
считаются по плейсхолдерам ФИО: внутри кавычек определения термина и частые
повторы одной метки (имя подписанта встречается 1–4 раза, термин — десятки).

Отчёт содержит только счётчики и номера строк — значения не раскрываются.

    from quality import quality_report
    report = quality_report(anon_text)   # {"verdict": "ok" | "needs_review", ...}
"""
from __future__ import annotations

import re
from collections import Counter

try:  # тот же список публичных доменов, что и в движке (один источник истины)
    from anonymizer import _PUBLIC_DOMAIN
except ImportError:  # импорт как пакет tools.pre_anonymize
    from tools.pre_anonymize.anonymizer import _PUBLIC_DOMAIN

_PH = r"\[[A-ZА-ЯЁ_]+_\d+[^\]]*\]"

_LEAK_DETECTORS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"\+\d[\d\s\-().]{7,}\d|\(\d{3,5}\)\s*\d[\d\-\s]{4,}\d"),
    "latin_requisite": re.compile(
        r"\b(?:INN|KPP|OGRN|OGRNIP|PSRN|OKPO|BIC|BIK|SWIFT|IBAN|TIN|Account|A/C)\b"
        r"[^\n\[]{0,20}?\d{6,}",
        re.IGNORECASE,
    ),
    # «#_Toc123456789» — якоря оглавления Word, не реквизит.
    "long_number": re.compile(r"(?<![\d\[_])(?<!Toc)\d{9,}(?![\d\]])|\b\d{4,5}(?:\s\d{3,4}){2,}\b"),
    "url": re.compile(r"(?:https?://|www\.)[^\s)\]]+", re.IGNORECASE),
    # SWIFT-подобный код без якоря (OCR оторвал метку): 8/11 символов, с цифрой.
    "swift_like": re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b"),
    "caps_company": re.compile(
        r"\b[A-Z]{3,}(?:\s+[A-Z]{3,}){1,4}\s+(?:LIMITED|LTD|LLC|INC|CO|GMBH|CORP)\b"
    ),
}

_FIO_IN_QUOTES = re.compile(r"[“\"«‘]\s*\[ФИО_\d+\]\s*[”\"»’]")
_FIO_PH = re.compile(r"\[ФИО_(\d+)\]")

# Пороги: остаток любого типа → needs_review; ложные замены — с допуском.
FIO_REPEAT_THRESHOLD = 5      # одна метка ФИО ≥ 5 раз — вероятно термин, не имя
FIO_QUOTES_THRESHOLD = 1      # ФИО в кавычках определения — почти всегда термин
FIO_REPEATED_LABELS_THRESHOLD = 2


def _lines(text: str, pattern: re.Pattern[str], limit: int = 5) -> list[int]:
    out: list[int] = []
    for m in pattern.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        if line not in out:
            out.append(line)
        if len(out) >= limit:
            break
    return out


def quality_report(anon_text: str) -> dict:
    """Счётчики остатков и ложных замен + вердикт. Значения не возвращаются."""
    leaks: dict[str, int] = {}
    leak_lines: dict[str, list[int]] = {}
    for key, pat in _LEAK_DETECTORS.items():
        found = pat.findall(anon_text)
        if key == "url":
            # публичные правовые ресурсы (pravo.gov.ru, wikipedia…) — не остаток
            found = [u for u in found if not _PUBLIC_DOMAIN.search(
                re.sub(r"^(?i:https?://)", "", u).split("/")[0] + "/")]
        n = len(found)
        if n:
            leaks[key] = n
            leak_lines[key] = _lines(anon_text, pat)

    fio_counts = Counter(_FIO_PH.findall(anon_text))
    repeated = sorted(i for i, c in fio_counts.items() if c >= FIO_REPEAT_THRESHOLD)
    in_quotes = len(_FIO_IN_QUOTES.findall(anon_text))
    false_positives: dict[str, int] = {}
    if in_quotes:
        false_positives["fio_in_quotes"] = in_quotes
    if repeated:
        false_positives["fio_repeated"] = len(repeated)

    fp_flag = (
        in_quotes >= FIO_QUOTES_THRESHOLD
        or len(repeated) >= FIO_REPEATED_LABELS_THRESHOLD
    )
    verdict = "needs_review" if (leaks or fp_flag) else "ok"
    return {
        "verdict": verdict,
        "leaks": leaks,
        "leak_lines": leak_lines,
        "false_positives": false_positives,
        "fio_placeholders": sum(fio_counts.values()),
        "fio_labels": len(fio_counts),
    }


def summary_line(report: dict) -> str:
    """Короткая строка для шапки оригинала/лога (без значений)."""
    if report["verdict"] == "ok":
        return "автопроверка обезличивания: ok"
    parts = [f"{k}: {v}" for k, v in report["leaks"].items()]
    parts += [f"{k}: {v}" for k, v in report["false_positives"].items()]
    return "автопроверка обезличивания: needs_review — " + ", ".join(parts)
