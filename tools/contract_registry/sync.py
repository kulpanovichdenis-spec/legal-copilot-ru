"""Сверка папки задачи с досье по хешам: какие документы задачи в досье ещё нет."""
from __future__ import annotations

from pathlib import Path

from tools.workflow_layout import TECH_DIR

from .dossier import dossier_dir, load_documents, sha256
from .paths import guard_task

SUFFIXES = (".pdf", ".docx", ".doc", ".rtf", ".txt", ".md")
SKIP_DIRS = {TECH_DIR, "_audit", "_knowledge", "_analysis"}


def _candidates(task_dir: Path):
    for p in sorted(task_dir.rglob("*")):
        # ~$имя.docx: файл блокировки Word, не документ
        if not p.is_file() or p.suffix.lower() not in SUFFIXES or p.name.startswith("~$"):
            continue
        rel = p.relative_to(task_dir).parts
        if SKIP_DIRS & set(rel[:-1]) or p.name == "case-context.md" or p.name.endswith(".txt.md"):
            continue
        yield p


def sync_check(root: Path, key: str, task_dir: Path) -> list[dict]:
    task_dir = guard_task(Path(task_dir), root)
    known = {doc["sha256"] for doc in load_documents(dossier_dir(root, key))}
    out = []
    for p in _candidates(task_dir):
        digest = sha256(p)
        if digest not in known:
            out.append({"path": str(p), "sha256": digest})
    return out
