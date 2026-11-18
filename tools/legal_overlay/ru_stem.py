"""Russian Snowball (Porter) stemmer, dependency-free.

Implements the published Snowball algorithm for Russian
(https://snowballstem.org/algorithms/russian/stemmer.html): RV/R2 regions,
perfective gerund, reflexive, adjectival, verb and noun endings, derivational
"ость", superlative "ейш" and the final "нн"/"ь" cleanup. Used only to widen
local full-text search to other word forms; it never rewrites stored text.
"""
from __future__ import annotations

import re

VOWELS = "аеиоуыэюя"

PERFECTIVE_GERUND_1 = ("вшись", "вши", "в")  # must follow а / я
PERFECTIVE_GERUND_2 = ("ившись", "ывшись", "ивши", "ывши", "ив", "ыв")
REFLEXIVE = ("ся", "сь")
ADJECTIVE = (
    "ими", "ыми", "его", "ого", "ему", "ому", "ее", "ие", "ые", "ое", "ей", "ий", "ый", "ой",
    "ем", "им", "ым", "ом", "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею",
)
PARTICIPLE_1 = ("ем", "нн", "вш", "ющ", "щ")  # must follow а / я
PARTICIPLE_2 = ("ивш", "ывш", "ующ")
VERB_1 = (  # must follow а / я
    "ете", "йте", "ешь", "нно", "ла", "на", "ли", "ем", "ло", "но", "ет", "ют", "ны", "ть", "й", "л", "н",
)
VERB_2 = (
    "ейте", "уйте", "ила", "ыла", "ена", "ите", "или", "ыли", "ило", "ыло", "ено", "ует", "уют",
    "ены", "ить", "ыть", "ишь", "ей", "уй", "ил", "ыл", "им", "ым", "ен", "ят", "ит", "ыт", "ую", "ю",
)
NOUN = (
    "иями", "ями", "ами", "ией", "иям", "ием", "иях", "ев", "ов", "ие", "ье", "еи", "ии", "ей", "ой",
    "ий", "ям", "ем", "ам", "ом", "ах", "ях", "ию", "ью", "ия", "ья", "а", "е", "и", "й", "о", "у",
    "ы", "ь", "ю", "я",
)
SUPERLATIVE = ("ейше", "ейш")
DERIVATIONAL = ("ость", "ост")

_CYRILLIC_WORD = re.compile(r"^[а-я]+$")


def _rv_r2(word: str) -> tuple[int, int]:
    """Return start indexes of RV and R2 (len(word) when the region is empty)."""
    n = len(word)
    rv = n
    for i, ch in enumerate(word):
        if ch in VOWELS:
            rv = i + 1
            break
    r1 = n
    for i in range(1, n):
        if word[i - 1] in VOWELS and word[i] not in VOWELS:
            r1 = i + 1
            break
    r2 = n
    for i in range(r1 + 1, n):
        if word[i - 1] in VOWELS and word[i] not in VOWELS:
            r2 = i + 1
            break
    return rv, r2


def _strip(word: str, rv: int, endings: tuple[str, ...], *, after_a_ya: bool = False) -> str | None:
    """Remove the longest ending lying inside RV; return None when nothing matched."""
    for ending in sorted(endings, key=len, reverse=True):
        if not word.endswith(ending):
            continue
        start = len(word) - len(ending)
        if start < rv:
            continue
        if after_a_ya:
            if start - 1 < rv or word[start - 1] not in "ая":
                continue
        return word[:start]
    return None


def _strip_any(word: str, rv: int, group1: tuple[str, ...], group2: tuple[str, ...]) -> str | None:
    """Longest match across both groups (group1 requires а/я before it)."""
    best: str | None = None
    for candidate in (_strip(word, rv, group1, after_a_ya=True), _strip(word, rv, group2)):
        if candidate is not None and (best is None or len(candidate) < len(best)):
            best = candidate
    return best


def _adjectival(word: str, rv: int) -> str | None:
    base = _strip(word, rv, ADJECTIVE)
    if base is None:
        return None
    participle = _strip_any(base, rv, PARTICIPLE_1, PARTICIPLE_2)
    return participle if participle is not None else base


def stem(word: str) -> str:
    """Stem one lowercase Russian word; non-Cyrillic input is returned unchanged."""
    word = str(word or "").casefold().replace("ё", "е")
    if not _CYRILLIC_WORD.match(word):
        return word
    # Regions are fixed on the original word; only suffixes are removed later,
    # so the indexes stay valid for every step.
    rv, r2 = _rv_r2(word)

    # Step 1
    result = _strip_any(word, rv, PERFECTIVE_GERUND_1, PERFECTIVE_GERUND_2)
    if result is None:
        reflexive = _strip(word, rv, REFLEXIVE)
        if reflexive is not None:
            word = reflexive
        for step in (_adjectival, lambda w, r: _strip_any(w, r, VERB_1, VERB_2), lambda w, r: _strip(w, r, NOUN)):
            candidate = step(word, rv)
            if candidate is not None:
                result = candidate
                break
        else:
            result = word
    word = result

    # Step 2
    if word.endswith("и") and len(word) - 1 >= rv:
        word = word[:-1]

    # Step 3: derivational ending in R2
    derivational = _strip(word, r2, DERIVATIONAL)
    if derivational is not None:
        word = derivational

    # Step 4
    if word.endswith("нн") and len(word) - 2 >= rv:
        word = word[:-1]
    else:
        superlative = _strip(word, rv, SUPERLATIVE)
        if superlative is not None:
            word = superlative
            if word.endswith("нн") and len(word) - 2 >= rv:
                word = word[:-1]
        elif word.endswith("ь") and len(word) - 1 >= rv:
            word = word[:-1]
    return word


def prefix_stem(token: str) -> str | None:
    """Return the Snowball stem to search as a prefix, or None to keep the word exact.

    A Russian word becomes ``"stem"*`` when its stem has 4+ letters, or 3 letters
    with a removed ending ("явные" -> "явн"). Short words without an ending
    ("акт", "для", "без") and non-Cyrillic tokens stay exact: as prefixes they
    pull in unrelated words ("актуальность"). Chosen on a measured sample
    (BL-007, 2026-10-30): exact-title retrieval unchanged, other word forms
    found 161/164 instead of 61/164.
    """
    token = str(token or "").casefold()
    if not re.fullmatch(r"[а-яё]+", token):
        return None
    root = stem(token)
    if len(root) >= 4 or (len(root) == 3 and root != token):
        return root
    return None
