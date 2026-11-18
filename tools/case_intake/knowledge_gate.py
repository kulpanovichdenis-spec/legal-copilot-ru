"""Гейт слоя знаний по делу (Stage B, skill matter-knowledge) — единственное место порога.

Используют: bootstrap.py (статус в отчёте раскладки) и tools/watch/queue_cli.py
(нельзя закрыть задачу приёма claims, пока в деле нужен слой знаний, а его нет).
Без зависимостей: модуль подгружается по пути из разных пакетов.
"""
from __future__ import annotations

import json
from pathlib import Path

KNOWLEDGE_MIN_DOCS = 3
INTAKE_DIR = Path("_knowledge") / "intake"
_NOT_DOCS = {"case-context.md", "deadlines.yaml"}
_NOT_DOC_DIRS = {"_knowledge", "_analysis", "Проекты"}


def case_documents(case_dir: Path) -> list[Path]:
    """Документы дела: без служебных файлов, слоя знаний, анализа и проектов."""
    return [p for p in case_dir.rglob("*") if p.is_file()
            and not (set(p.relative_to(case_dir).parts[:-1]) & _NOT_DOC_DIRS)
            and p.name not in _NOT_DOCS and not p.name.startswith(("matter-", "."))]


def knowledge_layer_status(case_dir: Path) -> str:
    """required — документов ≥ KNOWLEDGE_MIN_DOCS и нет _knowledge/index.md;
    present — слой собран; not_needed — документов меньше порога."""
    if (case_dir / "_knowledge" / "index.md").exists():
        return "present"
    return "required" if len(case_documents(case_dir)) >= KNOWLEDGE_MIN_DOCS else "not_needed"


def case_for_queue_ref(workflow_root: Path, queue_ref: str) -> Path | None:
    """Папка дела, куда разложен документ задачи очереди (по полю queue_ref карточки приёма)."""
    want = queue_ref.replace("\\", "/")
    for card in workflow_root.glob(f"*/{INTAKE_DIR.as_posix()}/*.intake.json"):
        try:
            data = json.loads(card.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(data.get("queue_ref", "")).replace("\\", "/") == want:
            return card.parents[2]
    return None


def close_out_block_reason(workflow_root: Path, queue_ref: str) -> str | None:
    """Причина, по которой задачу приёма закрывать нельзя, или None."""
    case = case_for_queue_ref(workflow_root, queue_ref)
    if case is None or knowledge_layer_status(case) != "required":
        return None
    n = len(case_documents(case))
    return (f"в деле «{case.name}» {n} документов, а слоя знаний нет (_knowledge/index.md). "
            f"Сначала skill matter-knowledge, потом закрыть задачу.")


if __name__ == "__main__":
    import sys

    # python tools/case_intake/knowledge_gate.py "workflow/<дело>" → required | present | not_needed
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        raise SystemExit('usage: knowledge_gate.py "workflow/<дело>"')
    print(knowledge_layer_status(Path(sys.argv[1])))
