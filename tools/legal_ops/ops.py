#!/usr/bin/env python3
"""CLI for legal-ops project state and calculators.

    python tools/legal_ops/ops.py init --folder PATH --name NAME
    python tools/legal_ops/ops.py validate --folder PATH
    python tools/legal_ops/ops.py decide --folder PATH --date YYYY-MM-DD --decision TEXT
    python tools/legal_ops/ops.py capacity --volume N --minutes N
    python tools/legal_ops/ops.py roi [--hours-saved N] [--rate N] [--cost N]
        [--cycle-before N] [--cycle-after N]
    python tools/legal_ops/ops.py compare --baseline PATH --actual PATH
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import yaml  # noqa: E402

from capacity import CalcGap, capacity_hours, fte  # noqa: E402
from compare_baseline import compare_baseline  # noqa: E402
from roi import roi_summary  # noqa: E402
from state import (  # noqa: E402
    StateError,
    init_project,
    record_decision,
    update_state,
    validate_process_card,
    validate_project,
)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _dec(text: str | None):
    if text is None:
        return None
    token = str(text).strip()
    if not token or token.upper() == "UNKNOWN":
        raise CalcGap(token or "value")
    try:
        number = Decimal(token)
    except Exception as exc:
        raise CalcGap(token) from exc
    if not number.is_finite():
        raise CalcGap(token)
    return number


def cmd_init(args: argparse.Namespace) -> int:
    path = init_project(Path(args.folder), args.name)
    print(path)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    issues = validate_project(folder)
    card_path = Path(args.card) if args.card else None
    if card_path:
        card = yaml.safe_load(card_path.read_text(encoding="utf-8"))
        issues.extend(validate_process_card(card))
    errors = [item for item in issues if item.level == "error"]
    for item in issues:
        print(f"{item.level}\t{item.code}\t{item.where}\t{item.message}")
    if not issues:
        print("PASS")
    return 1 if errors else 0


def cmd_decide(args: argparse.Namespace) -> int:
    decision_id = record_decision(
        Path(args.folder),
        {
            "date": args.date,
            "decision": args.decision,
            "owner": args.owner,
            "status": args.status or "confirmed",
            "problem": args.problem,
            "evidence": args.evidence,
            "assumptions": args.assumptions,
            "alternatives": args.alternatives,
            "selected": args.selected,
            "why": args.why,
            "risks": args.risks,
            "controls": args.controls,
            "reconsideration_trigger": args.reconsideration_trigger,
        },
    )
    print(decision_id)
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    update_state(
        Path(args.folder),
        phase=args.phase,
        track=args.track,
        objective=args.objective,
        fact=args.fact,
        assumption=args.assumption,
        question=args.question,
        related_budget_run=args.related_budget_run,
        artifact_ref=args.artifact_ref,
        completed=args.completed,
        active_process=args.active_process,
        next_action=args.next_action,
        blocked_by=args.blocked_by,
        human_control=args.human_control,
        decision_id=args.decision_id,
    )
    print("PASS")
    return 0


def cmd_capacity(args: argparse.Namespace) -> int:
    hours = capacity_hours(args.volume, args.minutes)
    print(f"hours\t{hours}")
    if args.hours_per_fte is not None:
        print(f"fte\t{fte(hours, args.hours_per_fte)}")
    return 0


def cmd_roi(args: argparse.Namespace) -> int:
    summary = roi_summary(
        {
            "hours_saved": _dec(args.hours_saved),
            "rate": _dec(args.rate),
            "cost": _dec(args.cost),
            "cycle_time_before": _dec(args.cycle_before),
            "cycle_time_after": _dec(args.cycle_after),
        }
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    baseline = yaml.safe_load(Path(args.baseline).read_text(encoding="utf-8")) or {}
    actual = yaml.safe_load(Path(args.actual).read_text(encoding="utf-8")) or {}
    print(json.dumps(compare_baseline(baseline, actual), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Legal Ops project state and calculators")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--folder", required=True)
    init.add_argument("--name", required=True)
    init.set_defaults(func=cmd_init)

    validate = sub.add_parser("validate")
    validate.add_argument("--folder", required=True)
    validate.add_argument("--card")
    validate.set_defaults(func=cmd_validate)

    decide = sub.add_parser("decide")
    decide.add_argument("--folder", required=True)
    decide.add_argument("--date", required=True)
    decide.add_argument("--decision", required=True)
    decide.add_argument("--owner", default="")
    decide.add_argument("--status", default="confirmed")
    decide.add_argument("--problem", default="")
    decide.add_argument("--evidence", default="")
    decide.add_argument("--assumptions", default="")
    decide.add_argument("--alternatives", default="")
    decide.add_argument("--selected", default="")
    decide.add_argument("--why", default="")
    decide.add_argument("--risks", default="")
    decide.add_argument("--controls", default="")
    decide.add_argument("--reconsideration-trigger", default="")
    decide.set_defaults(func=cmd_decide)

    setter = sub.add_parser("set")
    setter.add_argument("--folder", required=True)
    setter.add_argument("--phase")
    setter.add_argument("--track")
    setter.add_argument("--objective")
    setter.add_argument("--fact")
    setter.add_argument("--assumption")
    setter.add_argument("--question")
    setter.add_argument("--related-budget-run")
    setter.add_argument("--artifact-ref")
    setter.add_argument("--completed")
    setter.add_argument("--active-process")
    setter.add_argument("--next-action")
    setter.add_argument("--blocked-by")
    setter.add_argument("--human-control")
    setter.add_argument("--decision-id")
    setter.set_defaults(func=cmd_set)

    capacity = sub.add_parser("capacity")
    capacity.add_argument("--volume", required=True)
    capacity.add_argument("--minutes", required=True)
    capacity.add_argument("--hours-per-fte")
    capacity.set_defaults(func=cmd_capacity)

    roi = sub.add_parser("roi")
    roi.add_argument("--hours-saved")
    roi.add_argument("--rate")
    roi.add_argument("--cost")
    roi.add_argument("--cycle-before")
    roi.add_argument("--cycle-after")
    roi.set_defaults(func=cmd_roi)

    compare = sub.add_parser("compare")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--actual", required=True)
    compare.set_defaults(func=cmd_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (StateError, CalcGap) as exc:
        print(f"ERROR\t{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
