# -*- coding: utf-8 -*-
"""
tests/doc_ingest_smoke.py — автоматизированный smoke-тест ingestion-слоя.

Прогоняет router и markitdown_runner на стандартных файлах проекта
(.md / .json / .txt — все доступные в репозитории) и проверяет:
- inspect() возвращает правильный backend;
- convert() возвращает непустой markdown + metadata;
- router для сканов читает локальным tesseract, а при его отсутствии возвращает stub.

Не покрывает (требует реальных файлов от юриста — этап 9.6 ручной):
- сканированный PDF (router → локальный ocr);
- нативный .docx договора (markitdown с сохранением нумерации);
- многостраничный PDF с таблицами (markitdown vs docling сравнение);
- .xlsx со спецификацией;
- креатив рекламы (.png → локальный ocr).

Запуск:
    python -m tests.doc_ingest_smoke
    python tests/doc_ingest_smoke.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Поддержка обоих способов запуска
if __name__ == "__main__" and __package__ in (None, ""):
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

from tools.doc_ingest.router import inspect, convert
from tools.doc_ingest.markitdown_runner import convert as markitdown_convert


def test_file(path: Path) -> tuple[bool, str]:
    """Тестирует один файл. Возвращает (ok, message)."""
    if not path.exists():
        return False, f"файл не найден"
    if not path.is_file():
        return False, f"не обычный файл"

    decision = inspect(path)
    backend = decision["recommended_backend"]
    reason = decision["reason"]
    warnings = decision["warnings"]

    msg = f"router={backend} ({reason})"
    if warnings:
        msg += f", warnings={len(warnings)}"

    result = convert(path)
    meta = result["metadata"]
    md = result["markdown"]

    if backend == "markitdown":
        if meta["backend"] != "markitdown":
            return False, f"router сказал markitdown, но backend={meta['backend']}"
        if len(md) == 0:
            return False, f"markitdown вернул пустой markdown"
        msg += f", converted={meta['char_count']} chars in {meta['duration_sec']}s"
    elif backend == "ocr":
        if meta["backend"] not in ("ocr-tesseract", "tesseract-ocr", "stub-ocr-unavailable"):
            return False, f"router сказал ocr, но backend={meta['backend']}"
        msg += f", ocr backend={meta['backend']}"
    else:
        return False, f"неизвестный backend: {backend}"

    return True, msg


def main() -> int:
    # Принудительно UTF-8 для stdout — иначе PowerShell cp1251 ломает кириллицу + эмодзи
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"")

    test_files = [
        # Markdown (markitdown ожидается)
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "CLAUDE.md",
        PROJECT_ROOT / "SETUP.md",
        PROJECT_ROOT / "logs" / "roadmap.md",
        PROJECT_ROOT / "logs" / "external-tools-research.md",
        PROJECT_ROOT / "references" / "document-ingestion.md",
        # Text (markitdown ожидается; .txt не в safe-list, fallback markitdown)
        PROJECT_ROOT / "requirements.txt",
        # JSON (markitdown ожидается)
        PROJECT_ROOT / ".mcp.json",
    ]

    passed = 0
    failed = 0
    failures: list[tuple[str, str]] = []

    for f in test_files:
        rel = f.relative_to(PROJECT_ROOT) if f.is_relative_to(PROJECT_ROOT) else f
        try:
            ok, message = test_file(f)
            if ok:
                print(f"  [PASS] {rel} — {message}")
                passed += 1
            else:
                print(f"  [FAIL] {rel} — {message}")
                failed += 1
                failures.append((str(rel), message))
        except Exception as e:
            tb = traceback.format_exc().splitlines()[-3:]
            print(f"  [ERROR] {rel} — {type(e).__name__}: {e}")
            for line in tb:
                print(f"          {line}")
            failed += 1
            failures.append((str(rel), f"{type(e).__name__}: {e}"))

    print(f"")
    print(f"=== Smoke summary ===")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failures:
        print(f"")
        print(f"Failures:")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
        return 1

    print(f"")
    print(f"✅ Все доступные файлы прошли smoke-тест.")
    print(f"")
    print(f"Что НЕ покрыто (нужен ручной прогон с реальными файлами):")
    print(f"  - сканированный PDF (router → локальный ocr)")
    print(f"  - нативный .docx договора (markitdown, сохранение нумерации)")
    print(f"  - .pdf договора с таблицами")
    print(f"  - .xlsx со спецификацией")
    print(f"  - макет рекламы (.png — router → локальный ocr)")
    print(f"")
    print(f"См. tests/doc_ingest_manual_smoke.md для ручного прогона.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
