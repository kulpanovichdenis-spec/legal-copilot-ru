#!/usr/bin/env python3
"""On-demand ингестия материалов в слой знаний профиля (класс A, без LLM).

Юрист кладёт Word/PDF/картинки в profile/knowledge/<домен>/_inbox/. Проход:
  1) извлекает текст через tools/doc_ingest;
  2) пишет ЧЕРНОВИК-карточку в cards/<slug>.md со status: needs_enrichment;
  3) убирает оригинал в originals/.
Структурирование в качественную карточку делает агент по skill knowledge-intake
(класс B). Соглашение — references/profile-knowledge-layer.md.

Расположение слоя берётся из profile_root() — переносимый профиль поддержан.

Запуск:
  python tools/knowledge_ingest/intake.py --domain products --once
  python tools/knowledge_ingest/intake.py --domain corporate --once
  python tools/knowledge_ingest/intake.py --selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
import warnings
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DOMAINS = {
    "products": "product",
    "corporate": "corporate",
    "compliance": "compliance_document",
}
SUPPORTED = {".docx", ".doc", ".pdf", ".txt", ".md", ".rtf", ".odt",
             ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
INCOMPLETE_SUFFIXES = (".tmp", ".crdownload", ".part", ".download")
_UNSAFE = '/\\:*?"<>|'


def slugify(name: str) -> str:
    out = "".join("-" if ch in _UNSAFE else ch for ch in (name or ""))
    out = "-".join(out.split())
    return out.strip("-. ").lower() or "card"


def skip_reason(path: Path) -> str | None:
    name = path.name
    if name == ".gitkeep" or name.startswith("."):
        return "hidden"
    if name.startswith("~$"):
        return "lock"
    if any(name.endswith(s) for s in INCOMPLETE_SUFFIXES):
        return "incomplete"
    if path.suffix.lower() not in SUPPORTED:
        return "unsupported"
    return None


def unique_path(target_dir: Path, name: str) -> Path:
    existing = {p.name for p in target_dir.iterdir()} if target_dir.exists() else set()
    if name not in existing:
        return target_dir / name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while f"{stem} ({n})" + (f".{ext}" if ext else "") in existing:
        n += 1
    return target_dir / (f"{stem} ({n})" + (f".{ext}" if ext else ""))


def _one_line(value: object) -> str:
    return " ".join(str(value).replace("|", "\\|").replace("`", "'").split())


def _xlsx_located_text(path: Path) -> tuple[str, dict]:
    """Извлечь XLSX с адресами листов/ячеек, не изменяя книгу."""
    from openpyxl import load_workbook  # noqa: PLC0415

    caught: list[warnings.WarningMessage]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        workbook = load_workbook(path, read_only=False, data_only=False)
    lines: list[str] = []
    nonempty = formulas = validations = merged_ranges = 0
    sheet_names: list[str] = []
    try:
        for sheet in workbook.worksheets:
            sheet_names.append(sheet.title)
            safe_title = sheet.title.replace("'", "''")
            lines.extend([f"## Лист: {sheet.title}", ""])
            validations += (
                len(sheet.data_validations.dataValidation)
                if sheet.data_validations is not None else 0
            )
            merged_ranges += len(sheet.merged_cells.ranges)
            for row in sheet.iter_rows():
                cells = [cell for cell in row if cell.value is not None]
                if not cells:
                    continue
                nonempty += len(cells)
                formulas += sum(
                    isinstance(cell.value, str) and cell.value.startswith("=")
                    for cell in cells
                )
                first, last = cells[0].coordinate, cells[-1].coordinate
                locator = f"'{safe_title}'!{first}:{last}"
                rendered = " | ".join(
                    f"{cell.coordinate}={_one_line(cell.value)}" for cell in cells
                )
                lines.append(f"- `{locator}`: {rendered}")
            lines.append("")
    finally:
        workbook.close()

    warning_messages = list(dict.fromkeys(str(item.message) for item in caught))
    if formulas or validations or merged_ranges:
        warning_messages.append(
            "[XLSX STRUCTURED REVIEW] Формулы, validation или объединённые ячейки "
            "требуют проверки по оригиналу; извлечение сохраняет координаты."
        )
    metadata = {
        "backend": "openpyxl-located",
        "char_count": len("\n".join(lines)),
        "warnings": warning_messages,
        "source_locator_scheme": "sheet_cell_range",
        "needs_structured_review": bool(formulas or validations or merged_ranges),
        "needs_layout_review": False,
        "office_structure": {
            "sheet_count": len(sheet_names),
            "sheet_names": sheet_names,
            "nonempty_cells": nonempty,
            "formula_cells": formulas,
            "data_validations": validations,
            "merged_ranges": merged_ranges,
        },
    }
    return "\n".join(lines).strip(), metadata


def _pptx_structure(path: Path, markdown: str) -> dict:
    """Собрать безопасные структурные метрики PPTX без рендера и OCR."""
    from pptx import Presentation  # noqa: PLC0415
    from pptx.enum.shapes import MSO_SHAPE_TYPE  # noqa: PLC0415

    presentation = Presentation(path)
    pictures = tables = charts = text_shapes = native_text_chars = 0
    image_only_slides: list[int] = []
    for number, slide in enumerate(presentation.slides, start=1):
        slide_pictures = slide_text_chars = 0
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                pictures += 1
                slide_pictures += 1
            if getattr(shape, "has_text_frame", False):
                text_shapes += 1
                chars = len((shape.text or "").strip())
                native_text_chars += chars
                slide_text_chars += chars
            if getattr(shape, "has_table", False):
                tables += 1
            if getattr(shape, "has_chart", False):
                charts += 1
        if slide_pictures and slide_text_chars < 20:
            image_only_slides.append(number)
    slide_count = len(presentation.slides)
    needs_layout_review = bool(
        path.stat().st_size > 5 * 1024 * 1024
        or pictures
        or tables
        or charts
        or image_only_slides
    )
    result = {
        "source_locator_scheme": "slide",
        "needs_layout_review": needs_layout_review,
        "needs_structured_review": False,
        "office_structure": {
            "slide_count": slide_count,
            "picture_count": pictures,
            "table_count": tables,
            "chart_count": charts,
            "text_shape_count": text_shapes,
            "native_text_chars": native_text_chars,
            "image_only_slides": image_only_slides,
            "markdown_slide_markers": markdown.lower().count("<!-- slide"),
        },
    }
    return result


def extract_text(path: Path) -> tuple[str, str, dict]:
    """Вернуть (текст, backend, metadata); обработка всегда локальная."""
    if path.suffix.lower() in {".txt", ".md"}:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return text, "plain", {
                "backend": "plain", "char_count": len(text), "warnings": []
            }
        except OSError:
            return "", "plain", {"backend": "plain", "char_count": 0, "warnings": []}
    try:
        sys.path.insert(0, str(ROOT / "tools" / "doc_ingest"))
        import router  # type: ignore  # noqa: PLC0415
        if path.suffix.lower() == ".xlsx":
            decision = router.inspect(path)
            text, metadata = _xlsx_located_text(path)
            metadata["router"] = decision
            metadata["warnings"] = list(dict.fromkeys(
                [*metadata.get("warnings", []), *decision.get("warnings", [])]
            ))
            return text, str(metadata["backend"]), metadata
        res = router.convert(path)
        text = res.get("markdown") or ""
        metadata = dict(res.get("metadata") or {})
        backend = metadata.get("backend") or "unknown"
        if path.suffix.lower() == ".pptx":
            structure = _pptx_structure(path, text)
            metadata.update(structure)
            if structure["needs_layout_review"]:
                metadata["warnings"] = list(dict.fromkeys([
                    *metadata.get("warnings", []),
                    "[PPTX LAYOUT REVIEW] Нативный текст извлечён; изображения, "
                    "таблицы и порядок чтения проверить по слайдам.",
                ]))
        metadata.setdefault("char_count", len(text))
        metadata.setdefault("warnings", [])
        return text, str(backend), metadata
    except Exception as exc:  # noqa: BLE001 — сбой ингестии не роняет проход
        text = f"[ИНГЕСТИЯ НЕ УДАЛАСЬ: {exc}]"
        return text, "failed", {
            "backend": "failed",
            "char_count": len(text),
            "warnings": [f"{type(exc).__name__}: {exc}"],
        }


def build_draft_card(doc_type: str, name: str, source_rel: str,
                     backend: str, raw_text: str, today: str,
                     source_hash: str | None = None,
                     ingest_metadata: dict | None = None) -> str:
    body = raw_text.strip() or "[ПУСТО — проверить исходник или backend ингестии]"
    if doc_type == "compliance_document":
        metadata = ingest_metadata or {}
        document_id = "POL-" + slugify(name).upper()
        return "\n".join([
            "---",
            "type: compliance_document",
            f'document_id: "{document_id}"',
            f'title: "{name}"',
            "document_type: null",
            "version: null",
            "effective_from: null",
            "effective_to: null",
            "owner_function: null",
            f'source_files: ["{source_rel}"]',
            f'source_hash: "{source_hash or ""}"',
            "verification: candidate",
            "status: needs_enrichment",
            "coverage_status: not_extracted",
            f"ingest_backend: {backend}",
            f"ingest_char_count: {int(metadata.get('char_count') or len(raw_text))}",
            "ingest_warnings: " + json.dumps(
                metadata.get("warnings", []), ensure_ascii=False
            ),
            "source_locator_scheme: " + json.dumps(
                metadata.get("source_locator_scheme"), ensure_ascii=False
            ),
            "needs_layout_review: " + str(
                bool(metadata.get("needs_layout_review"))
            ).lower(),
            "needs_structured_review: " + str(
                bool(metadata.get("needs_structured_review"))
            ).lower(),
            "office_structure: " + json.dumps(
                metadata.get("office_structure", {}), ensure_ascii=False
            ),
            f"updated: {today}",
            "---",
            "",
            "<!-- Кандидат документа. knowledge-intake выделяет атомарные rule-карточки;",
            "     verified присваивает только юрист. Нулевой поиск не означает отсутствие правила. -->",
            "",
            "## Извлечённый текст",
            "",
            body,
            "",
        ])
    return "\n".join([
        "---",
        f"type: {doc_type}",
        f'name: "{name}"',
        "aliases: []",
        "reg_number: null",
        f'source_files: ["{source_rel}"]',
        "verification: candidate",
        "status: needs_enrichment",
        f"ingest_backend: {backend}",
        f"updated: {today}",
        "---",
        "",
        "<!-- ЧЕРНОВИК. Агент (skill knowledge-intake) структурирует факты с",
        "     провенансом и маркерами пробелов, уточняет name/aliases/reg_number,",
        "     затем ставит status: enriched. verified присваивает только юрист. -->",
        "",
        "## Извлечённый текст (сырьё для карточки)",
        "",
        body,
        "",
    ])


def process_once(
    domain_dir: Path,
    doc_type: str,
    *,
    verbose: bool = True,
    files: list[Path] | None = None,
) -> dict:
    inbox = domain_dir / "_inbox"
    cards = domain_dir / "cards" / "documents" if doc_type == "compliance_document" else domain_dir / "cards"
    originals = domain_dir / "originals"
    for d in (inbox, cards, originals):
        d.mkdir(parents=True, exist_ok=True)
    stats = {"drafted": 0, "skipped": 0, "cards": []}
    today = dt.date.today().isoformat()
    candidates = files if files is not None else [p for p in inbox.iterdir() if p.is_file()]
    for path in sorted(candidates):
        reason = skip_reason(path)
        if reason:
            stats["skipped"] += 1
            if verbose:
                print(f"[пропуск:{reason}] {path.name}")
            continue
        text, backend, metadata = extract_text(path)
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        dest = unique_path(originals, path.name)
        shutil.move(str(path), str(dest))
        card_path = unique_path(cards, f"{slugify(path.stem)}.md")
        card_path.write_text(
            build_draft_card(doc_type, path.stem, f"originals/{dest.name}",
                             backend, text, today, source_hash, metadata),
            encoding="utf-8")
        stats["cards"].append(str(card_path))
        stats["drafted"] += 1
        if verbose:
            print(f"[черновик] {path.name} → cards/{card_path.name} (backend={backend})")
    return stats


def selftest() -> int:
    import tempfile
    import yaml
    with tempfile.TemporaryDirectory() as tmp:
        dom = Path(tmp) / "products"
        (dom / "_inbox").mkdir(parents=True)
        (dom / "_inbox" / "Инструкция.txt").write_text("Состав: диосмин.", encoding="utf-8")
        (dom / "_inbox" / "x.crdownload").write_bytes(b"\x00" * 8)
        stats = process_once(dom, "product", verbose=False)
        problems = []
        if stats["drafted"] != 1:
            problems.append(f"черновиков {stats['drafted']} != 1")
        if stats["skipped"] != 1:
            problems.append(f"пропусков {stats['skipped']} != 1")
        cards = list((dom / "cards").glob("*.md"))
        if len(cards) != 1:
            problems.append(f"карточек {len(cards)} != 1")
        else:
            fm = yaml.safe_load(cards[0].read_text(encoding="utf-8").split("---")[1])
            if fm.get("status") != "needs_enrichment":
                problems.append("status != needs_enrichment")
        if not list((dom / "originals").glob("*.txt")):
            problems.append("оригинал не перемещён")
        if problems:
            print("SELFTEST FAIL:")
            for p in problems:
                print("  - " + p)
            return 1
    print("SELFTEST OK: проход ингестии отработал корректно")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="On-demand ингестия материалов в profile/knowledge/<домен>/")
    ap.add_argument("--domain", choices=sorted(DOMAINS))
    ap.add_argument("--once", action="store_true", help="один проход (по умолчанию)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.domain:
        ap.error("нужен --domain products|corporate|compliance (или --selftest)")
    from tools.profile.profile_lib import profile_root  # noqa: PLC0415
    domain_dir = profile_root() / "knowledge" / args.domain
    stats = process_once(domain_dir, DOMAINS[args.domain])
    print(f"Готово: черновиков {stats['drafted']}, пропущено {stats['skipped']}. "
          f"Дальше — разобрать карточки агентом (skill knowledge-intake).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
