#!/usr/bin/env python3
"""Перепроверка цитат во всей модели дела: matter-facts, matter-timeline, matter-positions.

Для каждой записи с
`anchor` (факты, события) и для каждой цитаты в `support` позиций заново сверяет цитату с
источником. Решение юриста 2026-10-13: факт или событие со статусом CONFIRMED без
подтверждённой цитаты понижается до REPORTED с записью в status_history.

По умолчанию только показывает, что изменится; `--write` записывает.

Usage:
    python tools/matter_model/anchors.py check --case ПАПКА_ДЕЛА [--write]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.workflow_layout import technical_path  # noqa: E402

import facts  # noqa: E402
import model  # noqa: E402
import positions  # noqa: E402

FILES = {"facts": "matter-facts.yaml", "timeline": "matter-timeline.yaml", "positions": "matter-positions.yaml"}


def _recheck(entry: dict, source_doc: str, base: Path) -> tuple[str, str]:
    old = entry.get("quote_check", "not_checked")
    res = model.evidence_anchor.check(model.evidence_anchor.resolve_doc(source_doc, base),
                                      entry.get("quote", ""), entry.get("location"))
    entry.update({"quote_check": res["quote_check"], "check_detail": res["detail"],
                  "checked_at": res["checked_at"]})
    return old, res["quote_check"]


def check_case(case_dir: str | Path, write: bool = False) -> dict:
    case = Path(case_dir)
    changes: list[str] = []
    downgraded: list[str] = []
    counts: dict[str, int] = {}

    def tally(state: str) -> None:
        counts[state] = counts.get(state, 0) + 1

    def items_with_status(items: list[dict], label: str) -> None:
        for it in items:
            a = it.get("anchor")
            if isinstance(a, dict) and a.get("quote"):
                old, new = _recheck(a, it.get("source_doc", ""), case)
                tally(new)
                if old != new:
                    changes.append(f"{label} {it.get('id')}: {old} → {new}")
            if model.enforce_confirmed(it):
                downgraded.append(f"{label} {it.get('id')}: CONFIRMED → REPORTED")

    loaded: dict[str, tuple[Path, dict]] = {}
    fp = technical_path(case, FILES["facts"])
    if fp.exists():
        data = facts.load(fp)
        items_with_status(data.get("facts", []), "факт")
        loaded["facts"] = (fp, data)
    tp = technical_path(case, FILES["timeline"])
    if tp.exists():
        data = model.load(tp)
        items_with_status(data.get("events", []), "событие")
        loaded["timeline"] = (tp, data)
    pp = technical_path(case, FILES["positions"])
    if pp.exists():
        data = positions.load(pp)
        for pos in data.get("positions", []):
            for n, s in enumerate(pos.get("support") or [], 1):
                old, new = _recheck(s, s.get("source_doc", ""), case)
                tally(new)
                if old != new:
                    changes.append(f"позиция {pos.get('id')}.support[{n}]: {old} → {new}")
            if pos.get("support_state") and positions.effective_state(pos) != pos["support_state"]:
                changes.append(f"позиция {pos.get('id')}: снято support_state={pos['support_state']} "
                               f"(по цитатам — {positions.effective_state({**pos, 'support_state': None})})")
                pos.pop("support_state")
        loaded["positions"] = (pp, data)
    if not loaded:
        raise model.ModelError(f"в {case} нет ни одного файла модели дела ({', '.join(FILES.values())})")
    if write:
        for path, data in loaded.values():
            model.save(path, data)
    return {"files": [str(p.name) for p, _ in loaded.values()], "quote_checks": counts,
            "changes": changes, "downgraded": downgraded, "written": write}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--case", required=True, help="папка дела с matter-*.yaml")
    c.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    try:
        res = check_case(args.case, args.write)
    except model.ModelError as exc:
        print(f"ОШИБКА: {exc}")
        return 1
    print(f"Файлы: {', '.join(res['files'])}")
    print("Цитаты: " + (", ".join(f"{k} {v}" for k, v in sorted(res["quote_checks"].items())) or "нет"))
    for line in res["changes"]:
        print(f"- {line}")
    for line in res["downgraded"]:
        print(f"- {line} ({model.UNANCHORED})")
    if not res["write"] and (res["changes"] or res["downgraded"]):
        print("Не записано: повторить с --write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
