"""Ключ договора: нормализация номера, имя папки досье, временный ключ."""
from __future__ import annotations

import re

# Кириллица, похожая на латиницу, сводится к латинице: «НПО» и «HПO» дают один ключ.
# Таблица только для заглавных: сначала номер переводится в верхний регистр.
_HOMO = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')


def number_key(s: str) -> str:
    s = (s or "").upper().translate(_HOMO)
    s = s.replace("№", "")
    s = re.sub(r"[\s\-‐‑‒–—―−_./]", "", s)
    return s


def folder_name(key: str, counterparty: str) -> str:
    name = _FORBIDDEN.sub("", f"{key} {counterparty}")
    return re.sub(r"\s+", " ", name).strip(" .")


def temporary_key(counterparty: str, date: str) -> str:
    return f"{counterparty.strip()} {date}"
