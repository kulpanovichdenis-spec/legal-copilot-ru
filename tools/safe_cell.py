"""Значение из документа → безопасная ячейка .xlsx / .csv.

Строка, которую Excel прочитает как формулу (`=`, `+`, `-`, `@`, табуляция,
перевод строки в начале), получает префикс `'` и остаётся текстом. Числа, даты,
None и прочие нестроковые значения не меняются. Правило —
`references/untrusted-input.md`, «Машинная подстраховка».

Usage:
    from tools.safe_cell import safe_cell, safe_row
    python tools/safe_cell.py selftest
"""
from __future__ import annotations

import sys

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_cell(value):
    """Строку, похожую на формулу, превратить в текст; остальное вернуть как есть."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_row(values):
    """Список или кортеж значений строки — каждое через safe_cell."""
    return [safe_cell(v) for v in values]


def safe_mapping(row: dict) -> dict:
    """Строка csv.DictWriter — значения через safe_cell, ключи не трогаются."""
    return {k: safe_cell(v) for k, v in row.items()}


def selftest() -> int:
    cases = [
        ("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"),
        ("+7 999", "'+7 999"),
        ("-1", "'-1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\t=1", "'\t=1"),
        ("п. 5.1", "п. 5.1"),
        ("", ""),
        (42, 42),
        (None, None),
        (-5, -5),
    ]
    for raw, expected in cases:
        got = safe_cell(raw)
        assert got == expected, f"{raw!r}: {got!r} != {expected!r}"
    assert safe_row(["=1", "a"]) == ["'=1", "a"]
    assert safe_mapping({"k": "=1"}) == {"k": "'=1"}
    print("selftest OK")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if sys.argv[1:] == ["selftest"] else 0)
