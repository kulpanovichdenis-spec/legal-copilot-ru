#!/usr/bin/env python3
"""Pre-LLM подготовка документа: конвертация в Markdown + обезличивание.

Конвейер (вне LLM-контура — модель оригинал не видит):
    входной .docx/.pdf/.md/... → markitdown (tools/doc_ingest) → Markdown
    (.doc/.rtf → doc_ingest.router: olefile / striprtf)
    → Anonymizer (tools/pre_anonymize/anonymizer.py)
    → <имя>.anon.md (передаётся агенту) + <имя>.mapping.json (локальный словарь
      плейсхолдер→оригинал для обратной подстановки; НЕ показывать LLM).

Профили строгости:
    full     — маскируется всё (по умолчанию);
    analytic — суммы, даты, сроки оплаты, количества, проценты, НДС остаются
               открытыми (нужны LLM для анализа сроков и расчётов).

Restore: черновик с плейсхолдерами (.md/.txt/.docx) + mapping.json →
файл с реальными реквизитами. Для .docx замена идёт по run'ам, при разрыве
плейсхолдера между run'ами — пересборка текста абзаца (форматирование абзаца
сохраняется по первому run).

Usage:
    python tools/pre_anonymize/prepare.py prepare <файл> [--profile full|analytic|sample] [--out-dir DIR]
    python tools/pre_anonymize/prepare.py restore <черновик> --mapping <mapping.json> [-o OUT]
    python tools/pre_anonymize/prepare.py selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

from anonymizer import Anonymizer, restore_reverse  # noqa: E402
import ocr  # noqa: E402

TEXT_EXTS = {".md", ".txt"}
# Старый Word и RTF markitdown не читает: их разбирает doc_ingest.router по сигнатуре.
LEGACY_WORD_EXTS = {".doc", ".rtf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
# Ниже этого порога считаем текст «пустым»: markitdown на скане без текстового
# слоя отдаёт мусорные крохи — тогда падаем в OCR, а если и он пуст — guard.
PDF_TEXT_LAYER_MIN = 100
MIN_TEXT_CHARS = 15
ANALYTIC_EXCLUDE = {"СУММА", "ДАТА", "СРОК_ОПЛАТЫ", "КОЛИЧЕСТВО", "ПРОЦЕНТ", "НДС"}
# Слой образцов (решение юриста 2026-10-05): маскируется идентифицирующее (стороны,
# имена, адреса, реквизиты, контакты, номера, даты рождения) и суммы/количества
# (коммерческая тайна); предмет, описания, страны, даты, сроки оплаты, проценты, НДС
# остаются — без них образец теряет смысл.
SAMPLE_EXCLUDE = {"ТЕМА_УСЛУГИ", "ОПИСАНИЕ", "СТРАНА", "ДАТА", "СРОК_ОПЛАТЫ", "ПРОЦЕНТ", "НДС"}
PROFILES = {"full": set(), "analytic": ANALYTIC_EXCLUDE, "sample": SAMPLE_EXCLUDE}


class PrepareError(Exception):
    pass


def to_markdown(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return path.read_text(encoding="utf-8", errors="replace")
    if ext in IMAGE_EXTS:
        if not ocr.available():
            raise PrepareError(
                f"{path.name}: изображению нужен OCR, но Tesseract не найден "
                "(winget install UB-Mannheim.TesseractOCR или PRE_ANON_TESSERACT_CMD)."
            )
        return ocr.ocr_image(path)
    if ext in LEGACY_WORD_EXTS:
        from tools.doc_ingest.router import convert as route_convert
        return route_convert(path)["markdown"]
    from tools.doc_ingest.markitdown_runner import convert
    md = convert(path)["markdown"]
    # Сканированный PDF без текстового слоя → markitdown пуст; пробуем OCR.
    if ext == ".pdf" and len(md.strip()) < PDF_TEXT_LAYER_MIN and ocr.available():
        try:
            ocr_text = ocr.ocr_pdf(path)
        except Exception:
            ocr_text = ""
        if len(ocr_text.strip()) > len(md.strip()):
            return ocr_text
    return md


def prepare(path: Path, profile: str, out_dir: Path | None = None) -> tuple[Path, Path]:
    if profile not in PROFILES:
        raise PrepareError(f"профиль должен быть одним из {sorted(PROFILES)}")
    if not path.exists():
        raise PrepareError(f"файл не найден: {path}")
    out_dir = out_dir or path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    text = to_markdown(path)
    # Guard: не выдавать пустой .anon.md за «успех». Скан без текстового слоя,
    # по которому OCR ничего не дал, или нераспознанное изображение — сюда.
    if len(text.strip()) < MIN_TEXT_CHARS:
        raise PrepareError(
            f"{path.name}: не удалось извлечь текст "
            f"(нет текстового слоя / OCR пуст / формат не поддержан). "
            "Файл не обезличен — нужна проверка (возможно, требуется OCR лучшего качества)."
        )
    a = Anonymizer(exclude_labels=PROFILES[profile])
    masked = a.anonymize(text)

    anon_path = out_dir / f"{path.stem}.anon.md"
    map_path = out_dir / f"{path.stem}.mapping.json"
    anon_path.write_text(masked, encoding="utf-8")
    map_path.write_text(json.dumps({
        "schema_version": 1,
        "source": path.name,
        "profile": profile,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "stats": a.stats(),
        "mapping": restore_reverse(a.mapping()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return anon_path, map_path


def _restore_text(text: str, mapping: dict[str, str]) -> str:
    for ph in sorted(mapping, key=len, reverse=True):
        text = text.replace(ph, mapping[ph])
    for ph in sorted(mapping, key=len, reverse=True):
        bare = ph[1:-1]
        if bare and bare in text:
            text = text.replace(bare, mapping[ph])
    return text


def _restore_docx(path: Path, mapping: dict[str, str], out: Path) -> int:
    import docx  # python-docx
    doc = docx.Document(str(path))
    replaced = 0

    def process_paragraph(p) -> None:
        nonlocal replaced
        if not any(ph in p.text or ph[1:-1] in p.text for ph in mapping):
            return
        # 1) замена внутри отдельных run'ов (сохраняет форматирование)
        for run in p.runs:
            new = _restore_text(run.text, mapping)
            if new != run.text:
                run.text = new
                replaced += 1
        # 2) плейсхолдер разорван между run'ами — пересборка абзаца
        if any(ph in p.text or ph[1:-1] in p.text for ph in mapping):
            full = _restore_text(p.text, mapping)
            if p.runs:
                p.runs[0].text = full
                for run in p.runs[1:]:
                    run.text = ""
                replaced += 1

    for p in doc.paragraphs:
        process_paragraph(p)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    process_paragraph(p)
    for section in doc.sections:
        for part in (section.header, section.footer):
            for p in part.paragraphs:
                process_paragraph(p)
            for table in part.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            process_paragraph(p)
    doc.save(str(out))
    return replaced


def restore(draft: Path, mapping_file: Path, out: Path | None = None) -> Path:
    if not draft.exists():
        raise PrepareError(f"файл не найден: {draft}")
    data = json.loads(mapping_file.read_text(encoding="utf-8"))
    mapping = data.get("mapping") or {}
    if not mapping:
        raise PrepareError(f"пустой mapping в {mapping_file}")
    ext = draft.suffix.lower()
    out = out or draft.with_name(draft.stem + ".restored" + ext)
    if ext == ".docx":
        n = _restore_docx(draft, mapping, out)
    else:
        text = draft.read_text(encoding="utf-8", errors="replace")
        restored = _restore_text(text, mapping)
        n = sum(1 for ph in mapping if ph in text or ph[1:-1] in text)
        out.write_text(restored, encoding="utf-8")
    leftover = [ph for ph in mapping if ph in (out.read_text(encoding="utf-8", errors="replace")
                                               if ext != ".docx" else "")]
    print(f"OK: восстановлено подстановок ≥{n} → {out}"
          + (f" ⚠️ не восстановлены: {leftover}" if leftover else ""))
    return out


# ---------- selftest ----------

def selftest() -> int:
    import tempfile
    ok = 0
    raw = ("Поставщик: ООО «Ромашка Фарм», ИНН 7712345678.\n"
           "Директор Иванов Иван Петрович, тел. +7 (495) 123-45-67.\n"
           "Цена: 1 250 000 руб., оплата в течение 30 календарных дней до 15.08.2026.")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "договор.md"
        src.write_text(raw, encoding="utf-8")

        # full: всё замаскировано
        anon, mp = prepare(src, "full")
        masked = anon.read_text(encoding="utf-8")
        assert "Ромашка" not in masked and "7712345678" not in masked
        assert "Иванов" not in masked and "1 250 000" not in masked
        ok += 1

        # mapping валиден и восстанавливает оригинал
        data = json.loads(mp.read_text(encoding="utf-8"))
        assert data["profile"] == "full" and data["mapping"]
        restored = _restore_text(masked, data["mapping"])
        assert "ООО «Ромашка Фарм»" in restored and "1 250 000 руб." in restored
        ok += 1

        # analytic: суммы и даты открыты, ПДн закрыты
        anon2, _ = prepare(src, "analytic")
        m2 = anon2.read_text(encoding="utf-8")
        assert "1 250 000 руб." in m2 and "15.08.2026" in m2
        assert "Ромашка" not in m2 and "Иванов" not in m2
        ok += 1

        # restore CLI-путь (md)
        draft = Path(td) / "draft.md"
        ph = next(p for p in data["mapping"] if p.startswith("[КОМПАНИЯ"))
        draft.write_text(f"Просим {ph} подтвердить полномочия.", encoding="utf-8")
        out = restore(draft, mp)
        assert "ООО «Ромашка Фарм»" in out.read_text(encoding="utf-8")
        ok += 1

        # restore .docx (если python-docx доступен)
        try:
            import docx
            d = docx.Document()
            d.add_paragraph(f"Просим {ph} подтвердить полномочия.")
            t = d.add_table(rows=1, cols=1)
            t.rows[0].cells[0].text = f"Контрагент: {ph}"
            dpath = Path(td) / "draft.docx"
            d.save(str(dpath))
            outd = restore(dpath, mp)
            d2 = docx.Document(str(outd))
            texts = [p.text for p in d2.paragraphs] + \
                    [c.text for tb in d2.tables for r in tb.rows for c in r.cells]
            assert any("Ромашка Фарм" in x for x in texts), texts
            ok += 1
        except ImportError:
            print("(python-docx не установлен — docx-restore пропущен)")

        # guard: пустой вход (нераспознаваемый) → PrepareError, не пустой .anon.md
        try:
            from PIL import Image
            blank = Path(td) / "blank.png"
            Image.new("RGB", (1000, 300), "white").save(str(blank))
            try:
                prepare(blank, "full")
                raise AssertionError("пустой скан должен падать guard'ом")
            except PrepareError:
                ok += 1
        except ImportError:
            print("(Pillow не установлен — guard-тест на изображении пропущен)")

        # OCR (best-effort): изображение с текстом → распознаётся и маскируется
        import ocr as _ocr
        if _ocr.available():
            try:
                from PIL import Image, ImageDraw, ImageFont
                img = Image.new("RGB", (1000, 140), "white")
                dr = ImageDraw.Draw(img)
                try:
                    font = ImageFont.truetype("arial.ttf", 30)
                except OSError:
                    font = ImageFont.load_default()
                dr.text((15, 20), "ООО «Ромашка Фарм», ИНН 7712345678", fill="black", font=font)
                dr.text((15, 75), "Директор Иванов Иван Петрович", fill="black", font=font)
                ipath = Path(td) / "скан.png"
                img.save(str(ipath))
                anon_i, _ = prepare(ipath, "full")
                mi = anon_i.read_text(encoding="utf-8")
                # OCR может ошибаться в буквах — проверяем сам факт маскирования:
                assert "Иванов" not in mi and "7712345678" not in mi, mi
                assert "[" in mi, "нет плейсхолдеров — OCR/маскирование не сработало"
                ok += 1
            except PrepareError as e:
                print(f"(OCR-тест пропущен: {e})")
        else:
            print("(Tesseract недоступен — OCR-тест пропущен)")
    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("file")
    p.add_argument("--profile", default="full", choices=sorted(PROFILES))
    p.add_argument("--out-dir")

    p = sub.add_parser("restore")
    p.add_argument("file")
    p.add_argument("--mapping", required=True)
    p.add_argument("-o", "--out")

    sub.add_parser("selftest")

    args = ap.parse_args()
    try:
        if args.cmd == "selftest":
            return selftest()
        if args.cmd == "prepare":
            anon, mp = prepare(Path(args.file), args.profile,
                               Path(args.out_dir) if args.out_dir else None)
            print(f"OK: {anon}\n    mapping: {mp}")
            return 0
        restore(Path(args.file), Path(args.mapping),
                Path(args.out) if args.out else None)
        return 0
    except PrepareError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
