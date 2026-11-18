from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import run_daemon, run_once
from .paths import RuntimePaths
from .queue import QueueStore
from .registry import build_registry, select_channels
from .selftest import run as run_selftest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Единый watcher каналов приёма, без LLM")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="один проход")
    mode.add_argument("--daemon", action="store_true", help="постоянный polling")
    mode.add_argument("--selftest", action="store_true", help="изолированный smoke-тест")
    parser.add_argument("--channel", action="append", help="ограничить проход каналом")
    parser.add_argument("--interval", type=float, default=15.0, help="интервал daemon, секунд")
    parser.add_argument("--root", type=Path, help="явный корень checkout (для теста/диагностики)")
    parser.add_argument("--profile-root", type=Path, help="явный физический профиль")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return run_selftest()
    runtime = (
        RuntimePaths.for_root(args.root, profile_root=args.profile_root)
        if args.root
        else RuntimePaths.discover()
    )
    specs = select_channels(build_registry(runtime), args.channel)
    queue = QueueStore(runtime.queue_root, repo_root=runtime.repo_root)
    if args.once:
        report = run_once(specs, runtime=runtime, queue=queue)
        print(json.dumps({key: vars(value) for key, value in report.channels.items()}, ensure_ascii=False))
        return 1 if report.errors else 0
    run_daemon(specs, runtime=runtime, queue=queue, interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
