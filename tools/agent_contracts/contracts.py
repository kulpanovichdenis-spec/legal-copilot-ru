#!/usr/bin/env python3
"""Контракты отчётов проверяющих агентов: схема, смысловые правила, рендер, гейт сохранения.

Агент (субагент или
основная модель in-context) возвращает один JSON-блок по схеме из `schemas/`. Код проверяет:

- схему (`jsonschema`);
- смысловые правила: `VERIFIED` только при открытом источнике и маршруте (`usable_now: true`
  для нормы, первоисточник для судебного акта), иначе статус понижается до
  `OPENED_UNVERIFIED`/`NOT_CHECKED` с пометкой; у каждого входного тезиса ровно один результат;
  довод adverse без проверенной опоры несёт маркер;
- манифест проверок документа (`check-run`): каждая обязательная по матрице проверка
  выполнена с валидным отчётом либо явно «не запускалась: причина»; отчёт встроен.

Счётчики итогов агент не пишет — их считает `summary()`. Человек читает `render()`, не JSON.
Матрица срабатывания — `references/legal-opinion-subagents.md`.

Usage:
    python tools/agent_contracts/contracts.py validate REPORT.json [--schema NAME] [--claims CLAIMS.json] [--write]
    python tools/agent_contracts/contracts.py render REPORT.json [--schema NAME]
    python tools/agent_contracts/contracts.py extract REPLY.txt -o REPORT.json
    python tools/agent_contracts/contracts.py check-run MANIFEST.json
    python tools/agent_contracts/contracts.py selftest
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

import jsonschema

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMAS = ("source_verification.v1", "adversarial_position.v1", "consistency_report.v1",
           "intake_classification.v1", "checks_manifest.v1", "skill_review.v1")
VERDICT_ORDER = ("READY", "SOME_CONCERNS", "MATERIAL_CONCERNS", "REFUSE")
SKILL_TEXT_SUFFIXES = (".md", ".yaml", ".yml", ".txt")
AGENT_SCHEMA = {
    "source-verifier": "source_verification.v1",
    "adversarial-researcher": "adversarial_position.v1",
    "consistency-checker": "consistency_report.v1",
}
NOT_VERIFIED_MARKER = "[СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ]"
NORM_MARKER = "[ПРОВЕРИТЬ НОРМУ]"


class ContractError(Exception):
    pass


def load_schema(name: str) -> dict:
    if name not in SCHEMAS:
        raise ContractError(f"неизвестная схема {name!r}; есть: {', '.join(SCHEMAS)}")
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def extract(text: str) -> dict:
    """JSON-отчёт из ответа агента: последний блок ```json … ``` или весь текст."""
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.S)
    candidates = list(reversed(blocks)) + [text.strip()]
    for raw in candidates:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ContractError("в ответе агента нет JSON-объекта")


def _schema_errors(report: dict, name: str) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema(name))
    out = []
    for err in sorted(validator.iter_errors(report), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(корень)"
        out.append(f"схема: {where}: {err.message}")
    return out


# ---------- смысловые правила ----------

def _sv_rules(report: dict, claims: list[str] | None) -> tuple[list[str], list[str]]:
    errors, notes = [], []
    seen: dict[str, int] = {}
    for item in report.get("items", []):
        cid = item["claim_id"]
        seen[cid] = seen.get(cid, 0) + 1
        if item["result"] != "VERIFIED":
            continue
        via = item["checked_via"]
        reason = None
        if not via.get("opened"):
            reason, new = "источник не открыт", "NOT_CHECKED"
        elif item["source_kind"] == "norm" and via.get("usable_now") is not True:
            reason, new = "норма без маршрута usable_now: true", "OPENED_UNVERIFIED"
        elif item["source_kind"] in ("court_act", "court_position") and via.get("primary_source") is not True:
            reason, new = "судебный акт без первоисточника", "OPENED_UNVERIFIED"
        if reason:
            item["result"] = new
            item["validator_note"] = f"понижено с VERIFIED: {reason}"
            if not item.get("recommended_marker"):
                item["recommended_marker"] = NORM_MARKER if item["source_kind"] == "norm" else NOT_VERIFIED_MARKER
            notes.append(f"{cid}: VERIFIED → {new} ({reason})")
    dups = sorted(c for c, n in seen.items() if n > 1)
    if dups:
        errors.append(f"тезисы с несколькими результатами: {', '.join(dups)}")
    if claims is not None:
        missing = [c for c in claims if c not in seen]
        extra = sorted(set(seen) - set(claims))
        if missing:
            errors.append(f"нет результата по тезисам: {', '.join(missing)}")
        if extra:
            errors.append(f"результаты по тезисам, которых не было во входе: {', '.join(extra)}")
    return errors, notes


def _ap_rules(report: dict) -> list[str]:
    errors = []
    for arg in report.get("arguments", []):
        sup = arg["support"]
        if sup["verification"] != "route_verified" and not sup.get("marker"):
            errors.append(f"довод {arg['id']}: опора не проверена ({sup['verification']}) — нужен маркер в support.marker")
        if sup["source_class"] != "none" and not sup.get("citation"):
            errors.append(f"довод {arg['id']}: source_class={sup['source_class']} без citation")
    if not report.get("arguments") and not report.get("not_found"):
        errors.append("нет ни доводов, ни раздела not_found — пустой отчёт не принимается")
    return errors


def _allowed_verdict(report: dict) -> str:
    """Самый мягкий вердикт, который допускают находки (Т4; скилл-QA по образцу skills-qa CFL)."""
    statuses = {p["id"]: p["status"] for p in report["parameters"]}
    legal = report["legal_failure_modes"].values()
    missing = [k for k, v in statuses.items() if v == "missing"]
    partial = [k for k, v in statuses.items() if v == "partial"]
    if report["risk_surface"]["embedded_instructions"]:
        return "REFUSE"
    hard = ("missing" in legal or statuses.get("insufficient_input") == "missing"
            or statuses.get("delegation_threshold") == "missing")
    if hard or missing:
        return "MATERIAL_CONCERNS"
    if partial or "partial" in legal:
        return "SOME_CONCERNS"
    return "READY"


def _quote_in_skill(skill_dir: Path, anchor: dict) -> bool:
    from tools.evidence_anchor.anchor import check  # noqa: PLC0415
    files = [skill_dir / "SKILL.md"] + sorted(
        f for f in skill_dir.rglob("*") if f.is_file() and f.suffix in SKILL_TEXT_SUFFIXES and f.name != "SKILL.md")
    for f in files:
        if f.is_file() and check(f, anchor["quote"])["quote_check"] == "matched":
            return True
    return False


def _sr_rules(report: dict, base_dir: Path | None) -> tuple[list[str], list[str]]:
    errors, notes = [], []
    ids = [p["id"] for p in report["parameters"]]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errors.append(f"параметры повторяются: {', '.join(dup)}")
    allowed = _allowed_verdict(report)
    if VERDICT_ORDER.index(report["verdict"]) < VERDICT_ORDER.index(allowed):
        errors.append(f"вердикт {report['verdict']} мягче допустимого по находкам: не лучше {allowed}")
    for p in report["parameters"]:
        if p["status"] == "addressed" and not p.get("anchor"):
            errors.append(f"{p['id']}: «addressed» без цитаты из скилла — чем подтверждено?")
    skill_dir = Path(report["skill_path"])
    if not skill_dir.is_absolute() and base_dir is not None:
        skill_dir = base_dir / skill_dir
    if skill_dir.is_file():
        skill_dir = skill_dir.parent
    if not skill_dir.is_dir():
        notes.append(f"папка скилла {report['skill_path']} не найдена — цитаты не сверены")
        return errors, notes
    anchors = [(p["id"], p.get("anchor")) for p in report["parameters"]] + \
              [(f"fix {n}", f.get("anchor")) for n, f in enumerate(report["fixes"], 1)]
    for where, a in anchors:
        if a and not _quote_in_skill(skill_dir, a):
            errors.append(f"{where}: цитата не найдена в файлах скилла — «{a['quote'][:60]}»")
    return errors, notes


def validate(report: dict, schema: str | None = None, claims: list[str] | None = None,
             base_dir: Path | None = None) -> dict:
    """Проверить отчёт. Возвращает {ok, schema, errors, notes, report} — report с понижениями."""
    report = copy.deepcopy(report)
    name = schema or report.get("schema")
    if not name:
        raise ContractError("схема не указана ни аргументом, ни полем schema")
    errors = _schema_errors(report, name)
    notes: list[str] = []
    if not errors:
        if name == "source_verification.v1":
            e, notes = _sv_rules(report, claims)
            errors += e
        elif name == "adversarial_position.v1":
            errors += _ap_rules(report)
        elif name == "skill_review.v1":
            e, notes = _sr_rules(report, base_dir)
            errors += e
    return {"ok": not errors, "schema": name, "errors": errors, "notes": notes, "report": report}


def summary(report: dict) -> dict:
    name = report.get("schema")
    if name == "source_verification.v1":
        out: dict[str, int] = {}
        for item in report["items"]:
            out[item["result"]] = out.get(item["result"], 0) + 1
        return out
    if name == "consistency_report.v1":
        out = {}
        for f in report["findings"]:
            out[f["severity"]] = out.get(f["severity"], 0) + 1
        return out
    if name == "adversarial_position.v1":
        return {"arguments": len(report["arguments"]),
                "route_verified": sum(a["support"]["verification"] == "route_verified" for a in report["arguments"]),
                "adverse_practice": len(report.get("adverse_practice", []))}
    return {}


# ---------- рендер для человека ----------

def _lines(title: str, values: list[str]) -> list[str]:
    return [f"## {title}"] + ([f"- {v}" for v in values] if values else ["- нет"]) + [""]


def render(report: dict) -> str:
    name = report.get("schema")
    out: list[str] = []
    if name == "source_verification.v1":
        out += ["# SOURCE_VERIFICATION", ""]
        for item in report["items"]:
            via = item["checked_via"]
            route = f"{via.get('tool')}" + (f" / {via['provider']}" if via.get("provider") else "")
            out += [f"## {item['claim_id']}",
                    f"Тезис: {item['proposition']}",
                    f"Источник: {item['source_cited']}",
                    f"Проверено через: {route}; открыт: {'да' if via.get('opened') else 'нет'}"
                    + (f"; usable_now: {via['usable_now']}" if via.get("usable_now") is not None else ""),
                    f"Результат: {item['result']}"]
            if item.get("anchor"):
                out.append(f"Подтверждающий фрагмент: «{item['anchor']['quote']}» ({item['anchor']['location']})")
            if item.get("edition_date"):
                out.append(f"Редакция: {item['edition_date']}")
            out.append(f"Комментарий: {item['comment']}")
            if item.get("recommended_marker"):
                out.append(f"Маркер при встраивании: {item['recommended_marker']}")
            if item.get("validator_note"):
                out.append(f"Валидатор: {item['validator_note']}")
            out.append("")
        counts = summary(report)
        out += ["## Итог", "- " + "; ".join(f"{k}: {v}" for k, v in sorted(counts.items())), ""]
        out += _lines("Недоступные инструменты", report.get("tools_unavailable", []))
    elif name == "adversarial_position.v1":
        out += ["# ADVERSARIAL_POSITION", "", "## Вопрос", report["question"], "", "## Сильнейшие доводы против"]
        for a in report["arguments"]:
            s = a["support"]
            mark = f" {s['marker']}" if s.get("marker") else ""
            out.append(f"{a['id']}. {a['argument']} — ОПОРА: {s.get('citation') or 'нет'} "
                       f"[{s['source_class']}, {s['verification']}]{mark}; ПОЧЕМУ РЕЛЕВАНТНО: {a['relevance']}")
        out.append("")
        out.append("## Неблагоприятная практика / исключения")
        practice = report.get("adverse_practice", [])
        out += [f"- {p['citation']} — {p['against']}; отличить: {p['distinguishable']}"
                + (f", {p['basis']}" if p.get("basis") else "") for p in practice] or ["- нет"]
        out.append("")
        out += _lines("Слабые фактические допущения", report.get("weak_assumptions", []))
        out += _lines("Вероятные вопросы суда / органа", report.get("likely_questions", []))
        out += _lines("Чего НЕ нашлось", report.get("not_found", []))
        out += _lines("Недоступные инструменты", report.get("tools_unavailable", []))
    elif name == "consistency_report.v1":
        out += ["# CONSISTENCY_REPORT", "", "## Найденные рассогласования"]
        if not report["findings"]:
            out.append("Внутренних противоречий не выявлено.")
        for f in report["findings"]:
            out += [f"{f['id']}. ТИП: {f['type']}", f"   ГДЕ: {' ↔ '.join(f['locations'])}",
                    f"   СУТЬ: {f['description']}", f"   ПРИОРИТЕТ: {f['severity']}"]
            if f.get("suggested_fix"):
                out.append(f"   ИСПРАВЛЕНИЕ: {f['suggested_fix']}")
        out.append("")
        out += _lines("Что проверялось", report["checked"])
    elif name == "skill_review.v1":
        labels = {"addressed": "есть", "partial": "частично", "missing": "нет", "n_a": "не применимо"}
        verdicts = {"READY": "Готов", "SOME_CONCERNS": "Есть замечания",
                    "MATERIAL_CONCERNS": "Существенные замечания", "REFUSE": "Отказ"}
        out += [f"# Проверка скилла: {report['skill']}", "",
                f"Вердикт: **{verdicts[report['verdict']]}**"
                + (f" — {report['verdict_reason']}" if report.get("verdict_reason") else ""),
                f"Происхождение: {'внешний' if report['origin'] == 'external' else 'свой'}; путь: {report['skill_path']}", "",
                "## Параметры"]
        for p in report["parameters"]:
            line = f"- {p['id']}: {labels[p['status']]} — {p['finding']}"
            if p.get("anchor"):
                line += f" («{p['anchor']['quote']}», {p['anchor']['location']})"
            out.append(line)
        lfm = report["legal_failure_modes"]
        out += ["", "## Юридические режимы сбоя",
                f"- решение вместо поддержки решения: {labels[lfm['decision_vs_support']]}",
                f"- конфиденциальность, ПДн, коммерческая тайна: {labels[lfm['confidentiality']]}",
                f"- разрыв ответственности (подписать не читая): {labels[lfm['accountability_gap']]}", ""]
        rs = report["risk_surface"]
        out += ["## Поверхность риска",
                f"- инструменты: {', '.join(rs['tools']) or 'нет'}",
                f"- запись вне workflow/: {'да' if rs['writes_outside_workflow'] else 'нет'}",
                f"- внешние вызовы: {', '.join(rs['external_calls']) or 'нет'}",
                f"- платные вызовы: {', '.join(rs['paid_calls']) or 'нет'}", ""]
        if report.get("conflicts"):
            out += _lines("Пересечения с другими скиллами", [f"{c['skill']}: {c['overlap']}" for c in report["conflicts"]])
        out += _lines("Что поправить", [f"[{f['priority']}] {f['change']}" for f in report["fixes"]])
        found = report["risk_surface"]["embedded_instructions"]
        if found:
            out += _lines("Встроенные инструкции в скилле — [ВСТРОЕННАЯ ИНСТРУКЦИЯ — НЕ ИСПОЛНЕНО]", found)
        return "\n".join(out).rstrip() + "\n"
    else:
        raise ContractError(f"рендер для схемы {name!r} не предусмотрен")
    found = report.get("embedded_instructions") or []
    if found:
        out += _lines("Встроенные инструкции в источниках — [ВСТРОЕННАЯ ИНСТРУКЦИЯ — НЕ ИСПОЛНЕНО]", found)
    return "\n".join(out).rstrip() + "\n"


# ---------- гейт сохранения: манифест проверок ----------

def required_checks(manifest: dict) -> dict[str, str]:
    """Обязательные проверки по матрице references/legal-opinion-subagents.md: агент → основание."""
    depth = manifest["research_depth"]
    req: dict[str, str] = {}
    if manifest["skill"] == "legal-opinion":
        if depth in ("standard", "deep"):
            req["source-verifier"] = f"глубина {depth}"
            req["adversarial-researcher"] = f"глубина {depth}"
        if manifest.get("position_led"):
            req["adversarial-researcher"] = "position_led"
        if depth == "deep" and manifest.get("issues_count", 1) >= 2:
            req["consistency-checker"] = "deep и ≥2 issue"
    else:  # procedural-document-drafter
        kind = (manifest.get("document_kind") or "").lower()
        mandatory = ("иск", "отзыв", "жалоба", "возражения", "объяснения", "коап")
        if any(k in kind for k in mandatory):
            req["adversarial-researcher"] = f"документ «{manifest.get('document_kind')}»"
            req["source-verifier"] = "ссылки проекта перед сохранением"
    return req


def check_run(manifest_path: str | Path) -> dict:
    """Можно ли сохранять документ: все запущенные и обязательные проверки закрыты."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = _schema_errors(manifest, "checks_manifest.v1")
    warnings: list[str] = []
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    by_agent: dict[str, list[dict]] = {}
    for c in manifest["checks"]:
        by_agent.setdefault(c["agent"], []).append(c)
        label = c["agent"]
        if c["status"] == "not_run":
            if not (c.get("reason") or "").strip():
                errors.append(f"{label}: «не запускалась» без причины")
            continue
        report_path = manifest_path.parent / (c.get("report") or "")
        if not c.get("report") or not report_path.is_file():
            errors.append(f"{label}: статус {c['status']}, но файла отчёта нет ({c.get('report')}) — дождаться отчёта")
            continue
        try:
            res = validate(json.loads(report_path.read_text(encoding="utf-8")), AGENT_SCHEMA[c["agent"]])
        except (json.JSONDecodeError, ContractError) as exc:
            errors.append(f"{label}: отчёт не читается: {exc}")
            continue
        errors += [f"{label}: {e}" for e in res["errors"]]
        warnings += [f"{label}: {n}" for n in res["notes"]]
        if not c.get("integrated"):
            errors.append(f"{label}: отчёт есть, но не отмечен как встроенный (integrated: true)")
    for agent, why in required_checks(manifest).items():
        if agent not in by_agent:
            errors.append(f"{agent}: обязательна ({why}), но в манифесте нет ни отчёта, ни причины")
        elif all(c["status"] == "not_run" for c in by_agent[agent]):
            warnings.append(f"{agent}: обязательна ({why}), не запускалась — причина должна быть в записке юристу")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ---------- CLI ----------

def _print_result(res: dict) -> int:
    for n in res.get("notes", []) + res.get("warnings", []):
        print(f"ПРЕДУПРЕЖДЕНИЕ: {n}")
    for e in res["errors"]:
        print(f"ОШИБКА: {e}")
    print("OK" if res["ok"] else "НЕ ПРОЙДЕНО")
    return 0 if res["ok"] else 1


def selftest() -> int:
    sv = {"schema": "source_verification.v1", "caller_skill": "legal-opinion", "items": [
        {"claim_id": "C1", "proposition": "т", "source_cited": "ст. 401 ГК РФ", "source_kind": "norm",
         "checked_via": {"tool": "pravo_get_article", "provider": "pravo-gov-ru", "usable_now": True, "opened": True},
         "result": "VERIFIED", "comment": "ок"},
        {"claim_id": "C2", "proposition": "т", "source_cited": "ст. 428 ГК РФ", "source_kind": "norm",
         "checked_via": {"tool": "tavily_extract", "opened": True},
         "result": "VERIFIED", "comment": "агрегатор"}]}
    res = validate(sv, claims=["C1", "C2"])
    assert res["ok"], res
    assert res["report"]["items"][1]["result"] == "OPENED_UNVERIFIED"
    assert res["report"]["items"][1]["recommended_marker"] == NORM_MARKER
    assert summary(res["report"]) == {"VERIFIED": 1, "OPENED_UNVERIFIED": 1}
    assert not validate(sv, claims=["C1", "C2", "C3"])["ok"]
    bad = copy.deepcopy(sv)
    del bad["items"][0]["result"]
    assert not validate(bad)["ok"]
    assert "SOURCE_VERIFICATION" in render(res["report"])
    assert extract("текст\n```json\n{\"a\": 1}\n```\n") == {"a": 1}
    print("selftest OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("report")
    v.add_argument("--schema")
    v.add_argument("--claims", help="JSON-список claim_id, отданных агенту")
    v.add_argument("--write", action="store_true", help="записать отчёт с понижениями обратно")
    v.add_argument("--base-dir", help="корень для относительного skill_path (skill_review)")
    r = sub.add_parser("render")
    r.add_argument("report")
    r.add_argument("--schema")
    x = sub.add_parser("extract")
    x.add_argument("reply")
    x.add_argument("-o", "--output", required=True)
    c = sub.add_parser("check-run")
    c.add_argument("manifest")
    sub.add_parser("selftest")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "selftest":
            return selftest()
        if args.cmd == "extract":
            data = extract(Path(args.reply).read_text(encoding="utf-8"))
            Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"OK: {args.output}")
            return 0
        if args.cmd == "check-run":
            return _print_result(check_run(args.manifest))
        data = json.loads(Path(args.report).read_text(encoding="utf-8"))
        if args.cmd == "validate":
            claims = json.loads(Path(args.claims).read_text(encoding="utf-8")) if args.claims else None
            res = validate(data, args.schema, claims, Path(args.base_dir) if args.base_dir else Path.cwd())
            if args.write and not _schema_errors(data, res["schema"]):
                Path(args.report).write_text(json.dumps(res["report"], ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
            if res["ok"]:
                print("Итог: " + "; ".join(f"{k}: {v}" for k, v in summary(res["report"]).items()))
            return _print_result(res)
        if args.cmd == "render":
            res = validate(data, args.schema)
            if not res["ok"]:
                return _print_result(res)
            print(render(res["report"]), end="")
            return 0
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"ОШИБКА: {exc}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
