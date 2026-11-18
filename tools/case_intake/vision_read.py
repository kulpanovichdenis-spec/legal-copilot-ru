#!/usr/bin/env python3
"""Дочитывание сканов, с которыми не справился локальный OCR (рукопись, плохой скан).

Watcher ставит в карточке `needs_vision_read: true`, если Tesseract выдал мусор.
Читает страницу модель агента в сессии — Python-процесс модель не вызывает,
поэтому здесь только детерминированная обвязка (класс A):

  render  — страницы оригинала в PNG во временную папку (вне workflow/);
  apply   — расшифровку агента записать в карточку вместо мусорного OCR
            (исходный OCR сохраняется в `ocr_text_head`), временную папку удалить.

Порядок и границы — skills/case-intake/SKILL.md, шаг 1а; правило о том, когда
модели можно показывать изображение, — references/ocr-setup.md.

Запуск:
  python tools/case_intake/vision_read.py render workflow/_claims/queue/<файл>.json
  python tools/case_intake/vision_read.py apply  workflow/_claims/queue/<файл>.json <расшифровка.txt> --cleanup <папка render>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))

from watcher import HEAD_CHARS, _atomic_card  # noqa: E402

DEFAULT_DPI = 150  # рукопись читается уверенно, картинка не раздувает контекст


def ensure_not_anonymizer(path: Path) -> None:
    """Материалы конвейера анонимизации модели по изображению не показываются никогда.

    Решение юриста 2026-10-08: картинка обходит маскирование, поэтому запрет
    безусловный — без флагов и исключений.
    """
    parts = {p.lower() for p in Path(path).resolve().parts}
    if "_anonymizer" in parts:
        raise PermissionError(
            f"дочитывание по изображению запрещено для workflow/_anonymizer/: {path}")


def render_pages(source: Path, out_dir: Path, *, dpi: int = DEFAULT_DPI) -> list[Path]:
    """Каждую страницу PDF/изображения — в PNG `p<N>.png`. Возвращает пути по порядку."""
    import fitz  # PyMuPDF открывает и PDF, и картинки

    ensure_not_anonymizer(source)
    ensure_not_anonymizer(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    with fitz.open(str(source)) as doc:
        for i, page in enumerate(doc, start=1):
            target = out_dir / f"p{i}.png"
            page.get_pixmap(dpi=dpi).save(str(target))
            pages.append(target)
    return pages


def apply_transcript(card_path: Path, transcript_path: Path) -> dict:
    """Записать расшифровку агента в карточку: она становится `text_head` для классификатора."""
    ensure_not_anonymizer(card_path)
    text =transcript_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("пустая расшифровка — карточка не изменена")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    if card.get("text_source") != "vision":
        card["ocr_text_head"] = card.get("text_head", "")
    card["text_head"] = text[:HEAD_CHARS]
    card["text_truncated"] = len(text) > HEAD_CHARS
    card["text_source"] = "vision"
    card["needs_vision_read"] = False
    _atomic_card(card_path, card)
    return card


def _source_of(card_path: Path) -> Path:
    card = json.loads(card_path.read_text(encoding="utf-8"))
    rel = card.get("processed_path")
    if not rel:
        raise SystemExit(f"в карточке нет processed_path: {card_path}")
    source = Path(rel) if Path(rel).is_absolute() else ROOT / rel
    if not source.is_file():
        raise SystemExit(f"оригинал не найден: {source}")
    return source


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Дочитывание сканов моделью: render / apply")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="страницы оригинала карточки → PNG во временную папку")
    r.add_argument("card")
    r.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    a = sub.add_parser("apply", help="расшифровку → в карточку")
    a.add_argument("card")
    a.add_argument("transcript")
    a.add_argument("--cleanup", help="удалить временную папку render после записи")
    args = ap.parse_args(argv)

    card_path = Path(args.card)
    try:
        ensure_not_anonymizer(card_path)
        if args.cmd == "render":
            source = _source_of(card_path)
            ensure_not_anonymizer(source)
    except PermissionError as exc:
        print(f"ЗАПРЕЩЕНО: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "render":
        out_dir = Path(tempfile.mkdtemp(prefix="vision_read_"))
        pages = render_pages(source, out_dir, dpi=args.dpi)
        print(json.dumps({"render_dir": str(out_dir), "pages": [str(p) for p in pages]},
                         ensure_ascii=False, indent=2))
        return 0

    try:
        apply_transcript(card_path, Path(args.transcript))
    except ValueError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    if args.cleanup:
        cleanup = Path(args.cleanup)
        if cleanup.name.startswith("vision_read_"):  # удаляем только свою временную папку
            shutil.rmtree(cleanup, ignore_errors=True)
    print(f"расшифровка записана в карточку: {card_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
