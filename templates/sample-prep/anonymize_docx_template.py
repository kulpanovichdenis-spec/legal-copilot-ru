# -*- coding: utf-8 -*-
"""
Шаблон скрипта обезличивания .docx файлов.

Использование:
1. Скопировать в %TEMP% или рядом с обрабатываемой папкой.
2. Заполнить BASE (путь к папке для обработки).
3. Заполнить REPLACEMENTS (словарь замен).
4. При необходимости — заполнить SKIP_AMOUNTS (файлы, где суммы не трогаются).
5. Запустить: PYTHONIOENCODING=utf-8 python anonymize_docx.py

Методика — см. references/anonymization-procedure.md.
Стартовый словарь известных данных проекта — см. logs/anonymization-inventory.md.
"""

import os
import re
import sys
import glob
from docx import Document

sys.stdout.reconfigure(encoding='utf-8')

# === НАСТРОЙКИ ===

# Путь к обрабатываемой папке (НЕ должен включать backup)
BASE = r"<ЗАПОЛНИТЬ_ПУТЬ>"

# Файлы, в которых суммы НЕ заменяются (например, отзывы — методика основана на расчётах)
SKIP_AMOUNTS = {
    # "Отзыв.docx",
    # "отзыв_9л.docx",
}

# === СЛОВАРЬ ЗАМЕН ===
# Формат: (старая_строка, новая_строка)
# ВАЖНО: длиннейшие сначала (сортируется автоматически перед применением)
# ВАЖНО: учитывать все формы — падежи, инициалы с пробелом и без, заглавные / строчные, кавычки разных видов

REPLACEMENTS = [
    # === ЮРИДИЧЕСКИЕ ЛИЦА ===
    # ("ООО «Наименование»", "[НАИМЕНОВАНИЕ_ОРГАНИЗАЦИИ]"),
    # ("Полная форма с заглавными", "[НАИМЕНОВАНИЕ_ОРГАНИЗАЦИИ]"),
    # ("Английский эквивалент", "[ORGANIZATION_NAME]"),

    # === ФИО (все формы) ===
    # ("Фамилия Имя Отчество", "[ФИО_СОТРУДНИКА]"),
    # ("Фамилия И.О.", "[ФИО_СОТРУДНИКА]"),       # инициалы без пробела
    # ("Фамилия И. О.", "[ФИО_СОТРУДНИКА]"),      # инициалы с пробелом
    # ("Фамилии И.О.", "[ФИО_СОТРУДНИКА]"),       # родительный падеж
    # ("Фамилию И.О.", "[ФИО_СОТРУДНИКА]"),       # винительный падеж
    # ("И.О. Фамилия", "[ФИО_СОТРУДНИКА]"),       # инициалы перед, без пробела
    # ("И. О. Фамилия", "[ФИО_СОТРУДНИКА]"),      # инициалы перед, с пробелом

    # === АДРЕСА ===
    # ("Полный адрес с индексом", "[АДРЕС_ОРГАНИЗАЦИИ]"),

    # === РЕКВИЗИТЫ ===
    # ("1234567890123", "[ОГРН]"),
    # ("1234567890", "[ИНН]"),
    # ("123456789", "[КПП]"),

    # === БАНКИ ===
    # ("Наименование банка", "[НАИМЕНОВАНИЕ_БАНКА]"),
    # ("Расчётный счёт 20 цифр", "[РАСЧЁТНЫЙ_СЧЁТ]"),
    # ("SWIFT-код", "[SWIFT]"),
    # ("IBAN", "[IBAN]"),

    # === EMAIL ===
    # ("name@corporate.domain", "[EMAIL]"),

    # === ТЕЛЕФОНЫ ===
    # ("+7 (XXX) XXX-XX-XX доб. NNN", "[ТЕЛЕФОН]"),
    # ("+7 (XXX) XXX-XX-XX", "[ТЕЛЕФОН]"),

    # === НОМЕРА ДОКУМЕНТОВ ===
    # ("Номер договора", "[НОМЕР_ДОГОВОРА]"),
    # ("Номер доверенности", "[НОМЕР_ДОВЕРЕННОСТИ]"),
    # ("Номер дела", "[НОМЕР_ДЕЛА]"),
    # ("Номер постановления", "[НОМЕР_ПОСТАНОВЛЕНИЯ]"),
    # ("UUID обращения", "[UUID_ОБРАЩЕНИЯ]"),
]

# === REGEX ПАТТЕРНЫ (применяются после REPLACEMENTS) ===
REGEX_PATTERNS = [
    # Общие email (все, не попавшие в REPLACEMENTS)
    (r'\b[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b', '[EMAIL]'),
    # ОГРН после слова ОГРН
    (r'(?<![\d])ОГРН\s*\d{13}(?![\d])', 'ОГРН [ОГРН]'),
    # ИНН после слова ИНН (10 или 12 цифр)
    (r'(?<![\d])ИНН\s*\d{10}(?![\d])', 'ИНН [ИНН]'),
    (r'(?<![\d])ИНН\s*\d{12}(?![\d])', 'ИНН [ИНН]'),
]

# === REGEX ДЛЯ СУММ (применяется, если файл НЕ в SKIP_AMOUNTS) ===
AMOUNT_PATTERN = re.compile(
    r'\b\d{1,3}(?:[\s ]\d{3})*(?:[,.]\d{2})?\s*(руб\.|рублей|RUB|USD|долл\.|долларов|EUR|евро|CNY|юаней)',
)
AMOUNT_REPLACEMENT = r'[СУММА] \1'


# === ОСНОВНАЯ ЛОГИКА ===

def replace_in_paragraph(paragraph, replacements_sorted, skip_amounts):
    """Заменяет текст в параграфе, сохраняя форматирование первого run."""
    if not paragraph.runs:
        return False

    full_text = paragraph.text
    new_text = full_text

    # 1. Точные замены из словаря (длиннейшие сначала)
    for old, new in replacements_sorted:
        if old in new_text:
            new_text = new_text.replace(old, new)

    # 2. Regex patterns (email / ОГРН / ИНН)
    for pattern, replacement in REGEX_PATTERNS:
        new_text = re.sub(pattern, replacement, new_text)

    # 3. Суммы (если файл не в исключениях)
    if not skip_amounts:
        new_text = AMOUNT_PATTERN.sub(AMOUNT_REPLACEMENT, new_text)

    if new_text != full_text:
        # Записываем результат в первый run, остальные очищаем
        first_run = paragraph.runs[0]
        for r in paragraph.runs[1:]:
            r.text = ""
        first_run.text = new_text
        return True
    return False


def anonymize_docx(path, replacements_sorted, skip_amounts):
    """Обезличивает один .docx файл."""
    try:
        doc = Document(path)
    except Exception as e:
        return f"FAIL open: {e}"

    changes = 0

    # Тело документа
    for p in doc.paragraphs:
        if replace_in_paragraph(p, replacements_sorted, skip_amounts):
            changes += 1

    # Таблицы
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if replace_in_paragraph(p, replacements_sorted, skip_amounts):
                        changes += 1

    # Headers / Footers (всех секций)
    for section in doc.sections:
        for hdr in [section.header, section.footer,
                    section.first_page_header, section.first_page_footer,
                    section.even_page_header, section.even_page_footer]:
            try:
                for p in hdr.paragraphs:
                    if replace_in_paragraph(p, replacements_sorted, skip_amounts):
                        changes += 1
                for tbl in hdr.tables:
                    for row in tbl.rows:
                        for cell in row.cells:
                            for p in cell.paragraphs:
                                if replace_in_paragraph(p, replacements_sorted, skip_amounts):
                                    changes += 1
            except Exception:
                pass

    try:
        doc.save(path)
    except Exception as e:
        return f"FAIL save: {e}"
    return f"OK changes={changes}"


def main():
    if BASE == r"<ЗАПОЛНИТЬ_ПУТЬ>" or not os.path.isdir(BASE):
        print(f"ERROR: BASE не настроен или не существует: {BASE}", file=sys.stderr)
        sys.exit(1)

    # Сортировка словаря по длине ключа (длиннейшие сначала)
    replacements_sorted = sorted(REPLACEMENTS, key=lambda x: -len(x[0]))

    pattern = os.path.join(BASE, "**", "*.docx")
    files = glob.glob(pattern, recursive=True)
    # Защита: пропустить файлы в backup-папках
    files = [f for f in files if 'backup' not in f.lower()]
    print(f"Найдено {len(files)} .docx файлов в {BASE}")

    for path in files:
        fname = os.path.basename(path)
        skip = fname in SKIP_AMOUNTS
        result = anonymize_docx(path, replacements_sorted, skip)
        marker = " [SKIP_AMOUNTS]" if skip else ""
        rel = os.path.relpath(path, BASE)
        print(f"  {rel}: {result}{marker}")


if __name__ == "__main__":
    main()
