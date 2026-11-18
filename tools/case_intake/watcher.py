#!/usr/bin/env python3
"""Watcher канала приёма: workflow/_claims/ → карточки задач для агента.

Юрист кладёт входящий документ в `workflow/_claims/`. Watcher (класс A —
детерминированная часть, без LLM):
  1) ждёт, пока файл дозапишется (стабильный размер между опросами);
  2) извлекает текст через tools/doc_ingest;
  3) достаёт номера дел regex-ом, подбирает существующую папку дела;
  4) пишет карточку задачи в `workflow/_claims/queue/<файл>.json`; если OCR
     не справился (рукопись, плохой скан), ставит `needs_vision_read` —
     агент дочитает страницы по изображению (`vision_read.py`);
  5) оригинал убирает в `processed/` (ошибка чтения → `failed/`,
     неразбираемый формат → `unsorted/` с пометкой причины).

ВАЖНО — граница возможностей. Классификацию типа документа (класс B) выполняет
субагент `intake-classifier`, а он существует только внутри сессии Claude Code:
Python-процесс сам его вызвать не может. Поэтому watcher доводит работу до
карточки задачи и останавливается, а разбор очереди делает агент в сессии
(по фразе юриста «разбери входящие»). Разделение классов — см.
`references/execution-profiles.md`.

Запуск:
  python tools/case_intake/watcher.py --once        # один проход
  python tools/case_intake/watcher.py --interval 20 # демон, опрос раз в 20 с
  python tools/case_intake/watcher.py --selftest    # проверка на временной папке
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))

import core  # noqa: E402

CHANNEL = ROOT / "workflow" / "_claims"
HEAD_CHARS = 6000          # сколько текста кладём в карточку для классификатора
POLL_STABLE_SECONDS = 2.0  # пауза между замерами размера файла
MIN_SCAN_TEXT_CHARS = 20   # меньше — из PDF/картинки текст фактически не извлечён


def subdirs(channel: Path) -> dict[str, Path]:
    return {
        "queue": channel / "queue",
        "processed": channel / "processed",
        "failed": channel / "failed",
        "unsorted": channel / "unsorted",
    }


def log(channel: Path, msg: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line)
    try:
        with (channel / "watcher.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def is_stable(path: Path, wait: float = POLL_STABLE_SECONDS) -> bool:
    """Файл дозаписан: размер не меняется между двумя замерами."""
    try:
        first = path.stat().st_size
        time.sleep(wait)
        return path.stat().st_size == first
    except OSError:
        return False


def extract_text(path: Path) -> tuple[str, dict]:
    """Текст документа через doc_ingest. Возвращает (текст, метаданные)."""
    try:
        sys.path.insert(0, str(ROOT / "tools" / "doc_ingest"))
        import router  # type: ignore  # noqa: PLC0415

        res = router.convert(path)
        return res.get("markdown") or "", res.get("metadata") or {}
    except Exception as exc:  # noqa: BLE001 — любой сбой ингестии = failed, с причиной
        if path.suffix.lower() in {".txt", ".md"}:
            try:
                return path.read_text(encoding="utf-8", errors="replace"), {"backend": "plain"}
            except OSError:
                pass
        raise RuntimeError(f"ингестия не удалась: {exc}") from exc


def load_case_folders(workflow_root: Path | None = None) -> list[dict]:
    """Карточки существующих дел из frontmatter workflow/<дело>/case-context.md.

    Служебные папки (`_claims`, `_anonymizer` и т. п.) пропускаются — они не дела.
    """
    out: list[dict] = []
    wf = workflow_root or (ROOT / "workflow")
    if not wf.exists():
        return out
    for d in sorted(p for p in wf.iterdir() if p.is_dir() and not p.name.startswith("_")):
        ctx = d / "case-context.md"
        if not ctx.exists():
            out.append({"folder": d.name, "case_number": None, "entities": []})
            continue
        meta = parse_frontmatter(ctx)
        out.append({
            "folder": d.name,
            "case_number": meta.get("case_number"),
            "entities": meta.get("entities") or [],
        })
    return out


def parse_frontmatter(path: Path) -> dict:
    """Минимальный разбор YAML-frontmatter (нужны только case_number и entities)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    _, _, rest = text.partition("---")
    block, sep, _ = rest.partition("\n---")
    if not sep:
        return {}
    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — битый frontmatter не должен ронять конвейер
        return {}


def _ocr_runner():
    """doc_ingest/ocr_runner — единый источник порога доверия и списка форматов-картинок."""
    sys.path.insert(0, str(ROOT / "tools" / "doc_ingest"))
    import ocr_runner  # type: ignore  # noqa: PLC0415

    return ocr_runner


def vision_read_reason(path: Path, text: str, meta: dict) -> str | None:
    """Почему текст скана нужно дочитать моделью по изображению (None — не нужно).

    Tesseract не читает рукопись и плохие сканы: выдаёт мусор с низким доверием.
    Такой текст классификатору бесполезен — агент дочитывает страницы глазами
    модели (skills/case-intake, шаг 1а).
    """
    ocr = _ocr_runner()
    if "ocr" in (meta.get("backend") or "").lower():
        confidence = meta.get("confidence")
        if confidence is None:
            return "OCR без оценки доверия"
        if float(confidence) < ocr.LOW_CONFIDENCE:
            return f"низкое доверие OCR ({float(confidence):.2f} < {ocr.LOW_CONFIDENCE:.2f})"
    is_scan_format = path.suffix.lower() == ".pdf" or path.suffix.lower() in ocr.IMAGE_EXTS
    if is_scan_format and len(text.strip()) < MIN_SCAN_TEXT_CHARS:
        return "из скана почти не извлечён текст"
    return None


def build_card(path: Path, text: str, meta: dict, folders: list[dict]) -> dict:
    """Карточка задачи: всё, что удалось установить кодом, + что осталось агенту."""
    numbers = core.extract_case_numbers(text)
    folder = core.find_case_folder(folders, case_numbers=numbers, parties=[])
    reason = vision_read_reason(path, text, meta)
    return {
        "source_file": path.name,
        "detected_at": dt.datetime.now().isoformat(timespec="seconds"),
        "ingest_backend": meta.get("backend"),
        "ocr_confidence": meta.get("confidence"),
        # Мусорный OCR дочитывает агент по изображению страниц (шаг 1а case-intake):
        "needs_vision_read": reason is not None,
        "vision_read_reason": reason,
        "case_numbers": numbers,
        "matched_case_folder": folder,
        "text_head": text[:HEAD_CHARS],
        "text_truncated": len(text) > HEAD_CHARS,
        # Заполняет агент через субагента intake-classifier (класс B):
        "needs_classification": True,
        "classification": None,
        "status": "pending",
    }


def rel_to_root(path: Path, root: Path = ROOT) -> str:
    """Путь относительно корня проекта; если файл вне корня (selftest) — абсолютный."""
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def move_aside(path: Path, target_dir: Path, reason: str | None = None) -> Path:
    """Переместить файл, не затирая существующий; при наличии причины — положить .reason.txt."""
    target_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in target_dir.iterdir()} if target_dir.exists() else set()
    dest = target_dir / core.unique_name(path.name, existing)
    shutil.move(str(path), str(dest))
    if reason:
        dest.with_suffix(dest.suffix + ".reason.txt").write_text(
            f"{reason}\n", encoding="utf-8")
    return dest


def _atomic_card(path: Path, card: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(card, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink()
        except FileNotFoundError:
            pass


def process_once(
    channel: Path = CHANNEL,
    *,
    verbose: bool = True,
    files: list[Path] | None = None,
    stable_wait: float = POLL_STABLE_SECONDS,
    workflow_root: Path | None = None,
    repo_root: Path = ROOT,
) -> dict:
    """Один проход по каналу. Возвращает счётчики для тестов и лога."""
    dirs = subdirs(channel)
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    stats = {
        "queued": 0,
        "failed": 0,
        "unsorted": 0,
        "waiting": 0,
        "notified": 0,
        "cards": [],
    }
    if not channel.exists():
        return stats

    folders = load_case_folders(workflow_root)
    candidates = files if files is not None else [p for p in channel.iterdir() if p.is_file()]
    for path in sorted(candidates):
        if path.name == "watcher.log" or path.name == ".gitkeep":
            continue

        reason = core.skip_reason(path)
        if reason:
            action = core.skip_action(reason)
            if action == "ignore":
                continue
            if action == "retry":
                stats["waiting"] += 1
                continue
            if action == "notify":
                stats["notified"] += 1
                if verbose:
                    log(channel, f"[открыт в Word] {path.name} — закройте документ, "
                                 f"чтобы конвейер его забрал (сам lock-файл текста не содержит)")
                continue
            move_aside(path, dirs["unsorted"], f"Формат не разбирается конвейером ({reason}).")
            stats["unsorted"] += 1
            if verbose:
                log(channel, f"[unsorted] {path.name} — {reason}")
            continue

        if not is_stable(path, wait=stable_wait):
            stats["waiting"] += 1
            continue

        try:
            text, meta = extract_text(path)
        except RuntimeError as exc:
            move_aside(path, dirs["failed"], str(exc))
            stats["failed"] += 1
            if verbose:
                log(channel, f"[failed] {path.name} — {exc}")
            continue

        card = build_card(path, text, meta, folders)
        moved = move_aside(path, dirs["processed"])
        card["processed_path"] = rel_to_root(moved, root=repo_root)
        card_path = dirs["queue"] / f"{moved.stem}.json"
        _atomic_card(card_path, card)
        stats["cards"].append(str(card_path))
        stats["queued"] += 1
        if verbose:
            hint = card["matched_case_folder"] or "дело не определено"
            vision = (f"; OCR не справился ({card['vision_read_reason']}) — дочитает агент"
                      if card["needs_vision_read"] else "")
            log(channel, f"[в очередь] {path.name} → {hint}; "
                         f"номера дел: {', '.join(card['case_numbers']) or '—'}{vision}")
    return stats


def selftest() -> int:
    """Интеграционная проверка на временной папке (без сети и без LLM)."""
    with tempfile.TemporaryDirectory() as tmp:
        ch = Path(tmp) / "_claims"
        ch.mkdir()
        # в имени файла слэша быть не может — номер дела берётся из текста
        (ch / "Отзыв по делу.txt").write_text(
            "Отзыв на исковое заявление по делу № А40-555/2025", encoding="utf-8")
        (ch / "~$Отзыв.docx").write_bytes(b"\x00" * 160)          # lock — уведомить
        (ch / "Схема.dwg").write_bytes(b"\x00" * 10)               # формат не наш
        (ch / "Акт.pdf.crdownload").write_bytes(b"\x00" * 10)      # ещё качается

        stats = process_once(ch, verbose=False)
        problems: list[str] = []
        if stats["queued"] != 1:
            problems.append(f"ожидался 1 файл в очереди, получено {stats['queued']}")
        if stats["notified"] != 1:
            problems.append(f"ожидалось 1 уведомление о lock-файле, получено {stats['notified']}")
        if stats["unsorted"] != 1:
            problems.append(f"ожидался 1 файл в unsorted, получено {stats['unsorted']}")
        if stats["waiting"] != 1:
            problems.append(f"ожидался 1 файл в ожидании дозагрузки, получено {stats['waiting']}")

        cards = list((ch / "queue").glob("*.json"))
        if len(cards) != 1:
            problems.append(f"ожидалась 1 карточка задачи, найдено {len(cards)}")
        else:
            card = json.loads(cards[0].read_text(encoding="utf-8"))
            if card["case_numbers"] != ["А40-555/2025"]:
                problems.append(f"номер дела не извлечён: {card['case_numbers']}")
            if not card["needs_classification"]:
                problems.append("карточка должна требовать классификации (класс B)")
        if not (ch / "processed").glob("*"):
            problems.append("оригинал не перемещён в processed/")
        # lock-файл и недокачанный остаются на месте — их трогать нельзя
        if not (ch / "~$Отзыв.docx").exists():
            problems.append("lock-файл не должен перемещаться")
        if not (ch / "Акт.pdf.crdownload").exists():
            problems.append("недокачанный файл не должен перемещаться")

        if problems:
            print("SELFTEST FAIL:")
            for p in problems:
                print("  - " + p)
            return 1
    print("SELFTEST OK: проход канала отработал корректно")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Watcher канала приёма workflow/_claims/")
    ap.add_argument("--once", action="store_true", help="один проход и выход")
    ap.add_argument("--interval", type=float, default=15.0, help="интервал опроса, секунд")
    ap.add_argument("--selftest", action="store_true", help="проверка на временной папке")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    CHANNEL.mkdir(parents=True, exist_ok=True)
    if args.once:
        stats = process_once()
        log(CHANNEL, f"проход завершён: {stats}")
        return 0

    log(CHANNEL, f"watcher запущен, опрос раз в {args.interval:g} с. Ctrl+C — остановить.")
    try:
        while True:
            process_once()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log(CHANNEL, "watcher остановлен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
