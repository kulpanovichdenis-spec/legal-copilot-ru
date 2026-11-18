from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from .paths import RuntimePaths
from .queue import QueueStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Просмотр и статусы единой очереди watcher")
    parser.add_argument("--root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--status", default="pending")
    listing.add_argument("--json", action="store_true")
    show = sub.add_parser("show")
    show.add_argument("task_id")
    for name in ("claim", "complete", "block", "fail"):
        command = sub.add_parser(name)
        command.add_argument("task_id")
        command.add_argument("--note")
        if name == "complete":
            command.add_argument(
                "--skip-knowledge-gate", metavar="ПРИЧИНА",
                help="закрыть задачу приёма claims без слоя знаний по делу (причина пишется в задачу)")
    return parser


def _knowledge_gate(runtime: RuntimePaths):
    """tools/case_intake/knowledge_gate.py — единственный источник порога слоя знаний."""
    path = runtime.repo_root / "tools" / "case_intake" / "knowledge_gate.py"
    spec = importlib.util.spec_from_file_location("knowledge_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def close_out_block(runtime: RuntimePaths, queue_root: Path, task_id: str) -> str | None:
    """Причина не закрывать задачу приёма claims: дело разложено, слой знаний нужен, его нет."""
    path = queue_root / f"{task_id}.json"
    if not path.exists():
        return None
    task = json.loads(path.read_text(encoding="utf-8"))
    if task.get("channel") != "claims":
        return None
    return _knowledge_gate(runtime).close_out_block_reason(runtime.workflow_root, task.get("task_ref", ""))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = RuntimePaths.for_root(args.root) if args.root else RuntimePaths.discover()
    queue = QueueStore(runtime.queue_root, repo_root=runtime.repo_root)
    if args.command == "list":
        cards = queue.cards(status=args.status)
        if args.json:
            print(json.dumps(cards, ensure_ascii=False, indent=2))
        else:
            counts: dict[str, int] = {}
            for card in cards:
                channel = str(card.get("channel") or "unknown")
                counts[channel] = counts.get(channel, 0) + 1
            detail = ", ".join(f"{key}: {counts[key]}" for key in sorted(counts))
            print(
                f"Очередь: {len(cards)} со статусом {args.status}"
                + (f" ({detail})." if detail else ".")
            )
            for card in cards:
                print(
                    f"{card['task_id']}  {card['channel']}  {card['task_type']}  "
                    f"{card['task_ref']}"
                )
        return 0
    if args.command == "show":
        path = runtime.queue_root / f"{args.task_id}.json"
        if not path.exists():
            raise SystemExit(f"task не найден: {args.task_id}")
        print(path.read_text(encoding="utf-8"))
        return 0
    status = {
        "claim": "in_progress",
        "complete": "completed",
        "block": "blocked",
        "fail": "failed",
    }[args.command]
    note = args.note
    if args.command == "complete":
        reason = close_out_block(runtime, runtime.queue_root, args.task_id)
        if reason and not args.skip_knowledge_gate:
            print(f"НЕ ЗАКРЫТО: {reason} Обойти можно только с --skip-knowledge-gate \"причина\".")
            return 2
        if reason:
            note = f"{note + '; ' if note else ''}слой знаний пропущен: {args.skip_knowledge_gate}"
    print(json.dumps(queue.set_status(args.task_id, status, note=note), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
