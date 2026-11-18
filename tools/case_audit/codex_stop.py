"""Codex Stop hook: backfill completed turn usage into explicitly bound cases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.case_audit.ledger import CODEX_ID_RE, import_codex_turn  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id", required=True)
    args = parser.parse_args()
    if not CODEX_ID_RE.fullmatch(args.session_id) or not CODEX_ID_RE.fullmatch(args.turn_id):
        return 0
    binding = ROOT / "workflow" / "_case_audit_bindings" / args.session_id / f"{args.turn_id}.jsonl"
    if not binding.exists():
        return 0
    failures = []
    for line in binding.read_text(encoding="utf-8").splitlines():
        try:
            relative = json.loads(line)["case"]
            task = (ROOT / "workflow" / relative).resolve()
            if not task.is_relative_to((ROOT / "workflow").resolve()):
                raise ValueError("case вне workflow")
            import_codex_turn(task, args.session_id, args.turn_id)
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            failures.append(str(exc))
    if failures:
        print("case-audit: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
