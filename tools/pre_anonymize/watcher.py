#!/usr/bin/env python3
"""Watcher: автоматический pre-LLM конвейер над workflow/_anonymizer/_inbox/.

Все папки конвейера собраны в одном контейнере workflow/_anonymizer/ (решение
юриста 2026-09-08 — чтобы служебные папки не путались с папками дел в корне
workflow/). Юрист кладёт входящий документ в _anonymizer/_inbox/ (или
_anonymizer/_inbox/analytic/ для профиля analytic — суммы/даты остаются
открытыми). Watcher:
  1) ждёт, пока файл дозапишется (стабильный размер между опросами);
  2) конвертирует в Markdown и обезличивает (prepare.py, ядро из v4);
  3) кладёт <имя>.anon.md + <имя>.mapping.json в workflow/_anonymizer/_ready/;
  4) оригинал перемещает в workflow/_anonymizer/_inbox/originals/ (при ошибке — failed/).

Агент по правилу CLAUDE.md работает только с workflow/_anonymizer/_ready/*.anon.md;
оригиналы из _inbox/ и mapping-файлы в LLM не передаются.

Запуск: python tools/pre_anonymize/watcher.py [--once] [--interval N]
        или tools/pre_anonymize/start-watcher.bat (автозапуск — см. README.md).
Лог: workflow/_anonymizer/_inbox/watcher.log.
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import prepare as prep  # noqa: E402

ANON_ROOT = ROOT / "workflow" / "_anonymizer"
INBOX = ANON_ROOT / "_inbox"
READY = ANON_ROOT / "_ready"
ORIGINALS = INBOX / "originals"
FAILED = INBOX / "failed"
ANALYTIC = INBOX / "analytic"
LOG = INBOX / "watcher.log"

from project_layout import SUPPORTED  # noqa: E402  (один список форматов с проектами)
SKIP_PREFIXES = ("~$", ".")
SKIP_SUFFIXES = (".tmp", ".crdownload", ".part", ".anon.md", ".mapping.json")


def log_to(log_path: Path | None, msg: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    if log_path is None:
        return
    print(line)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def log(msg: str) -> None:
    log_to(LOG, msg)


def candidates_for(folder: Path, profile: str) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    if not folder.exists():
        return out
    for p in folder.iterdir():
        if not p.is_file():
            continue
        name = p.name.lower()
        if name.startswith(SKIP_PREFIXES) or name.endswith(SKIP_SUFFIXES):
            continue
        if name == "watcher.log" or p.suffix.lower() not in SUPPORTED:
            continue
        out.append((p, profile))
    return out


def candidates() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for folder, profile in ((INBOX, "full"), (ANALYTIC, "analytic")):
        out.extend(candidates_for(folder, profile))
    return out


def unique_target(folder: Path, name: str) -> Path:
    t = folder / name
    if not t.exists():
        return t
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return folder / f"{Path(name).stem}.{stamp}{Path(name).suffix}"


def stable_size(path: Path, wait: float = 1.0) -> bool:
    try:
        s1 = path.stat().st_size
        time.sleep(wait)
        return path.stat().st_size == s1 and s1 > 0
    except OSError:
        return False


def process_file(
    path: Path,
    profile: str,
    *,
    ready_dir: Path,
    originals_dir: Path,
    failed_dir: Path,
    stable_wait: float = 1.0,
    log_path: Path | None = None,
) -> str:
    for folder in (ready_dir, originals_dir, failed_dir):
        folder.mkdir(parents=True, exist_ok=True)
    if not stable_size(path, wait=stable_wait):
        log_to(log_path, "SKIP (файл ещё пишется)")
        return "waiting"
    try:
        anon, _mapping = prep.prepare(path, profile, ready_dir)
        target = unique_target(originals_dir, path.name)
        shutil.move(str(path), str(target))
        # Автопроверка обезличивания: отчёт (без значений) рядом с .anon.md —
        # агент видит, что проверить глазами до работы с текстом.
        verdict = "n/a"
        try:
            import json
            from quality import quality_report
            report = quality_report(anon.read_text(encoding="utf-8", errors="replace"))
            verdict = report["verdict"]
            anon.with_name(anon.name.replace(".anon.md", ".quality.json")).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        log_to(log_path, f"OK [{profile}]: artifact={anon.name} quality={verdict}")
        return "processed"
    except Exception as exc:
        try:
            shutil.move(str(path), str(unique_target(failed_dir, path.name)))
        except OSError:
            pass
        log_to(log_path, f"FAIL: {type(exc).__name__}")
        return "failed"


def process(path: Path, profile: str) -> None:
    process_file(
        path,
        profile,
        ready_dir=READY,
        originals_dir=ORIGINALS,
        failed_dir=FAILED,
        log_path=LOG,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="один проход и выход")
    ap.add_argument("--interval", type=float, default=3.0)
    args = ap.parse_args()

    for d in (INBOX, READY, ORIGINALS, ANALYTIC):
        d.mkdir(parents=True, exist_ok=True)
    log(f"WATCHER START (inbox={INBOX}, interval={args.interval}s, once={args.once})")

    while True:
        for path, profile in candidates():
            process(path, profile)
        if args.once:
            log("WATCHER DONE (--once)")
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
