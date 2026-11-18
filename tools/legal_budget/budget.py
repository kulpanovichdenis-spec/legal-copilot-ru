#!/usr/bin/env python3
"""CLI for a legal budget run.

    python tools/legal_budget/budget.py init --folder PATH --run-id ID --goal create
    python tools/legal_budget/budget.py demo
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lb_local import load  # noqa: E402

capability_flags = load("capability").capability_flags
_finance = load("finance_template")
apply_finance_card = _finance.apply_finance_card
parse_finance_template = _finance.parse_finance_template
challenge = load("challenge").challenge
_model = load("model")
BudgetError = _model.BudgetError
CalcGap = _model.CalcGap
STAGE_STATUSES = _model.STAGE_STATUSES
annual_amount = load("calculate").annual_amount
import_table = load("import_tabular").import_table
normalize_actuals = load("normalize").normalize_actuals
log_entry = _model.log_entry
money = _model.money
D = _model.D
quality_gate = load("quality").quality_gate
reconcile = load("reconcile").reconcile
reforecast_view = load("reforecast").reforecast_view
render_html = load("render_html").render_html
_scenarios = load("scenarios")
apply_scenario = _scenarios.apply_scenario
make_vs_buy = _scenarios.make_vs_buy
plan_cut = _scenarios.plan_cut
_state = load("state")
append_log = _state.append_log
init_run = _state.init_run
load_json = _state.load_json
save_json = _state.save_json
build_view_model = load("view_model").build_view_model
write_workbook = load("workbook").write_workbook
from docx import Document  # noqa: E402
from docx.shared import Pt  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def write_cfo_note(view: dict, path: Path) -> None:
    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    document.add_paragraph("ЧЕРНОВИК — требует проверки юристом")
    document.add_heading("Записка по бюджету юридической функции", level=1)
    document.add_paragraph(
        f"Запрашиваемый бюджет: {view.get('total')} {view.get('currency') or ''}. "
        "Цифры взяты из view model, отдельно не пересчитывались."
    )
    if view.get("bridge_total"):
        document.add_paragraph(f"Итог моста от прошлого периода: {view.get('bridge_total')} {view.get('currency') or ''}.")
    document.add_paragraph("Главные драйверы, обязательные статьи и решения — только из строк этого запуска.")
    if view.get("scenario_saving"):
        document.add_paragraph(
            f"Сценарий сокращения через отдельные рычаги: {view['scenario_saving']} {view.get('currency') or ''}. "
            "Равномерная стрижка всех строк не применялась."
        )
    for item in view.get("findings") or []:
        document.add_paragraph(f"{item.get('id')} {item.get('rule')}: {item.get('finding')}")
    for item in view.get("assumptions") or []:
        text = item.get("statement") if isinstance(item, dict) else item
        document.add_paragraph(f"Допущение: {text}")
    for item in view.get("open_issues") or []:
        text = item.get("question") if isinstance(item, dict) else item
        document.add_paragraph(f"Открытый вопрос: {text}")
    if view.get("total_complete") is False:
        document.add_paragraph("Итог неполный: есть строки без суммы. Пустая сумма не заменена нулём.")
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)


def render_pack(folder: Path) -> dict:
    folder = Path(folder)
    bundle = {
        "context": load_json(folder / "state" / "budget_context.json"),
        "state": load_json(folder / "state" / "budget_state.json"),
        "assumptions": load_json(folder / "state" / "assumptions.json"),
        "open_issues": load_json(folder / "state" / "open_issues.json"),
    }
    findings = [item.as_dict() for item in challenge(bundle["state"], bundle["context"])]
    bundle["findings"] = findings
    view = build_view_model(bundle)
    save_json(folder / "state" / "view_model.json", view)
    write_workbook(view, folder / "output" / "legal_budget_workbook.xlsx")
    render_html(view, folder / "output" / "legal_budget_review.html")
    write_cfo_note(view, folder / "output" / "cfo_budget_note.docx")
    issues = reconcile(
        view,
        folder / "output" / "legal_budget_workbook.xlsx",
        folder / "output" / "legal_budget_review.html",
        folder / "output" / "cfo_budget_note.docx",
    )
    flags = capability_flags()
    meta = {
        "visual_qa_performed": False,
        "reason": "browser capability не подтверждался в этом запуске",
        "reconcile_errors": [item.message for item in issues],
        "capabilities": flags,
        "ready_for_submission": False,
    }
    save_json(folder / "output" / "render_meta.json", meta)
    append_log(folder, log_entry("view_total", {"lines": len(view["lines"])}, view["total"], view.get("currency") or "RUB"))
    return {"findings": findings, "view": view, "issues": [item.message for item in issues]}


def demo(folder: Path | None = None) -> Path:
    folder = Path(folder) if folder is not None else Path(tempfile.mkdtemp(prefix="legal-budget-demo-"))
    init_run(folder, "2026-09-24_budget_2027_001", "create")
    context = load_json(folder / "state" / "budget_context.json")
    context.update(
        {
            "reporting_currency": "RUB",
            "budget_period": {"start": "2027-01-01", "end": "2027-12-31"},
            "industry": "synthetic",
            "materiality_threshold": "1000.00",
        }
    )
    save_json(folder / "state" / "budget_context.json", context)
    state = load_json(folder / "state" / "budget_state.json")
    state["lines"] = [
        {
            "id": "BL-1",
            "category": "подписки",
            "description": "учебная подписка",
            "owner": "legal",
            "monthly_amounts": {f"2027-{month:02d}": "100.00" for month in range(1, 13)},
            "annual_amount": "999.00",
            "source_refs": ["SRC-1"],
            "assumption_refs": [],
            "material": True,
        },
        {
            "id": "BL-2",
            "category": "споры",
            "description": "учебное дело",
            "owner": "legal",
            "monthly_amounts": {f"2027-{month:02d}": "50.00" for month in range(1, 13)},
            "source_refs": [],
            "assumption_refs": ["A-1"],
            "material": True,
        },
    ]
    state["actuals"] = [{"invoice_id": "INV-1", "amount": "10"}]
    state["accruals"] = [{"invoice_id": "INV-1", "amount": "10"}]
    save_json(folder / "state" / "budget_state.json", state)
    before = render_pack(folder)
    rules = {item["rule"] for item in before["findings"]}
    if "annual_mismatch" not in rules or "accrual_double_count" not in rules:
        raise BudgetError("демо не поймало заложенные ошибки")
    state = load_json(folder / "state" / "budget_state.json")
    state["lines"][0]["annual_amount"] = money(
        sum((D(value) for value in state["lines"][0]["monthly_amounts"].values()), D("0"))
    )
    state["accruals"] = []
    state["bridge"] = {
        "prior": "1800.00",
        "ceased": "0",
        "price": "0",
        "volume": "0",
        "new_demand": "0",
        "headcount": "0",
        "fx": "0",
    }
    overlay = apply_scenario(
        state,
        [
            {
                "type": "defer",
                "classification": "deferrable",
                "line_id": "BL-2",
                "saving": "60.00",
                "consequence": "часть учебного спора сдвигается на следующий период",
                "owner": "руководитель Legal",
                "confidence": "medium",
            }
        ],
    )
    state["scenario_overlay"] = overlay["scenario_overlay"]
    save_json(folder / "state" / "budget_state.json", state)
    save_json(
        folder / "state" / "assumptions.json",
        [{"id": "A-1", "statement": "учебная оценка открытого дела", "confidence": "low"}],
    )
    after = render_pack(folder)
    if after["issues"]:
        raise BudgetError("; ".join(after["issues"]))
    if any(item["rule"] == "annual_mismatch" for item in after["findings"]):
        raise BudgetError("годовая сумма не исправилась")
    print(folder)
    print(json.dumps({"total": after["view"]["total"], "saving": after["view"]["scenario_saving"]}, ensure_ascii=False))
    return folder


def reforecast_demo(folder: Path | None = None) -> Path:
    folder = Path(folder) if folder is not None else Path(tempfile.mkdtemp(prefix="legal-budget-reforecast-"))
    init_run(folder, "2026-09-24_reforecast_001", "reforecast")
    context = load_json(folder / "state" / "budget_context.json")
    context.update(
        {
            "reporting_currency": "RUB",
            "budget_period": {"start": "2027-01-01", "end": "2027-12-31"},
            "industry": "synthetic",
        }
    )
    save_json(folder / "state" / "budget_context.json", context)
    state = load_json(folder / "state" / "budget_state.json")
    state["lines"] = [
        {
            "id": "BL-APP",
            "category": "утверждённый бюджет",
            "owner": "legal",
            "monthly_amounts": {f"2027-{month:02d}": "100.00" for month in range(1, 13)},
            "source_refs": ["SRC-APPROVED"],
            "assumption_refs": [],
            "material": True,
        }
    ]
    state["actuals"] = [{"invoice_id": "INV-PAID", "amount": "500.00"}]
    state["accruals"] = [{"invoice_id": "INV-OPEN", "amount": "50.00"}]
    save_json(folder / "state" / "budget_state.json", state)
    pack = render_pack(folder)
    view = pack["view"]
    view["reforecast"] = reforecast_view(
        approved_total=view["total"],
        phased_to_date="600.00",
        actual_total="500.00",
        accrual_total="50.00",
        etc_total="700.00",
        actual_invoices=["INV-PAID"],
        accrual_invoices=["INV-OPEN"],
    )
    save_json(folder / "state" / "view_model.json", view)
    render_html(view, folder / "output" / "legal_budget_review.html")
    write_workbook(view, folder / "output" / "legal_budget_workbook.xlsx")
    html = (folder / "output" / "legal_budget_review.html").read_text(encoding="utf-8")
    if 'data-eac="1250.00"' not in html or "unknown" not in html:
        raise BudgetError("рефорекаст не попал в HTML")
    print(folder)
    print(json.dumps(view["reforecast"], ensure_ascii=False))
    return folder


def _folder_state(folder: Path) -> tuple[Path, dict]:
    path = folder / "state" / "budget_state.json"
    return path, load_json(path)


def _iso_date(value: str) -> str:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise BudgetError(f"дата должна быть ISO YYYY-MM-DD: {value}") from exc


def cmd_import_table(folder: Path, file: Path, kind: str) -> None:
    if kind not in {"lines", "actuals", "accruals", "history"}:
        raise BudgetError("kind: lines, actuals, accruals или history")
    imported = import_table(file)
    path, state = _folder_state(folder)
    state[kind] = imported["rows"]
    save_json(path, state)
    if imported["mapping_questions"]:
        issues_path = folder / "state" / "open_issues.json"
        issues = load_json(issues_path)
        for item in imported["mapping_questions"]:
            issues.append({"question": item["question"], "blocking": True, "status": "open"})
        save_json(issues_path, issues)
    print(json.dumps({"rows": len(imported["rows"]), "mapping_questions": imported["mapping_questions"]}, ensure_ascii=False))


def cmd_normalize(folder: Path) -> None:
    path, state = _folder_state(folder)
    state["history"] = normalize_actuals(state.get("history") or [], {})
    save_json(path, state)
    print("PASS")


def cmd_recalc_annual(folder: Path) -> None:
    path, state = _folder_state(folder)
    for line in state.get("lines") or []:
        monthly = line.get("monthly_amounts") or {}
        if monthly:
            line["annual_amount"] = money(annual_amount(monthly))
    save_json(path, state)
    print("PASS")


def cmd_scenario(folder: Path, actions_file: Path) -> None:
    actions = json.loads(actions_file.read_text(encoding="utf-8"))
    path, state = _folder_state(folder)
    decisions = load_json(folder / "state" / "decisions.json")
    updated = apply_scenario(state, actions, decisions)
    save_json(path, updated)
    print(json.dumps(updated["scenario_overlay"], ensure_ascii=False))


def cmd_assume(folder: Path, assumption_id: str, text: str) -> None:
    path = folder / "state" / "assumptions.json"
    items = load_json(path)
    items.append({"id": assumption_id, "statement": text, "confidence": "low"})
    save_json(path, items)
    print(assumption_id)


def cmd_question(folder: Path, text: str) -> None:
    path = folder / "state" / "open_issues.json"
    items = load_json(path)
    items.append({"question": text, "blocking": False, "status": "open"})
    save_json(path, items)
    print("PASS")


def cmd_bridge(folder: Path, parts: dict) -> None:
    path, state = _folder_state(folder)
    state["bridge"] = parts
    save_json(path, state)
    print(money(load("calculate").bridge(parts)))


def cmd_reforecast(folder: Path, args) -> None:
    path, state = _folder_state(folder)
    state["reforecast_inputs"] = {
        "approved_total": args.approved,
        "phased_to_date": args.phased,
        "actual_total": args.actual,
        "accrual_total": args.accrual,
        "etc_total": args.etc,
        "driver": args.driver,
    }
    save_json(path, state)
    print("PASS")


def cmd_link_ops(folder: Path, project: str) -> None:
    target = Path(project)
    if not (target / "project_state.yaml").is_file():
        raise BudgetError("related_ops_project должен быть папкой Legal Ops с project_state.yaml")
    path = folder / "state" / "budget_context.json"
    context = load_json(path)
    context["related_ops_project"] = str(target)
    save_json(path, context)
    print("PASS")


def cmd_decide(folder: Path, date: str, text: str) -> None:
    path = folder / "state" / "decisions.json"
    items = load_json(path)
    decision_id = f"DEC-{len(items) + 1:03d}"
    items.append({"id": decision_id, "date": _iso_date(date), "text": text, "kind": "decision"})
    save_json(path, items)
    print(decision_id)


def cmd_accept(folder: Path, date: str, text: str) -> None:
    path = folder / "state" / "decisions.json"
    items = load_json(path)
    decision_id = f"DEC-{len(items) + 1:03d}"
    items.append({"id": decision_id, "date": _iso_date(date), "text": text, "kind": "acceptance"})
    save_json(path, items)
    print(decision_id)


def cmd_stage(folder: Path, stage_id: str, status: str) -> None:
    if status not in STAGE_STATUSES:
        raise BudgetError(f"status должен быть одним из {STAGE_STATUSES}")
    path, state = _folder_state(folder)
    stages = dict(state.get("stages") or {})
    stages[stage_id] = status
    state["stages"] = stages
    save_json(path, state)
    print("PASS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Legal budget run")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--folder", required=True)
    init.add_argument("--run-id", required=True)
    init.add_argument("--goal", required=True)
    demo_cmd = sub.add_parser("demo")
    demo_cmd.add_argument("--folder")
    reforecast_cmd = sub.add_parser("reforecast-demo")
    reforecast_cmd.add_argument("--folder")
    parse = sub.add_parser("parse-finance")
    parse.add_argument("--file", required=True)
    parse.add_argument("--folder")
    challenge_cmd = sub.add_parser("challenge")
    challenge_cmd.add_argument("--folder", required=True)
    render = sub.add_parser("render")
    render.add_argument("--folder", required=True)
    cut = sub.add_parser("cut")
    cut.add_argument("--folder", required=True)
    cut.add_argument("--percent", required=True)
    hire = sub.add_parser("make-vs-buy")
    hire.add_argument("--external", required=True)
    hire.add_argument("--salary", required=True)
    gate = sub.add_parser("gate")
    gate.add_argument("--folder", required=True)
    imported = sub.add_parser("import-table")
    imported.add_argument("--folder", required=True)
    imported.add_argument("--file", required=True)
    imported.add_argument("--kind", required=True)
    normalized = sub.add_parser("normalize")
    normalized.add_argument("--folder", required=True)
    recalc = sub.add_parser("recalc-annual")
    recalc.add_argument("--folder", required=True)
    scenario = sub.add_parser("scenario")
    scenario.add_argument("--folder", required=True)
    scenario.add_argument("--actions", required=True)
    assume = sub.add_parser("assume")
    assume.add_argument("--folder", required=True)
    assume.add_argument("--id", required=True)
    assume.add_argument("--text", required=True)
    question = sub.add_parser("question")
    question.add_argument("--folder", required=True)
    question.add_argument("--text", required=True)
    bridge = sub.add_parser("bridge")
    bridge.add_argument("--folder", required=True)
    for key in ("prior", "ceased", "price", "volume", "new-demand", "headcount", "fx"):
        bridge.add_argument(f"--{key}", required=True)
    forecast = sub.add_parser("reforecast")
    forecast.add_argument("--folder", required=True)
    forecast.add_argument("--approved", required=True)
    forecast.add_argument("--phased", required=True)
    forecast.add_argument("--actual", required=True)
    forecast.add_argument("--accrual", required=True)
    forecast.add_argument("--etc", required=True)
    forecast.add_argument("--driver")
    link = sub.add_parser("link-ops")
    link.add_argument("--folder", required=True)
    link.add_argument("--project", required=True)
    decide = sub.add_parser("decide")
    decide.add_argument("--folder", required=True)
    decide.add_argument("--date", required=True)
    decide.add_argument("--text", required=True)
    accept = sub.add_parser("accept")
    accept.add_argument("--folder", required=True)
    accept.add_argument("--date", required=True)
    accept.add_argument("--text", required=True)
    stage = sub.add_parser("stage")
    stage.add_argument("--folder", required=True)
    stage.add_argument("--id", required=True)
    stage.add_argument("--status", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_run(Path(args.folder), args.run_id, args.goal)
            print(args.folder)
        elif args.command == "reforecast-demo":
            reforecast_demo(Path(args.folder) if args.folder else None)
        elif args.command == "parse-finance":
            card = parse_finance_template(Path(args.file))
            if args.folder:
                folder = Path(args.folder)
                context_path = folder / "state" / "budget_context.json"
                context = apply_finance_card(load_json(context_path), card)
                save_json(context_path, context)
                issues_path = folder / "state" / "open_issues.json"
                issues = load_json(issues_path)
                known = {
                    item.get("question")
                    for item in issues
                    if isinstance(item, dict)
                }
                for text in card.get("open_questions") or []:
                    if text not in known:
                        issues.append({"question": text, "blocking": False, "status": "open"})
                        known.add(text)
                save_json(issues_path, issues)
            print(json.dumps(card, ensure_ascii=False, indent=2))
        elif args.command == "challenge":
            folder = Path(args.folder)
            state = load_json(folder / "state" / "budget_state.json")
            context = load_json(folder / "state" / "budget_context.json")
            print(json.dumps([item.as_dict() for item in challenge(state, context)], ensure_ascii=False, indent=2))
        elif args.command == "import-table":
            cmd_import_table(Path(args.folder), Path(args.file), args.kind)
        elif args.command == "normalize":
            cmd_normalize(Path(args.folder))
        elif args.command == "recalc-annual":
            cmd_recalc_annual(Path(args.folder))
        elif args.command == "scenario":
            cmd_scenario(Path(args.folder), Path(args.actions))
        elif args.command == "assume":
            cmd_assume(Path(args.folder), args.id, args.text)
        elif args.command == "question":
            cmd_question(Path(args.folder), args.text)
        elif args.command == "bridge":
            cmd_bridge(
                Path(args.folder),
                {
                    "prior": args.prior,
                    "ceased": args.ceased,
                    "price": args.price,
                    "volume": args.volume,
                    "new_demand": args.new_demand,
                    "headcount": args.headcount,
                    "fx": args.fx,
                },
            )
        elif args.command == "reforecast":
            cmd_reforecast(Path(args.folder), args)
        elif args.command == "link-ops":
            cmd_link_ops(Path(args.folder), args.project)
        elif args.command == "decide":
            cmd_decide(Path(args.folder), args.date, args.text)
        elif args.command == "accept":
            cmd_accept(Path(args.folder), args.date, args.text)
        elif args.command == "stage":
            cmd_stage(Path(args.folder), args.id, args.status)
        elif args.command == "render":
            result = render_pack(Path(args.folder))
            print(json.dumps({"total": result["view"]["total"], "issues": result["issues"]}, ensure_ascii=False))
            if result["issues"]:
                return 2
        elif args.command == "cut":
            state = load_json(Path(args.folder) / "state" / "budget_state.json")
            print(json.dumps(plan_cut(state.get("lines") or [], args.percent), ensure_ascii=False, indent=2))
        elif args.command == "make-vs-buy":
            print(json.dumps(make_vs_buy(args.external, args.salary), ensure_ascii=False, indent=2))
        elif args.command == "gate":
            print(json.dumps(quality_gate(Path(args.folder)), ensure_ascii=False, indent=2))
        else:
            demo(Path(args.folder) if args.folder else None)
    except (BudgetError, CalcGap) as exc:
        print(f"ERROR\t{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
