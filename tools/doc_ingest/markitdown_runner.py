# -*- coding: utf-8 -*-
"""
tools/doc_ingest/markitdown_runner.py

Лёгкая обёртка над markitdown — преобразует документ в нормализованный Markdown
с метаданными. Используется как «лёгкий» backend в Направлении 9 (см.
references/document-ingestion.md).

Когда использовать:
- нативный .docx, .xlsx, .pptx, .csv, .html, .epub, .json, .xml;
- PDF с текстовым слоем (не сканы);
- небольшие документы (до ~5 МБ).

Когда НЕ использовать (использовать docling MCP — см. Направление 9.2):
- сканированные PDF (нет текстового слоя);
- многоколоночные PDF судебных актов;
- PDF с критически важными таблицами;
- документы со сложным layout (формулы, footnotes).

CLI:
    python tools/doc_ingest/markitdown_runner.py FILE
    python tools/doc_ingest/markitdown_runner.py FILE -o out.md
    python tools/doc_ingest/markitdown_runner.py FILE -o out.md --json-meta meta.json

Python API:
    from tools.doc_ingest.markitdown_runner import convert
    result = convert("Договор.docx")
    print(result["markdown"])
    print(result["metadata"])

Возвращает:
    {
      "markdown": "<нормализованный Markdown>",
      "metadata": {
        "source": "Договор.docx",
        "source_path": "<абсолютный путь>",
        "extension": ".docx",
        "size_bytes": 12345,
        "backend": "markitdown",
        "backend_version": "0.0.2",
        "duration_sec": 0.32,
        "char_count": 6789,
        "line_count": 234
      }
    }
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from markitdown import MarkItDown
except ImportError as e:
    sys.stderr.write(
        "markitdown не установлен. Установите:\n"
        "    pip install 'markitdown[all]'\n"
        "Если pip ставит в user-site и Python не видит — `--target` "
        "в системный site-packages.\n"
    )
    raise


# Расширения, на которых markitdown ожидаемо работает хорошо.
# Для всего остального — рассмотреть docling (см. tools/doc_ingest/router.py
# когда будет создан).
LIGHT_BACKEND_EXTENSIONS = frozenset({
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".html", ".htm", ".csv", ".json", ".xml", ".txt", ".md",
    ".rtf", ".epub", ".zip",
    # PDF с текстовым слоем — пробуем сначала здесь; роутер позже решит
    ".pdf",
    # изображения — без OCR (markitdown OCR — отдельная подсистема через LLM)
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff",
})


def _markitdown_version() -> str:
    try:
        from importlib.metadata import version
        return version("markitdown")
    except Exception:
        return "unknown"


def convert(path: str | Path) -> dict:
    """
    Преобразовать документ в Markdown через markitdown.

    Args:
        path: путь к входному файлу (абсолютный или относительный).

    Returns:
        Словарь {"markdown": str, "metadata": dict}. См. модульный docstring.

    Raises:
        FileNotFoundError: файл не существует.
        ValueError: путь указывает не на обычный файл (директория, симлинк-цикл)
            или markitdown не смог его конвертировать (например, .doc).
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Файл не найден: {p}")
    if not p.is_file():
        raise ValueError(f"Не обычный файл: {p}")

    ext = p.suffix.lower()
    if ext not in LIGHT_BACKEND_EXTENSIONS:
        # Не блокируем — markitdown может что-то сделать. Но это маркер для
        # роутера: «возможно, нужен docling».
        sys.stderr.write(
            f"[warn] расширение {ext} не в списке проверенных для markitdown. "
            f"Если результат плохой — попробовать docling backend.\n"
        )

    started = time.time()
    md = MarkItDown()
    try:
        result = md.convert(str(p))
    except BaseException as exc:
        # markitdown наследует свои исключения (UnsupportedFormatException и др.)
        # от BaseException — их не ловит ни один `except Exception`, и один
        # неподдерживаемый файл (.doc) ронял весь единый watcher. Обычные
        # исключения и KeyboardInterrupt/SystemExit пробрасываются как есть.
        if isinstance(exc, Exception) or not type(exc).__module__.startswith("markitdown"):
            raise
        raise ValueError(
            f"markitdown не смог конвертировать {p.name}: {type(exc).__name__}: {exc}"
        ) from exc
    duration = time.time() - started

    markdown_text = result.text_content or ""

    return {
        "markdown": markdown_text,
        "metadata": {
            "source": p.name,
            "source_path": str(p),
            "extension": ext,
            "size_bytes": p.stat().st_size,
            "backend": "markitdown",
            "backend_version": _markitdown_version(),
            "duration_sec": round(duration, 3),
            "char_count": len(markdown_text),
            "line_count": markdown_text.count("\n") + 1,
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Преобразовать документ в Markdown через markitdown. "
            "Лёгкий backend проекта."
        ),
    )
    parser.add_argument("input", help="Путь к входному файлу")
    parser.add_argument(
        "-o", "--output",
        help="Путь к .md (по умолчанию — stdout)",
    )
    parser.add_argument(
        "--json-meta",
        metavar="PATH",
        help="Записать метаданные в указанный .json (или '-' для stderr)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Не выводить служебные сообщения в stderr",
    )
    args = parser.parse_args(argv)

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

    # Markdown — в файл или в stdout (UTF-8)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown_text, encoding="utf-8")
        if not args.quiet:
            sys.stderr.write(
                f"Записано в {out} ({metadata['char_count']} символов, "
                f"{metadata['duration_sec']} сек)\n"
            )
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(markdown_text)

    # Метаданные
    if args.json_meta:
        meta_json = json.dumps(metadata, ensure_ascii=False, indent=2)
        if args.json_meta == "-":
            sys.stderr.write(meta_json + "\n")
        else:
            mp = Path(args.json_meta)
            mp.parent.mkdir(parents=True, exist_ok=True)
            mp.write_text(meta_json, encoding="utf-8")
            if not args.quiet:
                sys.stderr.write(f"Метаданные в {mp}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
