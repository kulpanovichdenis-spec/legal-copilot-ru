# -*- coding: utf-8 -*-
"""Нечёткая сверка дословной цитаты с OCR-текстом страницы.

OCR недословный (ошибки в отдельных буквах, перемешанный порядок чтения возле
штампов), поэтому точного совпадения недостаточно. Результат информационный и
не заменяет сверку юристом по скану:

  matched    — цитата найдена в тексте страницы после нормализации;
  fuzzy      — точного совпадения нет, но найден фрагмент со сходством >= порога;
  not_found  — похожего фрагмента нет (ошибка цитаты либо сбой OCR).

Поиск идёт в два этапа: дешёвый отбор нескольких кандидатных окон страницы по
числу общих слов, затем точное сравнение символов только для кандидатов. Полный
перебор окон с difflib на странице в 300-400 слов занимает секунды на цитату.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter

DEFAULT_THRESHOLD = 0.90
CANDIDATES = 5   # сколько лучших по общим словам окон сравнивать точно
SHIFTS = 2       # сдвиг начала окна и разброс длины (слова), OCR может слить или разбить слова

_WORD_RE = re.compile(r"[0-9a-zа-я]+")
_HYPHEN_BREAK_RE = re.compile(r"[-­]\s*\n\s*")


def normalize(text: str) -> str:
    """Нижний регистр, ё→е, без знаков препинания и переносов слов."""
    joined = _HYPHEN_BREAK_RE.sub("", text or "")
    return " ".join(_WORD_RE.findall(joined.casefold().replace("ё", "е")))


def _top_windows(q_words: list[str], p_words: list[str], size: int, limit: int) -> list[int]:
    """Начала окон страницы длиной size слов с наибольшим числом общих слов с цитатой."""
    q_counts = Counter(q_words)
    window = Counter(p_words[:size])
    scored: list[tuple[int, int]] = []
    for start in range(0, len(p_words) - size + 1):
        if start:
            window[p_words[start - 1]] -= 1
            window[p_words[start + size - 1]] += 1
        shared = sum(min(count, window[word]) for word, count in q_counts.items())
        scored.append((shared, start))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [start for _, start in scored[:limit]]


def check_quote(quote: str, page_text: str, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Вернуть {"status": matched|fuzzy|not_found, "score": 0..1}."""
    q, p = normalize(quote), normalize(page_text)
    if not q:
        return {"status": "not_found", "score": 0.0}
    if f" {q} " in f" {p} ":
        return {"status": "matched", "score": 1.0}
    if not p:
        return {"status": "not_found", "score": 0.0}

    q_words, p_words = q.split(), p.split()
    n = len(q_words)
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(q)
    best = 0.0
    seen: set[tuple[int, int]] = set()
    for base in _top_windows(q_words, p_words, min(n, len(p_words)), CANDIDATES):
        for shift in range(-SHIFTS, SHIFTS + 1):
            start = max(0, base + shift)
            for size in range(max(1, n - SHIFTS), n + SHIFTS + 1):
                if (start, size) in seen:
                    continue
                seen.add((start, size))
                matcher.set_seq1(" ".join(p_words[start:start + size]))
                if matcher.real_quick_ratio() <= best:
                    continue
                best = max(best, matcher.ratio())
        if best >= 0.999:
            break
    score = round(best, 4)
    return {"status": "fuzzy" if score >= threshold else "not_found", "score": score}
