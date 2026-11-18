# -*- coding: utf-8 -*-
"""
tools/doc_ingest/ocr_tesseract.py

Локальный OCR (tesseract) для сканов: PDF без текстового слоя и изображений.
Всё выполняется на машине юриста, ничего не уходит в сеть, поэтому подходит
для конфиденциальных материалов (references/document-ingestion.md, §4.3 и §7).

OCR недословный: встречаются ошибки в отдельных буквах, а штампы и печати
нарушают порядок чтения. Результат годится для поиска и нечёткой сверки
цитат, но не как источник дословного текста.

Поиск бинарника (системный PATH не меняется):
  1) переменная окружения TESSERACT_CMD;
  2) tesseract из PATH;
  3) %LOCALAPPDATA%\\Programs\\Tesseract-OCR\\tesseract.exe;
  4) %ProgramFiles%\\Tesseract-OCR\\tesseract.exe и C:\\Program Files\\Tesseract-OCR.

CLI:
    python tools/doc_ingest/ocr_tesseract.py FILE [--lang rus] [--dpi 300]
    python tools/doc_ingest/ocr_tesseract.py --where
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

ENV_VAR = "TESSERACT_CMD"
DEFAULT_LANG = "rus"
DEFAULT_DPI = 300
OCR_WARNING = (
    "OCR недословный: текст годится для поиска и нечёткой сверки цитат, "
    "дословные реквизиты сверять со сканом"
)


class OcrUnavailable(RuntimeError):
    """tesseract, pytesseract или нужный язык недоступны на этой машине."""


def _default_candidates() -> list[Path]:
    out: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(Path(local) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base:
            out.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
    out.append(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
    return out


def find_tesseract(env=None, which=shutil.which, candidates=None) -> str | None:
    """Путь к бинарнику tesseract или None. Параметры нужны для тестов."""
    env = os.environ if env is None else env
    explicit = env.get(ENV_VAR)
    if explicit and Path(explicit).is_file():
        return str(explicit)
    found = which("tesseract")
    if found:
        return found
    for cand in (_default_candidates() if candidates is None else candidates):
        if Path(cand).is_file():
            return str(cand)
    return None


def _engine(lang: str):
    """pytesseract, настроенный на найденный бинарник; проверяет языковые данные."""
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrUnavailable("не установлен pytesseract: pip install pytesseract") from exc
    cmd = find_tesseract()
    if not cmd:
        raise OcrUnavailable(
            "tesseract не найден (TESSERACT_CMD, PATH, стандартные каталоги установки)"
        )
    pytesseract.pytesseract.tesseract_cmd = cmd
    available = set(pytesseract.get_languages(config=""))
    missing = [x for x in lang.split("+") if x not in available]
    if missing:
        raise OcrUnavailable(
            f"нет языковых данных tesseract: {', '.join(missing)} "
            f"(есть: {', '.join(sorted(available))})"
        )
    return pytesseract


def is_available(lang: str = DEFAULT_LANG) -> bool:
    try:
        _engine(lang)
    except OcrUnavailable:
        return False
    return True


def ocr_pdf_pages(path: str | Path, *, lang: str = DEFAULT_LANG,
                  dpi: int = DEFAULT_DPI) -> list[str]:
    """Текст каждой страницы PDF (список по номерам страниц, с нуля)."""
    import fitz
    from PIL import Image

    engine = _engine(lang)
    pages: list[str] = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(engine.image_to_string(img, lang=lang))
    return pages


def ocr_image(path: str | Path, *, lang: str = DEFAULT_LANG) -> str:
    from PIL import Image

    engine = _engine(lang)
    with Image.open(str(path)) as img:
        return engine.image_to_string(img.convert("RGB"), lang=lang)


def convert(path: str | Path, *, lang: str = DEFAULT_LANG,
            dpi: int = DEFAULT_DPI) -> dict:
    """Форма результата совпадает с markitdown_runner.convert()."""
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Файл не найден: {p}")
    started = time.time()
    if p.suffix.lower() == ".pdf":
        pages = ocr_pdf_pages(p, lang=lang, dpi=dpi)
    else:
        pages = [ocr_image(p, lang=lang)]
    markdown = "\n\n".join(
        f"## Стр. {i}\n\n{text.strip()}" for i, text in enumerate(pages, start=1)
    )
    engine = _engine(lang)
    try:
        version = str(engine.get_tesseract_version())
    except Exception:  # noqa: BLE001 — версия справочная, сбой не критичен
        version = "unknown"
    return {
        "markdown": markdown,
        "metadata": {
            "source": p.name,
            "source_path": str(p),
            "extension": p.suffix.lower(),
            "size_bytes": p.stat().st_size,
            "backend": "tesseract-ocr",
            "backend_version": version,
            "ocr_lang": lang,
            "pages": len(pages),
            "duration_sec": round(time.time() - started, 3),
            "char_count": len(markdown),
            "line_count": markdown.count("\n") + 1,
            "warnings": [OCR_WARNING],
        },
    }


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Локальный OCR (tesseract) для сканов")
    ap.add_argument("input", nargs="?", help="PDF или изображение")
    ap.add_argument("--lang", default=DEFAULT_LANG)
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    ap.add_argument("--where", action="store_true", help="показать найденный tesseract")
    args = ap.parse_args(argv)
    if args.where:
        cmd = find_tesseract()
        print(cmd or "tesseract не найден")
        return 0 if cmd else 1
    if not args.input:
        ap.error("нужен файл (или --where)")
    try:
        result = convert(args.input, lang=args.lang, dpi=args.dpi)
    except (OcrUnavailable, FileNotFoundError) as exc:
        sys.stderr.write(f"Ошибка: {exc}\n")
        return 2
    print(result["markdown"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
