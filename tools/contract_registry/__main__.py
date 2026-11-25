"""CLI реестра договоров: python -m tools.contract_registry <команда> [--root PATH]."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from . import amendments, card, dossier, links, registry, relations, rename, sync  # noqa: E402
from .paths import RegistryError, default_root  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _entry(root: Path, key: str) -> dict:
    entry = registry.find_entry(registry.load(root), key)
    if not entry:
        raise RegistryError(f"досье {key} в реестре нет")
    return entry


def _validate(root: Path, key: str, rel: tuple[list[str], list[str]] | None = None) -> list[str]:
    entry = _entry(root, key)
    d = Path(root) / entry["folder"]
    rel_errs = (rel or relations.validate(root, key))[0]
    errs = card.validate_card(d / "contract-card.md", key=entry["key"]) + amendments.validate(root, key) + rel_errs
    p = subprocess.run([sys.executable, str(REPO / "tools" / "matter_model" / "model.py"), "validate",
                        "--file", str(d / "matter-timeline.yaml")], capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        errs.append(f"matter-timeline: {p.stdout.strip()} {p.stderr.strip()}")
    return errs


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m tools.contract_registry")
    ap.add_argument("--root", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lookup"); p.add_argument("query")
    p = sub.add_parser("init")
    p.add_argument("--key", required=True); p.add_argument("--counterparty", required=True)
    p.add_argument("--inn", default=""); p.add_argument("--alias", action="append", default=[])
    p.add_argument("--temporary", action="store_true")
    p = sub.add_parser("add-doc")
    p.add_argument("--key", required=True); p.add_argument("--file", required=True, type=Path)
    p.add_argument("--kind", required=True); p.add_argument("--status", required=True)
    p.add_argument("--evidence", default=""); p.add_argument("--date", default="")
    p = sub.add_parser("set-doc-status")
    p.add_argument("--key", required=True); p.add_argument("--doc", required=True)
    p.add_argument("--status", required=True, choices=dossier.STATUSES); p.add_argument("--evidence", default="")
    p = sub.add_parser("sync-check"); p.add_argument("--key", required=True); p.add_argument("--task", required=True, type=Path)
    p = sub.add_parser("rename-key"); p.add_argument("--old", required=True); p.add_argument("--new", required=True)
    p = sub.add_parser("link-task"); p.add_argument("--key", required=True); p.add_argument("--task", required=True, type=Path)
    p = sub.add_parser("add-draft")
    p.add_argument("--key", required=True); p.add_argument("--task", required=True); p.add_argument("--file", required=True)
    p = sub.add_parser("add-conflict")
    for a in ("--key", "--field", "--dossier-value", "--new-value", "--source"):
        p.add_argument(a, required=True)
    for name in ("amend-clause", "amend-change"):
        p = sub.add_parser(name)
        for a in ("--key", "--clause", "--doc", "--quote", "--location"):
            p.add_argument(a, required=True)
        if name == "amend-change":
            p.add_argument("--date", default="")
    p = sub.add_parser("link-doc")
    p.add_argument("--key", required=True); p.add_argument("--doc", required=True)
    p.add_argument("--type", required=True, choices=relations.TYPES); p.add_argument("--target", required=True)
    p.add_argument("--quote", required=True)
    p = sub.add_parser("unlink-doc")
    p.add_argument("--key", required=True); p.add_argument("--doc", required=True)
    p.add_argument("--type", required=True, choices=relations.TYPES); p.add_argument("--target", required=True)
    p = sub.add_parser("chain"); p.add_argument("--key", required=True)
    p = sub.add_parser("current"); p.add_argument("--key", required=True)
    p = sub.add_parser("validate"); p.add_argument("--key", required=True)
    p = sub.add_parser("summary"); p.add_argument("--key", required=True)
    p = sub.add_parser("set-card-status"); p.add_argument("--key", required=True)
    p.add_argument("--status", required=True, choices=card.CARD_STATUSES)
    return ap


def run(argv: list[str]) -> int:
    a = build_parser().parse_args(argv)
    root = a.root or default_root()
    try:
        if a.cmd == "lookup":
            _out(registry.lookup(root, a.query))
        elif a.cmd == "init":
            _out({"dossier": str(dossier.init(root, a.key, a.counterparty, inn=a.inn,
                                              aliases=a.alias, temporary=a.temporary))})
        elif a.cmd == "add-doc":
            _out(dossier.add_doc(root, a.key, a.file, kind=a.kind, status=a.status, evidence=a.evidence, date=a.date))
        elif a.cmd == "set-doc-status":
            _out(dossier.set_doc_status(root, a.key, a.doc, a.status, a.evidence))
        elif a.cmd == "sync-check":
            _out(sync.sync_check(root, a.key, a.task))
        elif a.cmd == "rename-key":
            _out({"dossier": str(rename.rename_key(root, a.old, a.new))})
        elif a.cmd == "link-task":
            _out(links.link_task(root, a.key, a.task))
        elif a.cmd == "add-draft":
            links.add_draft(root, a.key, task=a.task, file=a.file); _out({"ok": True})
        elif a.cmd == "add-conflict":
            _out(links.add_conflict(root, a.key, field=a.field, dossier_value=a.dossier_value,
                                    new_value=a.new_value, source=a.source))
        elif a.cmd == "amend-clause":
            _out(amendments.add_clause(root, a.key, clause=a.clause, doc_id=a.doc, quote=a.quote, location=a.location))
        elif a.cmd == "amend-change":
            _out(amendments.add_change(root, a.key, clause=a.clause, doc_id=a.doc, quote=a.quote,
                                       location=a.location, date=a.date))
        elif a.cmd == "link-doc":
            _out(relations.link_doc(root, a.key, doc=a.doc, type=a.type, target=a.target, quote=a.quote))
        elif a.cmd == "unlink-doc":
            _out(relations.unlink_doc(root, a.key, doc=a.doc, type=a.type, target=a.target))
        elif a.cmd == "chain":
            _out(relations.chain(root, a.key))
        elif a.cmd == "current":
            _out(amendments.current(root, a.key))
        elif a.cmd == "validate":
            rel = relations.validate(root, a.key)  # один проход: ошибки и предупреждения связей
            errs = _validate(root, a.key, rel)
            # Предупреждения (несвязанный ДС, приложение без annex_to) на код выхода не влияют.
            _out({"errors": errs, "warnings": rel[1]})
            return 1 if errs else 0
        elif a.cmd == "summary":
            _out(card.summary(dossier.dossier_dir(root, a.key)))
        elif a.cmd == "set-card-status":
            entry = _entry(root, a.key)
            extra = _validate(root, a.key) if a.status == "reviewed" else []
            _out(card.set_card_status(Path(root) / entry["folder"] / "contract-card.md", a.status,
                                      key=entry["key"], extra_errors=extra))
    except RegistryError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
