from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.watch.paths import RuntimePaths  # noqa: E402
from tools.watch.queue import QueueStore  # noqa: E402


def main() -> int:
    # На Windows stdout в пайп хука идёт в cp1251, а Claude Code читает UTF-8:
    # сводка приходила кракозябрами и терялась для агента.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    runtime = RuntimePaths.discover()
    summary = QueueStore(runtime.queue_root, repo_root=runtime.repo_root).session_summary()
    if summary:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
