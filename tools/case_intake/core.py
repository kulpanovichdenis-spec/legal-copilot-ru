#!/usr/bin/env python3
"""Детерминированное ядро авто-разбора входящих документов (класс A).

Здесь — только то, что надёжно решается кодом без LLM: разбор номеров дел,
маршрутизация claims/gov_response, поиск существующей папки дела, safety-правила
именования и фильтрации файлов.

Что сюда НЕ входит по правилам `references/execution-profiles.md`:
  - классификация типа документа и извлечение сторон  → класс B (воркер intake-classifier);
  - любые правовые выводы, маркеры неполноты, решения  → класс C (основной агент, юрист).

"""
from __future__ import annotations

import re
from pathlib import Path

# --- Файловые safety-правила ---------------------------------------------------

SUPPORTED = {".docx", ".doc", ".pdf", ".txt", ".md", ".rtf", ".odt",
             ".xlsx", ".xls",            # расчёты, реестры, приложения к претензиям
             ".eml", ".msg",             # входящая переписка из почты
             ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
INCOMPLETE_SUFFIXES = (".tmp", ".crdownload", ".part", ".download")
PIPELINE_SUFFIXES = (".anon.md", ".mapping.json")

# Что делать с непринятым файлом. Требование юриста: **молча не исчезает ничего**,
# кроме собственных артефактов конвейера.
SKIP_ACTIONS = {
    "word_lock": "notify",        # сообщить юристу: документ, похоже, открыт в Word
    "incomplete": "retry",        # дозагрузится — возьмём на следующем проходе
    "pipeline_output": "ignore",  # наш же результат, единственный тихий случай
    "hidden": "ignore",           # .DS_Store, Thumbs.db и подобное
    "unsupported": "unsorted",    # формат не разбираем → в unsorted с пометкой
}


def skip_reason(path: Path) -> str | None:
    """Причина, по которой файл не идёт в обычную обработку (None — идёт).

    Разделение важно: `word_lock` и `incomplete` — не мусор. Первый означает, что
    юрист держит документ открытым (сам lock-файл текста документа не содержит —
    это служебные ~160 байт с именем пользователя, разбирать в нём нечего);
    второй станет нормальным документом после дозагрузки.
    """
    name = path.name
    if name.startswith("~$"):
        return "word_lock"
    if any(name.endswith(sfx) for sfx in PIPELINE_SUFFIXES):
        return "pipeline_output"
    if any(name.endswith(sfx) for sfx in INCOMPLETE_SUFFIXES):
        return "incomplete"
    if name.startswith("."):
        return "hidden"
    if path.suffix.lower() not in SUPPORTED:
        return "unsupported"
    return None


def skip_action(reason: str) -> str:
    """Что watcher делает с файлом по причине пропуска: notify / retry / ignore / unsorted."""
    return SKIP_ACTIONS.get(reason, "unsorted")


def is_processable(path: Path) -> bool:
    """Берём ли файл в обычную обработку (короткая форма поверх `skip_reason`)."""
    return skip_reason(path) is None


_UNSAFE_NAME_CHARS = '/\\:*?"<>|'


def safe_folder_name(value: str) -> str:
    """Имя папки дела из номера дела или наименования контрагента.

    Номер дела содержит слэш (`А40-12345/2025`) — в имени файла/папки он недопустим
    и молча превратился бы во вложенный путь. Заменяем на дефис, схлопываем пробелы,
    убираем хвостовые точки (Windows их не хранит).
    """
    out = "".join("-" if ch in _UNSAFE_NAME_CHARS else ch for ch in (value or ""))
    out = " ".join(out.split()).strip(" .")
    return out


def unique_name(name: str, existing: set[str]) -> str:
    """Имя, не затирающее существующий файл: «Иск.docx» → «Иск (2).docx» → «Иск (3).docx».

    Правило безопасности: конвейер никогда не перезаписывает уже лежащий документ.
    """
    if name not in existing:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while True:
        candidate = f"{stem} ({n})" + (f".{ext}" if ext else "")
        if candidate not in existing:
            return candidate
        n += 1


# --- Номера дел ----------------------------------------------------------------

# Арбитраж: буква (кириллическая А или латинская A) + код региона + номер + / + год.
_ARB = re.compile(r"(?<![\w-])[АA]\s?(\d{1,2})\s?-\s?(\d{1,7})\s?/\s?(\d{4})(?![\w/])")
# СОЮ: тип производства (1-2 цифры) + номер + / + год. Требуем префикс «дело/№»,
# иначе ловятся дроби и диапазоны из обычного текста.
_SOU = re.compile(r"(?:дел[оа]|№)\s*(\d{1,2})\s?-\s?(\d{1,7})\s?/\s?(\d{4})(?![\w/])",
                  re.IGNORECASE)


def extract_case_numbers(text: str) -> list[str]:
    """Номера дел из текста, в порядке появления, без дублей.

    Ложные срабатывания (ИНН, ОГРН, суммы, даты вида 12/2025) отсекаются формой шаблона:
    номер дела всегда содержит дефис между кодом и порядковым номером и год после слэша.
    """
    if not text:
        return []
    found: list[str] = []

    def add(value: str) -> None:
        if value not in found:
            found.append(value)

    for m in _ARB.finditer(text):
        # латинская A нормализуется в кириллическую — номера АС пишутся кириллицей
        add(f"А{m.group(1)}-{m.group(2)}/{m.group(3)}")
    for m in _SOU.finditer(text):
        add(f"{m.group(1)}-{m.group(2)}/{m.group(3)}")
    return found


# --- Нормализация даты ---------------------------------------------------------

_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_WORD_DATE = re.compile(r"\b(\d{1,2})\s+([а-яё]{3,})\s+(\d{4})", re.IGNORECASE)


def parse_ru_date(value: str | None) -> str | None:
    """Дата в ISO (`YYYY-MM-DD`) из типовых русских форматов, иначе None.

    Класс-B классификатор по инструкции **не нормализует** реквизиты и отдаёт дату
    как в тексте — приведение к схеме делает код. Что не разобралось, остаётся None:
    событие получит `date_status = needs_check`, а не выдуманную дату.
    """
    if not value:
        return None
    s = str(value).strip()

    def build(y: int, m: int, d: int) -> str | None:
        try:
            import datetime as _dt

            return _dt.date(y, m, d).isoformat()
        except ValueError:
            return None  # напр. 31.02 — несуществующая дата

    m = _ISO_DATE.search(s)
    if m:
        return build(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _NUMERIC_DATE.search(s)
    if m:
        return build(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = _WORD_DATE.search(s)
    if m:
        stem = m.group(2).lower()[:3]
        month = _MONTHS.get(stem)
        if month:
            return build(int(m.group(3)), month, int(m.group(1)))
    return None


# --- Категория документа (claims / gov_response) -------------------------------

CLAIMS = "claims"
GOV_RESPONSE = "gov_response"

# Канал приёма один (`workflow/_claims/`) — решение юриста 2026-09-08: механика
# одинаковая, делить папки незачем. Категория ниже определяет НЕ папку, а:
#   1) какой skill предложить юристу;
#   2) что записать в `task_types` карточки дела (`case-context.md`).

_LETTER_KINDS = {"претензия", "письмо", "уведомление", "требование"}


def classify_matter_type(doc_kind: str | None, authority_side: bool | None) -> str | None:
    """Категория работы по документу.

    Граница — **по адресату, а не по форуму**: госорган на другой стороне →
    `gov_response` всегда, включая обжалование предписания в суде; спор между
    хозяйствующими субъектами → `claims`.

    None, если тип документа или сторона не определены: тогда документ уходит
    в `unsorted/` для решения юриста (при неопределённости не угадываем).
    """
    if doc_kind is None or authority_side is None:
        return None
    return GOV_RESPONSE if authority_side else CLAIMS


def suggested_skill(matter_type: str | None, doc_kind: str | None) -> str | None:
    """Какой skill предложить юристу. Это подсказка одной строкой, не автозапуск."""
    if matter_type is None:
        return None
    if matter_type == GOV_RESPONSE:
        return "gov-response"
    if doc_kind and doc_kind.strip().lower() in _LETTER_KINDS:
        return "counterparty-letter"
    return "procedural-document-drafter"


# --- Поиск существующей папки дела ---------------------------------------------

def _norm(s: str) -> str:
    """Нормализация наименования для сопоставления: регистр, кавычки, лишние пробелы."""
    s = (s or "").lower()
    for ch in "«»\"'“”„":
        s = s.replace(ch, " ")
    s = s.replace("ё", "е")
    return " ".join(s.split())


def find_case_folder(folders: list[dict], case_numbers: list[str],
                     parties: list[str]) -> str | None:
    """Подобрать существующую папку дела.

    `folders` — уже прочитанные карточки дел: {"folder", "case_number", "entities"}
    (источник — frontmatter `workflow/<дело>/case-context.md`, читается вызывающим кодом).

    Порядок: точное совпадение по номеру дела → совпадение по контрагенту.
    Неоднозначность (несколько папок по одному контрагенту) даёт None: выбор между
    делами — решение юриста, не догадка конвейера.
    """
    for num in case_numbers:
        for f in folders:
            if f.get("case_number") and f["case_number"] == num:
                return f["folder"]

    wanted = {_norm(p) for p in parties if p}
    matches = [f["folder"] for f in folders
               if wanted & {_norm(e) for e in (f.get("entities") or [])}]
    if len(matches) == 1:
        return matches[0]
    return None


# --- Конвенция имени папки дела (Stage A) --------------------------------------

def matter_marker(matter_type: str | None) -> str:
    """Маркер в имени папки дела: GOV для ответов госорганам, иначе CLAIM.

    CLAIM — споры и досудебные претензии (без разницы, суд или досудебка).
    GOV — только когда тип надёжно определён как gov_response.
    """
    return "GOV" if matter_type == GOV_RESPONSE else "CLAIM"


def case_folder_name(name: str, *, matter_type: str | None = None,
                     accepted_date: str | None = None) -> str:
    """Имя папки дела: «ГГГГ.ММ.ДД CLAIM <краткое наименование>».

    accepted_date — дата принятия дела судом (ISO YYYY-MM-DD); пусто/битая → сегодня.
    Дата — с точками (как в реальных папках юриста). Имя чистится safe_folder_name.
    """
    import datetime as _dt  # noqa: PLC0415

    try:
        dotted = _dt.date.fromisoformat(accepted_date).strftime("%Y.%m.%d")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        dotted = _dt.date.today().strftime("%Y.%m.%d")
    clean = safe_folder_name(name) or "[ПРОВЕРИТЬ РЕКВИЗИТЫ]"
    return f"{dotted} {matter_marker(matter_type)} {clean}"


# --- Раскладка по ролевым подпапкам (Stage A) ----------------------------------

# doc_kind → ролевая подпапка. Нет ключа → в корень папки дела. В одном деле
# процесс один, поэтому реально появится только одна из «*_приложения»-папок.
_DOC_KIND_FOLDER = {
    "иск": "Иск_приложения",
    "отзыв": "Отзыв_приложения",
    "возражения": "Возражения_приложения",
    "объяснение": "Объяснения_приложения",
    "ходатайство": "Ходатайства",
    "определение": "Судебные акты",
    "решение": "Судебные акты",
    "постановление": "Судебные акты",
}


def role_folder(doc_kind: str | None, *, expertise_name: str | None = None,
                third_party_name: str | None = None) -> str | None:
    """Ролевая подпапка дела для документа (или None — в корень папки дела).

    Приоритет, первое совпадение выигрывает:
      1) expertise_name  → «Экспертиза_<name>»
      2) third_party_name → «Третье_лицо_<name>»
      3) doc_kind по таблице _DOC_KIND_FOLDER
      4) иначе None (корень)
    Имя из класса B чистится safe_folder_name; пустое имя правило не включает —
    папку с угаданным именем не создаём (правило «не выдумывать»).
    """
    exp = safe_folder_name(expertise_name or "")
    if exp:
        return f"Экспертиза_{exp}"
    tp = safe_folder_name(third_party_name or "")
    if tp:
        return f"Третье_лицо_{tp}"
    return _DOC_KIND_FOLDER.get((doc_kind or "").strip().lower())


# --- Имя переименованного файла (Stage A) ----------------------------------------

def document_filename(doc_kind: str | None, party: str | None, *,
                      doc_date: str | None, ext: str) -> str:
    """Имя файла: «ГГГГ-ММ-ДД <Тип> <сторона>.ext» (дата — самого документа).

    Неизвестное поле опускаем (не выдумываем). doc_date — ISO (YYYY-MM-DD) или None.
    Тип и сторона — по-русски; символы, недопустимые в имени файла, чистятся
    safe_folder_name. ext — с точкой или без.
    """
    parts: list[str] = []
    if doc_date:
        parts.append(doc_date)                 # ISO, дефисы — как в примерах юриста
    kind = safe_folder_name((doc_kind or "").strip())
    if kind:
        parts.append(kind[:1].upper() + kind[1:])   # «иск» → «Иск»
    party_clean = safe_folder_name(party or "")
    if party_clean:
        parts.append(party_clean)
    stem = " ".join(parts) or "Документ"
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"{stem}{ext}"
