# -*- coding: utf-8 -*-
"""Локальный офлайн-OCR backend для doc_ingest (Tesseract).

Извлекает текст из сканов/фото/PDF-без-текстового-слоя СКРИПТОМ, не заливая
картинку в модель (токен-экономия) и не отправляя ничего в облако
(конфиденциальность). Облачный LLM-OCR запрещён — см. references/ocr-setup.md.

Зависимости (локально): Tesseract + языковой пакет `rus`, pytesseract, PyMuPDF (fitz).
Нет Tesseract → ocr_extract возвращает stub с пометкой, не падает.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"})
# Ниже этого среднего доверия результат помечаем как ненадёжный (→ уточнение).
# Порог согласован с references/document-ingestion.md (маркер [ОЦР НЕ УВЕРЕН] при < 0.7).
LOW_CONFIDENCE = 0.70

# Tesseract на машине установлен, но НЕ в PATH (память: tesseract-local-not-in-path).
# Ищем бинарь по известным путям и указываем его pytesseract явно — НЕ ставим заново.
_TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
)


def _tesseract_path() -> str | None:
    """Путь к бинарю Tesseract: PATH → известные места установки (Windows)."""
    found = shutil.which("tesseract")
    if found:
        return found
    for cand in _TESSERACT_CANDIDATES:
        if cand and Path(cand).is_file():
            return cand
    return None


def tesseract_available() -> bool:
    """Есть ли Tesseract (в PATH или по известным путям) и обёртка pytesseract."""
    path = _tesseract_path()
    if not path:
        return False
    try:
        import pytesseract  # noqa: PLC0415
    except ImportError:
        return False
    pytesseract.pytesseract.tesseract_cmd = path
    return True


def _ocr_image(pil_image, lang: str) -> tuple[str, float]:
    """OCR одной картинки → (текст, среднее доверие 0..1)."""
    import pytesseract  # noqa: PLC0415

    data = pytesseract.image_to_data(pil_image, lang=lang,
                                     output_type=pytesseract.Output.DICT)
    words, confs = [], []
    for word, conf in zip(data["text"], data["conf"]):
        if word and word.strip():
            words.append(word)
            try:
                c = float(conf)
            except (TypeError, ValueError):
                c = -1.0
            if c >= 0:
                confs.append(c / 100.0)
    text = " ".join(words)
    confidence = sum(confs) / len(confs) if confs else 0.0
    return text, confidence


def ocr_extract(path: str | Path, *, lang: str = "rus+eng") -> dict:
    """Извлечь текст из скана/фото/PDF локальным OCR.

    Возвращает {"markdown", "metadata"}. Без Tesseract — stub (не падает).
    """
    p = Path(path)
    if not tesseract_available():
        return {
            "markdown": "",
            "metadata": {
                "source": p.name, "source_path": str(p.resolve()),
                "extension": p.suffix.lower(), "backend": "stub-ocr-unavailable",
                "char_count": 0, "confidence": 0.0,
                "warnings": ["[OCR НЕДОСТУПЕН] — установите Tesseract+rus "
                             "(references/ocr-setup.md); файл не распознан"],
            },
        }

    import fitz  # PyMuPDF  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    import io  # noqa: PLC0415

    pages_text: list[str] = []
    confs: list[float] = []
    ext = p.suffix.lower()
    if ext == ".pdf":
        doc = fitz.open(str(p))
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            t, c = _ocr_image(img, lang)
            pages_text.append(t)
            confs.append(c)
        doc.close()
    elif ext in IMAGE_EXTS:
        img = Image.open(str(p))
        t, c = _ocr_image(img, lang)
        pages_text.append(t)
        confs.append(c)
    else:
        return {
            "markdown": "",
            "metadata": {
                "source": p.name, "extension": ext, "backend": "ocr-tesseract",
                "char_count": 0, "confidence": 0.0,
                "warnings": [f"[OCR] расширение {ext} не поддержано OCR-backend"],
            },
        }

    text = "\n\n".join(t for t in pages_text if t)
    confidence = sum(confs) / len(confs) if confs else 0.0
    warnings = []
    if confidence < LOW_CONFIDENCE:
        warnings.append(f"[ОЦР НЕ УВЕРЕН] низкое доверие OCR "
                        f"({confidence:.2f}) — вероятен плохой скан, нужно уточнение")
    return {
        "markdown": text,
        "metadata": {
            "source": p.name, "source_path": str(p.resolve()), "extension": ext,
            "backend": "ocr-tesseract", "char_count": len(text),
            "confidence": round(confidence, 3), "pages": len(pages_text),
            "warnings": warnings,
        },
    }
