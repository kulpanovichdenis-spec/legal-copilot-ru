"""Раскладка папки проекта анонимайзера: workflow/_anonymizer/<проект>/.

Общий источник имён для project.py, project_guard.py и watcher.py.
Модуль без тяжёлых импортов: страховка загружает его на каждый вызов
инструмента агента.
"""
from __future__ import annotations

ANALYTIC = "analytic"
DRAFTS = "черновики"
READY = "готово"
SERVICE = "_служебное"
ORIGINALS = "оригиналы"
NOT_PROCESSED = "не-обработано"
STATE_FILE = "состояние.b64"
ANON_SUFFIX = ".anon.md"
# Рабочие файлы агента в корне проекта: ведутся с метками, watcher их не трогает.
AGENT_FILES = frozenset({"case-context.md", "deadlines.yaml", "matter-timeline.yaml"})
# Форматы, которые конвейер умеет обезличивать (разовый режим и проекты).
SUPPORTED = {".docx", ".doc", ".rtf", ".pdf", ".txt", ".md", ".html", ".htm", ".xlsx",
             ".pptx", ".csv",
             ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}  # изображения → OCR


def is_agent_file(name: str) -> bool:
    """Файл корня проекта, который агенту разрешено читать и писать."""
    low = name.lower()
    return low.endswith(ANON_SUFFIX) or low in AGENT_FILES


def is_project_name(name: str) -> bool:
    """Подпапка workflow/_anonymizer/ — проект, если не служебная (_inbox, _ready, скрытые)."""
    return bool(name) and not name.startswith(("_", "."))
