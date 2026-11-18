#!/usr/bin/env python3
"""Загрузчик реестра slop из references/anti-slop.md — единственного источника.

Своего списка паттернов здесь нет. Реестр — блоки ```yaml slop в пунктах
«### N. …» файла anti-slop.md. Элемент блока — либо фразовый паттерн (`regex`),
либо структурная проверка (`check` — имя функции в check.py, `params` — пороги).

Калибровка (правовые связки, цитаты, дипломатический регистр не ловятся) встроена
в сами regex и описана там же, в разделе «Калибровка».
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REGISTRY = Path(__file__).resolve().parents[2] / "references" / "anti-slop.md"
SEVERITIES = {"high", "review"}

_SECTION = re.compile(r"^###\s+(?:(\d+)\.|(Английский слой))", re.MULTILINE)
_BLOCK = re.compile(r"^```yaml slop\s*\n(.*?)^```", re.MULTILINE | re.DOTALL)


class Pattern:
    __slots__ = ("category", "severity", "regex", "message", "section")

    def __init__(self, category: str, severity: str, pattern: str, message: str, section: str = ""):
        self.category = category
        self.severity = severity
        self.regex = re.compile(pattern, re.IGNORECASE | re.UNICODE)
        self.message = message
        self.section = section


class Check:
    """Структурная проверка: функция из check.py + пороги из реестра."""
    __slots__ = ("category", "severity", "name", "params", "message", "section")

    def __init__(self, category, severity, name, params, message, section):
        self.category, self.severity, self.name = category, severity, name
        self.params, self.message, self.section = params or {}, message, section


def _label(section: str) -> str:
    return "anti-slop, англ. слой" if section == "EN" else f"anti-slop п.{section}"


def load(path: Path = REGISTRY) -> tuple[list[Pattern], list[Check], dict[str, int]]:
    """Прочитать реестр. Возвращает (паттерны, проверки, {пункт: число элементов})."""
    text = path.read_text(encoding="utf-8")
    sections = [(m.start(), m.group(1) or "EN") for m in _SECTION.finditer(text)]
    patterns: list[Pattern] = []
    checks: list[Check] = []
    coverage = {sec: 0 for _, sec in sections}
    for block in _BLOCK.finditer(text):
        owner = [sec for pos, sec in sections if pos < block.start()]
        if not owner:
            raise ValueError("блок yaml slop вне пункта реестра «### N.»")
        sec = owner[-1]
        try:
            items = yaml.safe_load(block.group(1)) or []
        except yaml.YAMLError as e:
            raise ValueError(f"anti-slop п.{sec}: битый блок yaml slop: {e}") from e
        for it in items:
            sev = it.get("severity")
            if sev not in SEVERITIES or not it.get("id") or not it.get("message"):
                raise ValueError(f"anti-slop п.{sec}: элемент без id/severity/message: {it}")
            msg = f"{it['message']} ({_label(sec)})"
            if "regex" in it:
                patterns.append(Pattern(it["id"], sev, it["regex"], msg, sec))
            elif "check" in it:
                checks.append(Check(it["id"], sev, it["check"], it.get("params"), msg, sec))
            else:
                raise ValueError(f"anti-slop п.{sec}: элемент без regex и без check: {it}")
            coverage[sec] += 1
    return patterns, checks, coverage


PATTERNS, CHECKS, COVERAGE = load()
