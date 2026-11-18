# -*- coding: utf-8 -*-
"""Проверка карточек-указателей норм (references/corporate-norm-cards/llc/*.md).

Карточка хранит тему, статью, тип нормы, риск изменения и дату сверки, но не
текст нормы (ТЗ §4.1, правило проекта «карточка — навигация, не основание»).
Статьи в карточку заносятся только после открытия текста живым маршрутом,
поэтому пустой список статей допустим, а заполненный обязан нести дату
редакции, дату сверки, тип нормы и ссылку на официальный текст.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_schema as schema  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CARDS_DIR = ROOT / "references" / "corporate-norm-cards" / "llc"

REQUIRED_KEYS = (
    "rule_id", "jurisdiction", "entity_type", "topic", "legal_state_at", "verified_at",
    "primary_source", "primary_source_url", "article_or_clause", "rule_type",
    "amendment_risk", "verification_required",
)
RULE_TYPES = ("mandatory", "default", "optional", "prohibition", "exception")
AMENDMENT_RISKS = ("low", "medium", "high", "unknown")
BOM = "\ufeff"
POLICY_MARKER = "<!-- norm-verification-policy:v1 -->"
# Эталон блока проверки нормы: единственное место, где определён его текст.
# Генератор карточек берёт блок отсюда, валидатор требует его без изменений и
# только эти строки освобождает от запрета цитат (blockquote).
POLICY_BLOCK_LINES = (
    POLICY_MARKER,
    "> **Проверка нормы.** Этот файл — указатель, а не источник права. Перед использованием нормы "
    "как правового основания вызвать `route_norm_verification(jurisdiction=\"RU\", probe=true)`, "
    "открыть полный текст только по маршруту с `usable_now: true` и проверить редакцию, статус, "
    "pinpoint и provenance. Если пригодного маршрута нет — поставить `[ПРОВЕРИТЬ НОРМУ]`.",
)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

# Запрет цитат закона: карточка только указатель. Короткие термины в кавычках допустимы.
QUOTE_LIMIT = 80
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HTML_BLOCKQUOTE_RE = re.compile(r"<\s*blockquote\b", re.IGNORECASE)
# Строка в форме заголовка статьи закона: «Статья 37. Текст…», «- Ст. 37.1. Текст…».
ARTICLE_HEADING_RE = re.compile(
    r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:\*\*)?(?:Статья|Ст\.)\s*\d+(?:\.\d+)*\.(?:\*\*)?\s+\S",
    re.IGNORECASE,
)
# Кавычки с разными открывающей и закрывающей: «…», “…”, „…“.
PAIRED_QUOTE_RES = (
    re.compile("«([^»]*)»"),
    re.compile("“([^”]*)”"),
    re.compile("„([^“”]*)[“”]"),
)


def card_slug(topic: str) -> str:
    return topic.replace("_", "-")


def parse_card(text: str) -> tuple[dict | None, str]:
    text = text.lstrip(BOM)
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    try:
        data = yaml.safe_load(match.group(1))
    except (yaml.YAMLError, ValueError, RecursionError):
        # ValueError: несуществующая дата (2026-02-31) — safe_load строит date сам; RecursionError: вложенность
        return None, match.group(2)
    return (data if isinstance(data, dict) else None), match.group(2)


def _policy_span(lines: list[str]) -> tuple[int, int] | None:
    """Строки блока проверки нормы: от маркера на отдельной строке ровно на длину эталона."""
    for start, line in enumerate(lines):
        if line.strip() == POLICY_MARKER:
            return start, start + len(POLICY_BLOCK_LINES)
    return None


def _entries(value: object) -> tuple[list[str], int]:
    """Непустые строковые записи списка и число пустых, пробельных и нестроковых записей."""
    items = value if isinstance(value, list) else []
    good = [item for item in items if isinstance(item, str) and item.strip()]
    return good, len(items) - len(good)


def _long_quote(lines: list[str]) -> tuple[int, int] | None:
    """Первая цитата в кавычках длиннее QUOTE_LIMIT: (индекс строки, длина в символах)."""
    found: list[tuple[int, int]] = []
    text = "\n".join(lines)
    for regex in PAIRED_QUOTE_RES:
        for match in regex.finditer(text):
            length = len(" ".join(match.group(1).split()))
            if length > QUOTE_LIMIT:
                found.append((text.count("\n", 0, match.start()), length))
    # Прямые кавычки одинаковы у открывающей и закрывающей: пары считаем по абзацу.
    paragraph: list[str] = []
    first = 0
    for index, line in enumerate([*lines, ""]):
        if line.strip():
            if not paragraph:
                first = index
            paragraph.append(line)
            continue
        parts = " ".join(paragraph).split('"')
        for piece in parts[1:len(parts) - 1:2]:
            length = len(" ".join(piece.split()))
            if length > QUOTE_LIMIT:
                found.append((first, length))
        paragraph = []
    return min(found) if found else None


def validate_card(path: Path, text: str) -> list[str]:
    name = path.name
    errors: list[str] = []
    meta, body = parse_card(text)
    if meta is None:
        return [f"{name}: нет валидного frontmatter"]
    for key in REQUIRED_KEYS:
        if key not in meta:
            errors.append(f"{name}: нет поля {key}")
    if errors:
        return errors
    topic = meta["topic"]
    if topic not in schema.TOPICS:
        errors.append(f"{name}: topic {topic!r} не входит в таксономию")
    else:
        if name != f"{card_slug(topic)}.md":
            errors.append(f"{name}: имя файла должно быть {card_slug(topic)}.md")
        if meta["rule_id"] != f"LLC.{topic.upper()}":
            errors.append(f"{name}: rule_id должен быть LLC.{topic.upper()}")
    if meta["jurisdiction"] != "RU":
        errors.append(f"{name}: jurisdiction должна быть RU")
    if meta["entity_type"] != "LLC":
        errors.append(f"{name}: entity_type должен быть LLC")
    if meta["verification_required"] is not True:
        errors.append(f"{name}: verification_required должно быть true")
    if meta["amendment_risk"] not in AMENDMENT_RISKS:
        errors.append(f"{name}: amendment_risk должен быть одним из {AMENDMENT_RISKS}")
    if meta["rule_type"] is not None and meta["rule_type"] not in RULE_TYPES:
        errors.append(f"{name}: rule_type должен быть пустым или одним из {RULE_TYPES}")
    for key in ("primary_source", "primary_source_url", "article_or_clause"):
        if not isinstance(meta[key], list):
            errors.append(f"{name}: {key} должен быть списком")
    if not (isinstance(meta["primary_source"], list) and meta["primary_source"]):
        errors.append(f"{name}: primary_source не должен быть пустым")

    articles, blank_articles = _entries(meta["article_or_clause"])
    urls, blank_urls = _entries(meta["primary_source_url"])
    for key, blank in (("article_or_clause", blank_articles), ("primary_source_url", blank_urls)):
        if blank:
            errors.append(f"{name}: {key} содержит пустые или нестроковые записи ({blank}): "
                          "записи должны быть непустыми строками")
    filled = bool(articles)
    if filled:
        if not schema.is_iso_date(meta["legal_state_at"]) or not schema.is_iso_date(meta["verified_at"]):
            errors.append(f"{name}: заполненная карточка требует legal_state_at и verified_at (YYYY-MM-DD)")
        if meta["rule_type"] is None:
            errors.append(f"{name}: заполненная карточка требует rule_type")
        if not urls:
            errors.append(f"{name}: заполненная карточка требует primary_source_url (официальный текст)")
    elif meta["verified_at"] is not None or meta["legal_state_at"] is not None:
        errors.append(f"{name}: даты сверки без article_or_clause: сначала занесите статьи")

    if body.count(POLICY_MARKER) != 1 or "route_norm_verification" not in body:
        errors.append(f"{name}: нужен ровно один блок проверки нормы (маркер {POLICY_MARKER} и route_norm_verification)")
    if "## Что искать в тексте нормы" not in body:
        errors.append(f"{name}: нет раздела «Что искать в тексте нормы»")
    errors.extend(_body_errors(name, text, body))
    return errors


def _body_errors(name: str, text: str, body: str) -> list[str]:
    """Тело карточки: блок проверки нормы без изменений, никаких цитат текста закона."""
    errors: list[str] = []
    lines = body.splitlines()
    shift = text.lstrip(BOM).count("\n") - body.count("\n") + 1  # индекс строки тела -> строка файла

    exempt: tuple[int, int] | None = None  # строки блока проверки нормы, освобождённые от запрета `>`
    span = _policy_span(lines)
    if span is None:
        if body.count(POLICY_MARKER) == 1:
            errors.append(f"{name}: блок проверки нормы: маркер {POLICY_MARKER} должен стоять отдельной строкой")
    else:
        if [line.rstrip() for line in lines[span[0]:span[1]]] == list(POLICY_BLOCK_LINES):
            exempt = span
        glued = span[1] < len(lines) and bool(lines[span[1]].strip())
        if exempt is None or glued:
            errors.append(
                f"{name}: блок проверки нормы изменён или дополнен (строка {span[0] + shift}): он должен "
                "совпадать с эталоном gov_cards.POLICY_BLOCK_LINES и заканчиваться пустой строкой; "
                "любой другой текст вне эталона запрещён")

    def in_exempt(index: int) -> bool:
        return exempt is not None and exempt[0] <= index < exempt[1]

    masked = ["" if in_exempt(i) else line for i, line in enumerate(lines)]
    fix = "карточка только указатель: вместо текста закона занесите статью в article_or_clause"
    for index, line in enumerate(masked):
        if line.lstrip().startswith(">"):
            errors.append(f"{name}: цитата в карточке запрещена (строка {index + shift}): {fix}")
            break
    for index, line in enumerate(masked):
        if FENCE_RE.match(line):
            errors.append(f"{name}: блок кода в карточке запрещён (строка {index + shift}): {fix}")
            break
    for index, line in enumerate(masked):
        if HTML_BLOCKQUOTE_RE.search(line):
            errors.append(f"{name}: html-цитата <blockquote> в карточке запрещена (строка {index + shift}): {fix}")
            break
    for index, line in enumerate(masked):
        if ARTICLE_HEADING_RE.match(line):
            errors.append(f"{name}: похоже на цитату текста закона (строка {index + shift}, заголовок статьи "
                          f"с текстом): {fix}")
            break
    quote = _long_quote(masked)
    if quote is not None:
        errors.append(f"{name}: похоже на цитату текста закона (строка {quote[0] + shift}, в кавычках "
                      f"{quote[1]} симв. при пределе {QUOTE_LIMIT}): {fix}; короткие термины в кавычках допустимы")
    return errors


def validate_cards(cards_dir: Path = CARDS_DIR) -> list[str]:
    errors: list[str] = []
    if not cards_dir.is_dir():
        return [f"каталог карточек не найден: {cards_dir}"]
    files = sorted(p for p in cards_dir.glob("*.md") if p.name.lower() != "readme.md")
    expected = {f"{card_slug(t)}.md": t for t in schema.TOPICS}
    present = {p.name for p in files}
    for missing in sorted(set(expected) - present):
        errors.append(f"нет карточки для темы {expected[missing]}: {missing}")
    for extra in sorted(present - set(expected)):
        errors.append(f"{extra}: карточка не соответствует ни одной теме таксономии")
    for path in files:
        if not path.is_file():
            errors.append(f"{path.name}: не файл (каталог или иной объект с расширением .md)")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            errors.append(f"{path.name}: файл не читается как UTF-8: сохраните карточку в кодировке UTF-8")
            continue
        except OSError as exc:
            errors.append(f"{path.name}: файл не читается ({exc.strerror or type(exc).__name__})")
            continue
        errors.extend(validate_card(path, text))
    return errors
