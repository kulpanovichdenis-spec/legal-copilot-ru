from __future__ import annotations

import tempfile
from pathlib import Path

from .core import run_once
from .paths import RuntimePaths
from .queue import QueueStore
from .registry import build_registry


def run() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        runtime = RuntimePaths.for_root(Path(temp_dir))
        inputs = {
            runtime.workflow_root / "_anonymizer" / "_inbox" / "anon.txt":
                "ООО Ромашка, ИНН 7712345678",
            runtime.workflow_root / "_anonymizer" / "_inbox" / "analytic" / "analytic.txt":
                "ООО Лютик, сумма 100 000 руб.",
            runtime.workflow_root / "_claims" / "claim.txt":
                "Отзыв по делу № А40-555/2025",
            runtime.profile_root / "knowledge" / "products" / "_inbox" / "product.txt":
                "Инструкция продукта.",
            runtime.profile_root / "knowledge" / "corporate" / "_inbox" / "charter.txt":
                "Устав общества.",
            runtime.profile_root / "knowledge" / "compliance" / "_inbox" / "policy.txt":
                "Политика взаимодействия с медицинскими работниками.",
            runtime.profile_root / "knowledge" / "clauses" / "_inbox" / "clause.txt":
                "ООО Ромашка. Условие о форс-мажоре.",
            runtime.profile_root / "knowledge" / "document-samples" / "_inbox" / "contract.txt":
                "ДОГОВОР ПОСТАВКИ. Поставщик ООО Ромашка.",
            runtime.workflow_root / "_counterparty" / "_inbox" / "extract.txt":
                "ООО Ромашка, ИНН 7712345678.",
        }
        for path, content in inputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        queue = QueueStore(runtime.queue_root, repo_root=runtime.repo_root)
        report = run_once(build_registry(runtime), runtime=runtime, queue=queue, stable_wait=0)
        processed = sum(item.processed for item in report.channels.values())
        pending = queue.cards(status="pending")
        if report.errors or processed != 9 or len(pending) != 7:
            print(
                f"SELFTEST FAIL: errors={report.errors} processed={processed} "
                f"pending={len(pending)}"
            )
            return 1
    print("SELFTEST OK: 9 маршрутов, 7 модельных task-card, DD не подключён")
    return 0
