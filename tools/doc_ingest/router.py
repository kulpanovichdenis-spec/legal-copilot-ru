# -*- coding: utf-8 -*-
"""
tools/doc_ingest/router.py

Auto-роутер ингестии документов. Принимает путь к файлу, эвристически выбирает
backend (markitdown — лёгкий текстовый; striprtf — RTF; olefile-doc — Word 97–2003;
ocr — локальный Tesseract для сканов/фото) и сразу конвертирует. RTF и .doc
различаются по сигнатуре файла, а не по расширению. docling больше не выбирается
роутером автоматически — это
ручная тяжёлая эскалация (см. references/docling-mcp-setup.md).

Правила выбора задокументированы в `references/document-ingestion.md` §4.

CLI (через -m form из корня проекта):
    python -m tools.doc_ingest.router FILE                # convert + print
    python -m tools.doc_ingest.router FILE -o out.md      # convert + save
    python -m tools.doc_ingest.router FILE --recommend    # только рекомендация

Python API:
    from tools.doc_ingest.router import inspect, convert

    decision = inspect("Договор.pdf")
    # {"recommended_backend": "markitdown" | "striprtf" | "olefile-doc" | "ocr",
    #  "reason": "...",
    #  "warnings": [...]}

    result = convert("Договор.pdf")
    # markitdown → markitdown_runner.convert() shape;
    # ocr → ocr_runner.ocr_extract() shape
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Поддержка обоих способов запуска: `python -m tools.doc_ingest.router ...`
# и `python tools/doc_ingest/router.py ...` (через sys.path-инъекцию).
if __name__ == "__main__" and __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _project_root = _Path(__file__).resolve().parents[2]
    if str(_project_root) not in _sys.path:
        _sys.path.insert(0, str(_project_root))

from tools.doc_ingest.markitdown_runner import (
    convert as markitdown_convert,
    LIGHT_BACKEND_EXTENSIONS,  # noqa: F401 — экспортируется для других модулей
)


# Размер файла, при котором лучше идти на docling (даже для нативных Office).
LARGE_FILE_THRESHOLD_BYTES = 5 * 1024 * 1024  # 5 МБ

# Минимальное количество символов первой страницы PDF, чтобы считать,
# что текстовый слой есть. Меньше — вероятный скан.
PDF_TEXT_LAYER_MIN_CHARS = 100

# Расширения-сканы, которые идут на локальный OCR (markitdown их не читает).
SCAN_IMAGE_EXTENSIONS = frozenset({
    ".tiff", ".tif",     # обычно сканы
})

# Расширения, для которых markitdown надёжен. .rtf сюда не входит: markitdown 0.0.2
# отдаёт его сырой разметкой; .doc он не читает вовсе.
MARKITDOWN_SAFE_EXTENSIONS = frozenset({
    ".docx", ".xlsx", ".pptx",
    ".html", ".htm", ".csv", ".json", ".xml", ".txt", ".md",
    ".epub", ".zip",
})

# RTF и Word 97–2003 различаются по сигнатуре, а не по расширению: «.doc» с сайтов
# и из почты часто на деле RTF.
LEGACY_WORD_EXTENSIONS = frozenset({".rtf", ".doc"})
RTF_MAGIC = b"{\\rtf"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _pdf_has_text_layer(path: Path) -> tuple[bool, str]:
    """
    Проверить, есть ли в PDF текстовый слой.
    Возвращает (есть_ли, причина).

    Используем pdfminer.six (поставляется с markitdown[all]).
    """
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        return True, "pdfminer недоступен — считаем, что текстовый слой есть"

    try:
        # Извлекаем текст только из первой страницы для скорости
        text = extract_text(str(path), maxpages=1) or ""
        n = len(text.strip())
        if n >= PDF_TEXT_LAYER_MIN_CHARS:
            return True, f"текстовый слой найден ({n} символов на первой странице)"
        else:
            return False, f"текстовый слой пуст или почти пуст ({n} символов на первой странице) — вероятно скан"
    except Exception as e:
        # Если pdfminer споткнулся — лучше попробовать markitdown сначала
        return True, f"pdfminer не смог проверить ({type(e).__name__}: {e}) — предполагаем текстовый слой"


def inspect(path: str | Path) -> dict:
    """
    Проверить файл и вернуть рекомендацию по backend.

    Returns:
        {
          "path": str,
          "extension": str,
          "size_bytes": int,
          "recommended_backend": "markitdown" | "striprtf" | "olefile-doc" | "ocr",
          "reason": str,
          "warnings": list[str]
        }
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Файл не найден: {p}")
    if not p.is_file():
        raise ValueError(f"Не обычный файл: {p}")

    ext = p.suffix.lower()
    size = p.stat().st_size
    warnings: list[str] = []

    # 1. Сканы-изображения TIFF → локальный OCR
    if ext in SCAN_IMAGE_EXTENSIONS:
        return {
            "path": str(p), "extension": ext, "size_bytes": size,
            "recommended_backend": "ocr",
            "reason": f"расширение {ext} обычно скан — нужен локальный OCR",
            "warnings": ["[OCR]"],
        }

    # 2. RTF и старый Word — локальные разборщики по сигнатуре файла
    if ext in LEGACY_WORD_EXTENSIONS:
        with p.open("rb") as fh:
            head = fh.read(8)
        if head.startswith(RTF_MAGIC):
            return {
                "path": str(p), "extension": ext, "size_bytes": size,
                "recommended_backend": "striprtf",
                "reason": "RTF (сигнатура {\\rtf) — текст через striprtf",
                "warnings": warnings,
            }
        if ext == ".doc" and head == OLE_MAGIC:
            return {
                "path": str(p), "extension": ext, "size_bytes": size,
                "recommended_backend": "olefile-doc",
                "reason": "Word 97–2003 (OLE) — текст по piece table через olefile",
                "warnings": warnings,
            }

    # 3. Безопасные для markitdown форматы — сразу markitdown
    if ext in MARKITDOWN_SAFE_EXTENSIONS:
        if size > LARGE_FILE_THRESHOLD_BYTES:
            warnings.append(
                f"файл крупный ({size // 1024 // 1024} МБ) — markitdown может быть медленным; "
                f"при плохом результате попробовать docling"
            )
        return {
            "path": str(p),
            "extension": ext,
            "size_bytes": size,
            "recommended_backend": "markitdown",
            "reason": f"{ext} — нативный формат, markitdown надёжен",
            "warnings": warnings,
        }

    # 4. PDF — проверяем текстовый слой
    if ext == ".pdf":
        has_text, reason = _pdf_has_text_layer(p)
        if not has_text:
            return {
                "path": str(p), "extension": ext, "size_bytes": size,
                "recommended_backend": "ocr",
                "reason": f"PDF без текстового слоя: {reason}",
                "warnings": ["[OCR] — markitdown не извлечёт текст, распознаём локально"],
            }
        # Текстовый слой есть, но если файл большой — предупредить
        if size > LARGE_FILE_THRESHOLD_BYTES:
            warnings.append(
                f"PDF крупный ({size // 1024 // 1024} МБ) — markitdown может быть медленным; "
                f"при плохом качестве таблиц переключиться на docling"
            )
        return {
            "path": str(p),
            "extension": ext,
            "size_bytes": size,
            "recommended_backend": "markitdown",
            "reason": f"PDF с текстовым слоем: {reason}",
            "warnings": warnings,
        }

    # 5. Изображения — без OCR markitdown не справится с содержимым
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp"}:
        return {
            "path": str(p), "extension": ext, "size_bytes": size,
            "recommended_backend": "ocr",
            "reason": f"изображение {ext} — локальный OCR (облачный LLM-OCR запрещён)",
            "warnings": ["[OCR]"],
        }

    # 6. Неизвестное расширение — пробуем markitdown с предупреждением
    warnings.append(f"расширение {ext} не классифицировано — пробуем markitdown")
    return {
        "path": str(p),
        "extension": ext,
        "size_bytes": size,
        "recommended_backend": "markitdown",
        "reason": f"расширение {ext} не классифицировано — markitdown как fallback",
        "warnings": warnings,
    }


def _try_local_ocr(path: str | Path, decision: dict) -> dict | None:
    """Резервный постраничный OCR; None, если второй локальный backend недоступен."""
    try:
        from tools.doc_ingest import ocr_tesseract
    except ImportError:
        return None
    if not ocr_tesseract.is_available():
        return None
    try:
        result = ocr_tesseract.convert(path)
    except Exception:  # noqa: BLE001 — сбой резерва не должен ронять router
        return None
    result["metadata"]["warnings"] = (
        result["metadata"].get("warnings", []) + decision["warnings"]
    )
    result["router"] = decision
    return result


def _add_untrusted_warnings(path: str | Path, result: dict) -> dict:
    """Находки сканера недоверенного ввода → metadata.warnings (references/untrusted-input.md).

    Сбой сканера не роняет ингестию: документ важнее подстраховки.
    """
    try:
        from tools.doc_ingest.untrusted_scan import scan  # noqa: PLC0415
        findings = scan(path, result.get("markdown") or "")
    except Exception:  # noqa: BLE001
        return result
    if findings:
        meta = result.setdefault("metadata", {})
        meta["warnings"] = meta.get("warnings", []) + findings
    return result


def _text_backend(name: str):
    """Функция конверсии для текстового backend-а; None — backend не текстовый."""
    if name == "markitdown":
        return markitdown_convert
    if name == "striprtf":
        from tools.doc_ingest.rtf_runner import convert as rtf_convert  # noqa: PLC0415
        return rtf_convert
    if name == "olefile-doc":
        from tools.doc_ingest.doc_runner import convert as doc_convert  # noqa: PLC0415
        return doc_convert
    return None


def convert(path: str | Path) -> dict:
    """Сконвертировать файл и добавить находки сканера недоверенного ввода."""
    return _add_untrusted_warnings(path, _convert(path))


def _convert(path: str | Path) -> dict:
    """
    Сконвертировать файл, выбрав backend автоматически.

    markitdown / striprtf (.rtf) / olefile-doc (Word 97–2003) → текст локально;
    ocr → локальный Tesseract (ocr_runner).
    Любой иной backend (роутер такого не выдаёт) — защитный stub с exit-кодом 3.

    Returns:
        {
          "markdown": str,
          "metadata": dict,
          "router": dict (результат inspect())
        }
    """
    decision = inspect(path)

    if decision["recommended_backend"] == "ocr":
        from tools.doc_ingest import ocr_runner  # noqa: PLC0415
        result = ocr_runner.ocr_extract(path)
        if result["metadata"].get("backend") == "stub-ocr-unavailable":
            fallback = _try_local_ocr(path, decision)
            if fallback is not None:
                return fallback
        result["metadata"]["warnings"] = (
            result["metadata"].get("warnings", []) + decision["warnings"]
        )
        result["router"] = decision
        return result

    backend_convert = _text_backend(decision["recommended_backend"])
    if backend_convert is not None:
        result = backend_convert(path)
        result["metadata"]["warnings"] = (
            result["metadata"].get("warnings", []) + decision["warnings"]
        )
        result["router"] = decision
        return result

    # Защитный fallback: inspect() штатно возвращает только известные backend-ы,
    # поэтому сюда попадём лишь при нераспознанном backend — не падаем, а отдаём
    # stub с exit-кодом 3, чтобы caller-скрипт это заметил.
    return {
        "markdown": (
            f"[BACKEND НЕ РАСПОЗНАН]\n\n"
            f"Router вернул backend `{decision['recommended_backend']}` "
            f"({decision['reason']}), который скрипт не обрабатывает."
        ),
        "metadata": {
            "source": Path(path).name,
            "source_path": str(Path(path).resolve()),
            "extension": decision["extension"],
            "size_bytes": decision["size_bytes"],
            "backend": "stub-unknown-backend",
            "backend_version": None,
            "warnings": decision["warnings"] + [
                "[BACKEND НЕ РАСПОЗНАН — проверьте router.inspect]"
            ],
            "char_count": 0,
            "line_count": 0,
        },
        "router": decision,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Auto-роутер ингестии документов. Выбирает backend "
            "(markitdown / striprtf / olefile-doc / ocr) и конвертирует. См. "
            "references/document-ingestion.md."
        ),
    )
    parser.add_argument("input", help="Путь к входному файлу")
    parser.add_argument(
        "-o", "--output",
        help="Путь к .md (по умолчанию — stdout)",
    )
    parser.add_argument(
        "--recommend",
        action="store_true",
        help="Только показать рекомендацию backend-а (не конвертировать)",
    )
    parser.add_argument(
        "--json-meta",
        metavar="PATH",
        help="Записать метаданные в .json (или '-' для stderr)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Не выводить служебные сообщения",
    )
    args = parser.parse_args(argv)

    # Mode: только рекомендация
    if args.recommend:
        try:
            decision = inspect(args.input)
        except FileNotFoundError as e:
            sys.stderr.write(f"Ошибка: {e}\n")
            return 2
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return 0

    # Mode: полная конверсия
    try:
        result = convert(args.input)
    except FileNotFoundError as e:
        sys.stderr.write(f"Ошибка: {e}\n")
        return 2
    except Exception as e:
        sys.stderr.write(f"Ошибка конвертации: {type(e).__name__}: {e}\n")
        return 1

    markdown_text = result["markdown"]
    metadata = result["metadata"]
    router_info = result.get("router", {})

    # Сообщить, какой backend выбран
    if not args.quiet:
        sys.stderr.write(
            f"Router: backend={metadata.get('backend')} "
            f"({router_info.get('reason', '')})\n"
        )
        for w in metadata.get("warnings", []):
            sys.stderr.write(f"  warning: {w}\n")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown_text, encoding="utf-8")
        if not args.quiet:
            sys.stderr.write(f"Записано в {out}\n")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(markdown_text)

    if args.json_meta:
        meta_obj = {"metadata": metadata, "router": router_info}
        meta_json = json.dumps(meta_obj, ensure_ascii=False, indent=2)
        if args.json_meta == "-":
            sys.stderr.write(meta_json + "\n")
        else:
            mp = Path(args.json_meta)
            mp.parent.mkdir(parents=True, exist_ok=True)
            mp.write_text(meta_json, encoding="utf-8")
            if not args.quiet:
                sys.stderr.write(f"Метаданные в {mp}\n")

    # Нераспознанный backend вернул защитный stub — выйти с кодом 3, чтобы
    # caller-скрипт мог отличить это от успешной конверсии.
    if metadata.get("backend") == "stub-unknown-backend":
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
