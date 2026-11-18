#!/usr/bin/env python3
"""Локальный OCR для pre-LLM конвейера (сканы PDF и изображения → текст).

Всё офлайн: движок Tesseract (нативный) + pytesseract + pypdfium2 (рендер
страниц PDF без poppler/ghostscript). Ничего не уходит в облако — это
обязательное условие обезличивания до LLM.

Путь к tesseract.exe: переменная окружения PRE_ANON_TESSERACT_CMD, иначе
стандартный путь установки UB-Mannheim. Язык: PRE_ANON_OCR_LANG (по умолчанию
rus+eng).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DEFAULT_LANG = "rus+eng"
RENDER_SCALE = 3.0  # ~216 DPI — достаточно для юридических сканов


def tesseract_cmd() -> str | None:
    """Абсолютный путь к tesseract.exe или имя в PATH; None если не найден."""
    env = os.environ.get("PRE_ANON_TESSERACT_CMD")
    if env and Path(env).exists():
        return env
    if Path(DEFAULT_TESSERACT).exists():
        return DEFAULT_TESSERACT
    found = shutil.which("tesseract")
    return found


def available() -> bool:
    """True, если движок и python-обвязка на месте."""
    if tesseract_cmd() is None:
        return False
    try:
        import pytesseract  # noqa: F401
        import pypdfium2  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def _lang() -> str:
    return os.environ.get("PRE_ANON_OCR_LANG", DEFAULT_LANG)


def _configure():
    import pytesseract
    cmd = tesseract_cmd()
    if cmd is None:
        raise RuntimeError(
            "Tesseract не найден. Установить: winget install UB-Mannheim.TesseractOCR "
            "(источник winget); или задать PRE_ANON_TESSERACT_CMD."
        )
    pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def ocr_image(path: Path) -> str:
    """Распознать одиночное изображение."""
    pytesseract = _configure()
    from PIL import Image
    with Image.open(path) as im:
        return pytesseract.image_to_string(im, lang=_lang())


def ocr_pdf(path: Path) -> str:
    """Распознать PDF постранично (рендер pypdfium2 → tesseract)."""
    pytesseract = _configure()
    import pypdfium2 as pdfium
    parts: list[str] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=RENDER_SCALE)
            pil = bitmap.to_pil()
            parts.append(pytesseract.image_to_string(pil, lang=_lang()))
    finally:
        pdf.close()
    return "\n\n".join(parts)
