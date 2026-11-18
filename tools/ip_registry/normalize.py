"""Детерминированная нормализация полей реестра товарных знаков (класс A, без LLM)."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

COUNTRIES_FILE = Path(__file__).with_name("countries.yaml")

RECORD_STATUS_LABELS = {
    "active": "действует",
    "pending": "в процессе регистрации",
    "withdrawn": "заявка отозвана",
    "refused": "отказ",
    "fee_unpaid": "решение о регистрации, пошлина не оплачена",
    "inactive": "не действует",
    "other": "иное",
}
TERRITORY_STATUS_LABELS = {
    "protected": "охраняется",
    "pending": "в процессе",
    "refused": "отказ",
    "lapsed": "не продлено / не действует",
    "withdrawn": "отозвано",
    "not_registered": "не зарегистрирован",
    "unknown": "не ясно",
}
RECORD_TO_TERRITORY = {
    "active": "protected",
    "pending": "pending",
    "withdrawn": "withdrawn",
    "refused": "refused",
    "fee_unpaid": "not_registered",
    "inactive": "lapsed",
    "other": "unknown",
}

_WS = re.compile(r"\s+")
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_LONG_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]{4,}")
_LOOKALIKE = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")
_STATUS_RULES = (
    ("не действует", "inactive"),
    ("пошлину не оплач", "fee_unpaid"),
    ("отозван", "withdrawn"),
    ("отказ", "refused"),
    ("в процессе", "pending"),
    ("действует", "active"),
)


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = _WS.sub(" ", str(value).replace("\xa0", " ")).strip()
    return text or None


def parse_date(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = clean(value)
    if not text:
        return None
    match = _DATE.search(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


_CLASS_NUMBER = re.compile(r"(?<!\d)\d{1,2}(?!\d)")


def _long_text_classes(text: str) -> list[str]:
    # Номера в начале строки плюс номера до первого длинного слова каждой строки
    # («03, 05, 35 (Cosmetics)»). Если ничего не найдено («Class 5, 35») — все номера текста.
    found = re.findall(r"(?m)^\s*(\d{1,2})\b", text)
    for line in text.splitlines():
        long_word = _LONG_WORD.search(line)
        prefix = line[: long_word.start()] if long_word else line
        found += _CLASS_NUMBER.findall(prefix)
    if not found:
        found = _CLASS_NUMBER.findall(text)
    return found


def parse_classes(value: Any) -> list[int]:
    if value is None:
        return []
    # Excel хранит «3.10» как float 3.1: восстанавливаем две цифры после точки.
    text = f"{value:.2f}" if isinstance(value, float) else str(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"класс\w*", " ", text, flags=re.IGNORECASE)
    if _LONG_WORD.search(text):
        found = _long_text_classes(text)
    else:
        found = re.findall(r"\d{1,2}", text)
    return sorted({int(item) for item in found if 1 <= int(item) <= 45})


def normalize_status(value: Any) -> tuple[str, bool]:
    text = (clean(value) or "").casefold()
    if not text:
        return "other", True
    for needle, code in _STATUS_RULES:
        if needle in text:
            return code, True
    return "other", False


def number_key(value: Any) -> str:
    text = (clean(value) or "").upper().translate(_LOOKALIKE)
    return re.sub(r"[^0-9A-Z]", "", text)


def parse_number(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = clean(value)
    if not text:
        return None, None
    if not re.search(r"\d", text):
        return None, text
    return text, None


def product_key(value: Any) -> str:
    return (clean(value) or "").casefold().replace("ё", "е")


def _fold(text: str) -> str:
    return text.casefold().replace("ё", "е")


@dataclass(frozen=True)
class Country:
    code: str
    name: str


class CountryBook:
    def __init__(self, data: dict[str, dict]) -> None:
        for raw_code in data:
            if not isinstance(raw_code, str):
                raise ValueError(f"countries.yaml: ключ {raw_code!r} должен быть строкой в кавычках")
        codes = {str(raw_code): item for raw_code, item in data.items()}
        self.by_code = {code: Country(code, item["name"]) for code, item in codes.items()}
        names = []
        for code, item in codes.items():
            for name in (item["name"], *(item.get("aliases") or [])):
                names.append((_fold(name), code))
        self._names = sorted(names, key=lambda pair: -len(pair[0]))

    @classmethod
    def load(cls, path: Path = COUNTRIES_FILE) -> "CountryBook":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(data["countries"])

    def names(self) -> list[tuple[str, str]]:
        """Пары (название или синоним в нижнем регистре, ISO-код), длинные сначала."""
        return list(self._names)

    def by_iso(self, code: str) -> Country | None:
        return self.by_code.get(code.upper())

    def match_prefix(self, text: str) -> tuple[Country, str] | None:
        stripped = text.strip()
        low = _fold(stripped)
        for name, code in self._names:
            if low.startswith(name) and (len(low) == len(name) or not low[len(name)].isalpha()):
                return self.by_code[code], stripped[len(name):]
        return None

    def find_in(self, text: str | None) -> Country | None:
        low = _fold(text or "")
        for name, code in self._names:
            if re.search(rf"(?<![а-яa-z]){re.escape(name)}(?![а-яa-z])", low):
                return self.by_code[code]
        return None


_HEADINGS = (
    (re.compile(r"Охраняется\s+по\s+([^:\n]{0,160}?)\s*:", re.IGNORECASE), "protected"),
    (re.compile(r"В\s+процессе\s+регистрации\s*:", re.IGNORECASE), "pending"),
    (re.compile(r"Подтверждение\s+полного\s+предварительного\s+отказа[^:\n;]{0,80}:", re.IGNORECASE), "refused"),
    (re.compile(r"Полный\s+предварительный\s+отказ[^:\n;]{0,80}:", re.IGNORECASE), "refused"),
    (re.compile(r"Окончательный\s+отказ[^:\n;]{0,80}:", re.IGNORECASE), "refused"),
    (re.compile(r"Не\s+продлено[^:\n;]{0,80}:", re.IGNORECASE), "lapsed"),
)
_BASIS = re.compile(r"[Сс]т\.?\s*(\d+(?:\.\d+)?[a-z]*(?:\s*\(\d+\))?)")
_ENTRY = re.compile(r"^([A-Z]{2})\s*[-–—]\s*(.*)$", re.DOTALL)
_CHAIN = re.compile(r"^[A-Z]{2}(?:\s*[-–—]\s*[A-Z]{2})+$")
_NEXT_ENTRY = re.compile(r"\s+(?=[A-Z]{2}\s*[-–—]\s*[А-ЯЁ])")
_STRONG_REFUSAL = re.compile(r"окончательный\s+отказ|недействительн|неохраноспособн", re.IGNORECASE)
_WEAK_STATUS = (("отказ", "refused"), ("в процессе", "pending"))


def _split_entries(segment: str) -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    for char in segment:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0 and char in ";\n":
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    parts.append("".join(buffer))
    result = []
    for part in parts:
        for piece in _NEXT_ENTRY.split(part):
            piece = piece.strip(" \t\r.,")
            if piece:
                result.append(piece)
    return result


def _clean_note(text: str) -> str | None:
    note = (clean(text) or "").strip(" .,;:–—-")
    if note.startswith("(") and note.endswith(")") and note.count("(") == 1:
        note = note[1:-1].strip()
    return note or None


def _parse_piece(piece: str, book: CountryBook, warnings: list[str]) -> list[tuple[str, str, str | None]]:
    if _CHAIN.match(piece):
        result = []
        for code in re.findall(r"[A-Z]{2}", piece):
            country = book.by_iso(code)
            if country is None:
                warnings.append(f"неизвестный код страны «{code}»")
            result.append((code, country.name if country else code, None))
        return result
    match = _ENTRY.match(piece)
    if match:
        code, rest = match.group(1), match.group(2)
        hit = book.match_prefix(rest)
        country = book.by_iso(code) or (hit[0] if hit else None)
        if country is None:
            warnings.append(f"неизвестный код страны «{code}»")
            return [(code, clean(rest) or code, None)]
        remainder = hit[1] if hit else rest
        return [(country.code, country.name, _clean_note(remainder))]
    hit = book.match_prefix(piece)
    if hit:
        return [(hit[0].code, hit[0].name, _clean_note(hit[1]))]
    return []


def parse_territories(text: Any, book: CountryBook) -> tuple[list[dict], list[str], list[str]]:
    raw = str(text or "").replace("\xa0", " ")
    if not raw.strip():
        return [], [], []
    found = []
    for pattern, status in _HEADINGS:
        for match in pattern.finditer(raw):
            basis = None
            if status == "protected":
                hit = _BASIS.search(match.group(1))
                basis = "ст. " + _WS.sub(" ", hit.group(1)) if hit else clean(match.group(1))
            found.append((match.start(), match.end(), status, basis))
    found.sort()
    sections: list[tuple[str, str | None, str | None]] = []
    cursor, current = 0, (None, None)
    for start, end, status, basis in found:
        if start < cursor:
            continue
        sections.append((raw[cursor:start], *current))
        cursor, current = end, (status, basis)
    sections.append((raw[cursor:], *current))

    territories: list[dict] = []
    warnings: list[str] = []
    notes: list[str] = []
    for segment, status, basis in sections:
        for piece in _split_entries(segment):
            entries = _parse_piece(piece, book, warnings)
            if not entries:
                notes.append(piece)
                continue
            for code, name, note in entries:
                entry_status = status
                if _STRONG_REFUSAL.search(piece):
                    entry_status = "refused"
                elif entry_status is None:
                    for needle, value in _WEAK_STATUS:
                        if needle in piece.casefold():
                            entry_status = value
                            break
                territories.append(
                    {
                        "code": code,
                        "name": name,
                        "status": entry_status,
                        "basis": basis if entry_status == status else None,
                        "note": note,
                    }
                )
    if not territories:
        warnings.append(f"страны не распознаны: «{(clean(raw) or '')[:80]}»")
    if notes:
        warnings.append(f"фрагменты территории не разобраны: «{'; '.join(notes)[:120]}»")
    return territories, warnings, notes


def national_territories(
    kind_raw: Any, territory_raw: Any, book: CountryBook
) -> tuple[list[dict], list[str], list[str]]:
    territories, warnings, notes = parse_territories(territory_raw, book)
    kind = str(kind_raw or "").replace("\xa0", " ")
    country = None
    for group in re.findall(r"\(([^)]*)\)", kind):
        country = book.find_in(group)
        if country:
            break
    if country is None:
        country = book.find_in(re.sub(r"\([^)]*\)", " ", kind))
    if country is None:
        return territories, warnings, notes
    warnings = [item for item in warnings if not item.startswith("страны не распознаны")]
    same = [item for item in territories if item["code"] == country.code]
    others = sorted({item["code"] for item in territories if item["code"] != country.code})
    if others:
        warnings.append(
            f"в «Государстве действия» другие страны ({', '.join(others)}), чем в виде регистрации ({country.code})"
        )
    if not same:
        same = [{"code": country.code, "name": country.name, "status": None, "basis": None, "note": None}]
    return same, warnings, notes
