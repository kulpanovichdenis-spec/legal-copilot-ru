# -*- coding: utf-8 -*-
"""
Шаблон скрипта обезличивания .md карточек.

Использование:
1. Скопировать в %TEMP% или рядом с обрабатываемой папкой.
2. Заполнить BASE (путь к папке для обработки).
3. Заполнить REPLACEMENTS (тот же словарь, что в anonymize_docx_template.py).
4. При необходимости — добавить замены для перекрёстных ссылок на старые имена файлов
   (после переименований этапа 4 процедуры).
5. Запустить: PYTHONIOENCODING=utf-8 python anonymize_md.py

Методика — см. references/anonymization-procedure.md.
"""

import os
import re
import sys
import glob

sys.stdout.reconfigure(encoding='utf-8')

# === НАСТРОЙКИ ===

BASE = r"<ЗАПОЛНИТЬ_ПУТЬ>"

# === СЛОВАРЬ ЗАМЕН ===
# Тот же формат, что в anonymize_docx_template.py.
# Также включает перекрёстные ссылки на старые имена файлов после переименований.

REPLACEMENTS = [
    # === ЮРИДИЧЕСКИЕ ЛИЦА / ФИО / АДРЕСА / РЕКВИЗИТЫ / EMAIL / ТЕЛЕФОНЫ / НОМЕРА ДОКУМЕНТОВ ===
    # (см. anonymize_docx_template.py — те же категории)

    # === ПЕРЕКРЁСТНЫЕ ССЫЛКИ НА СТАРЫЕ ИМЕНА ФАЙЛОВ ===
    # Если на этапе 4 были переименования — здесь обновляем ссылки в карточках.
    # ("Старое_имя_файла.docx", "Новое_имя_файла.docx"),
    # ("Старое_имя_файла-card.md", "Новое_имя_файла-card.md"),
    # ("Старое_имя_файла", "Новое_имя_файла"),  # без расширения — на случай упоминания без .docx
]


def anonymize_file(path, replacements_sorted):
    """Обезличивает один .md файл."""
    with open(path, encoding='utf-8') as f:
        original = f.read()
    text = original

    # 1. Точные замены из словаря (длиннейшие сначала)
    for old, new in replacements_sorted:
        text = text.replace(old, new)

    # 2. Общие email (если не попали в словарь)
    text = re.sub(r'\b[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b', '[EMAIL]', text)

    if text != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return True
    return False


def main():
    if BASE == r"<ЗАПОЛНИТЬ_ПУТЬ>" or not os.path.isdir(BASE):
        print(f"ERROR: BASE не настроен или не существует: {BASE}", file=sys.stderr)
        sys.exit(1)

    replacements_sorted = sorted(REPLACEMENTS, key=lambda x: -len(x[0]))

    pattern = os.path.join(BASE, "**", "*.md")
    files = glob.glob(pattern, recursive=True)
    files = [f for f in files if 'backup' not in f.lower()]
    print(f"Найдено {len(files)} .md файлов в {BASE}")

    changed = 0
    for path in files:
        if anonymize_file(path, replacements_sorted):
            changed += 1
            rel = os.path.relpath(path, BASE)
            print(f"  CHANGED: {rel}")

    print(f"\nИзменено: {changed}/{len(files)}")


if __name__ == "__main__":
    main()
