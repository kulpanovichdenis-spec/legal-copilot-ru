#!/usr/bin/env python3
"""Сборка документов Stage C: «Краткая справка по делу» и «Анализ дела и стратегия».

Класс A:
весь текст берётся из файлов папки дела; модуль от себя добавляет только заголовки
разделов и подписи полей. Маркеры неполноты подсвечивает профиль NoteDoc.

Вход — папка дела:
- case-context.md               — frontmatter (case_number, status), строка «Стадия:»;
- matter-timeline.yaml          — события (tools/matter_model/model.py);
- matter-facts.yaml             — стороны и пробелы (facts.py);
- matter-positions.yaml         — спорные вопросы и позиции сторон (positions.py);
- _analysis/case-analysis.yaml  — итог исследования (нужен только для analysis).

Выход — в корне папки дела, без перезаписи (коллизия → « (2)»):
- «ГГГГ-ММ-ДД Краткая справка по делу.docx» — только из matter-слоя;
- «ГГГГ-ММ-ДД Анализ дела и стратегия.docx» — matter-слой + case-analysis.yaml.

«Чья позиция сильнее» не хранится — выводится из our_position_strength (stronger_side).

Usage:
    python tools/case_analysis/case_docs.py validate --case DIR
    python tools/case_analysis/case_docs.py brief    --case DIR [--date YYYY-MM-DD]
    python tools/case_analysis/case_docs.py analysis --case DIR [--date YYYY-MM-DD]
    python tools/case_analysis/case_docs.py selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "matter_model"))

import facts  # noqa: E402
import model  # noqa: E402
import positions  # noqa: E402
from tools.case_intake.core import unique_name  # noqa: E402
from tools.docx_style.profiles import NoteDoc  # noqa: E402
from tools.workflow_layout import technical_path  # noqa: E402
from tools.case_analysis import structure  # noqa: E402

# Windows-консоль по умолчанию cp1251 — кириллица ломается.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BRIEF_TITLE = "Краткая справка по делу"
ANALYSIS_TITLE = "Анализ дела и стратегия"
ANALYSIS_FILE = Path("_analysis") / "case-analysis.yaml"
MATTER_FILES = ("matter-timeline.yaml", "matter-facts.yaml", "matter-positions.yaml")

# Шкалы калибровки — references/legal-opinion-method.md §9 (здесь не переопределяются).
STRENGTHS = ("strong", "moderately_strong", "balanced", "moderately_weak", "weak")
CERTAINTIES = ("high", "medium", "low")
IMPACTS = ("low", "medium", "high", "critical")
PRIORITIES = ("блокирующее", "высокое", "среднее", "низкое")

STRENGTH_LABELS = {"strong": "сильная", "moderately_strong": "скорее сильная",
                   "balanced": "равные шансы", "moderately_weak": "скорее слабая",
                   "weak": "слабая"}
CERTAINTY_LABELS = {"high": "высокая", "medium": "средняя", "low": "низкая"}
IMPACT_LABELS = {"low": "низкая", "medium": "средняя", "high": "высокая",
                 "critical": "критическая"}
ROLE_LABELS = {"our_side": "наша сторона", "counterparty": "контрагент",
               "opponent": "оппонент", "court": "суд", "gov_body": "госорган",
               "third_party": "третье лицо"}
KIND_LABELS = {"claim": "требование", "argument": "довод", "defense": "возражение",
               "procedural_request": "процессуальная просьба"}
REQUIRED_ISSUE_TEXT = ("rule", "analysis", "conclusion")
STATUS_LABELS = {"active": "в работе", "paused": "приостановлено", "closed": "закрыто"}


class RenderError(Exception):
    pass


def _blank(val) -> bool:
    return val is None or not str(val).strip()


def _str_list_errors(val, label: str) -> list[str]:
    """Список непустых строк. `val` отсутствует (None) — ок, поле опционально.
    Иначе обязан быть list[str] без пустых/не-строковых элементов. `label` уже
    несёт значимый префикс (например, «I-001: key_sources»)."""
    if val is None:
        return []
    if not isinstance(val, list):
        return [f"{label} должен быть списком строк, а не {type(val).__name__}"]
    return [f"{label}[{n}]: пустая строка или не строка" for n, x in enumerate(val, 1)
            if not isinstance(x, str) or _blank(x)]


def stronger_side(strength: str) -> str:
    """Чья позиция сильнее — производное от our_position_strength, не хранится."""
    if strength in ("strong", "moderately_strong"):
        return "наша сторона"
    if strength == "balanced":
        return "равные шансы"
    if strength in ("moderately_weak", "weak"):
        return "оппонент"
    raise RenderError(f"неизвестная our_position_strength: {strength!r}")


# ---------- вход ----------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
# Стадия — человеческий формат (bullet, templates/agent-notes/case-context-template.md).
_STAGE_BULLET_RE = re.compile(r"^\s*[-*]\s*Стадия\s*:\s*(.+?)\s*$", re.MULTILINE)
# Стадия — формат Stage A (tools/case_intake/bootstrap.py, CONTEXT_TEMPLATE): заголовок
# «## Стадия» и абзац-плейсхолдер, не bullet «Суть и статус».
_STAGE_SECTION_RE = re.compile(r"^##\s*Стадия\s*$\n(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)


def _stage_unfilled(value: str) -> bool:
    """Незаполненный плейсхолдер — «[…]» (шаблон человека) или «`[МАРКЕР]` — …»
    (Stage A, tools/case_intake/bootstrap.py): после снятия внешних бэктиков/пробелов
    начинается с «[»."""
    return value.strip().strip("`").strip().startswith("[")


def _stage_from_section(text: str) -> str:
    """Первая содержательная строка раздела «## Стадия» (до следующего «## »):
    пропускаем пустые строки, цитаты («>») и HTML-комментарии («<!--»)."""
    m = _STAGE_SECTION_RE.search(text)
    if not m:
        return ""
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith(">") or line.startswith("<!--"):
            continue
        line = re.sub(r"\s+", " ", line)
        return "" if _stage_unfilled(line) else line
    return ""


def _case_context(path: Path) -> dict:
    """Номер дела и статус — frontmatter case-context.md; стадия — строка «Стадия:»
    (раздел «Суть и статус» шаблона templates/agent-notes/case-context-template.md),
    а если её нет — первая содержательная строка раздела «## Стадия» (формат Stage A,
    tools/case_intake/bootstrap.py). Незаполненный плейсхолдер любого формата — пустая
    строка. Читаем как utf-8-sig: PowerShell пишет BOM, который иначе ломает frontmatter."""
    out = {"case_number": "", "status": "", "stage": ""}
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8-sig")
    m = _FRONTMATTER_RE.match(text)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        if isinstance(fm, dict):
            for key in ("case_number", "status"):
                val = fm.get(key)
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val if not _blank(v))
                out[key] = "" if _blank(val) else str(val).strip()
    s = _STAGE_BULLET_RE.search(text)
    if s:
        out["stage"] = "" if _stage_unfilled(s.group(1)) else s.group(1)
    else:
        out["stage"] = _stage_from_section(text)
    return out


def load_case(case: Path) -> dict:
    """Собрать всё нужное для документов из папки дела.

    Битый/неразбираемый `_analysis/case-analysis.yaml` не блокирует загрузку: справка
    от исследования не зависит (A4). `analysis` остаётся None, причина — в
    `analysis_error`."""
    case = Path(case)
    if not case.is_dir():
        raise RenderError(f"папка дела не найдена: {case}")
    missing = [name for name in MATTER_FILES if not technical_path(case, name).exists()]
    if missing:
        raise RenderError(f"в {case} нет {', '.join(missing)} — сначала matter-слой "
                          "(skills/matter-knowledge или tools/matter_model)")
    try:
        events = model.load(technical_path(case, "matter-timeline.yaml")).get("events") or []
        fct = facts.load(technical_path(case, "matter-facts.yaml"))
        pos = positions.load(technical_path(case, "matter-positions.yaml"))
    except (model.ModelError, yaml.YAMLError) as e:
        raise RenderError(str(e)) from e
    analysis = None
    analysis_error = None
    ap = technical_path(case, ANALYSIS_FILE.parent) / ANALYSIS_FILE.name
    if ap.exists():
        try:
            loaded = yaml.safe_load(ap.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            analysis_error = f"{ap.as_posix()} повреждён и не читается: {e}"
        else:
            if isinstance(loaded, dict):
                analysis = loaded
            else:
                analysis_error = f"{ap.as_posix()} не похож на case-analysis.yaml"
    return {
        "case": case,
        "context": _case_context(technical_path(case, "case-context.md")),
        "events": events,
        "parties": fct.get("parties") or [],
        "facts": fct.get("facts") or [],
        "gaps": fct.get("gaps") or [],
        "issues": pos["issues"],
        "positions": pos["positions"],
        "analysis": analysis,
        "analysis_error": analysis_error,
    }


# ---------- валидация ----------

def _our_side(cd: dict) -> list[dict]:
    return [p for p in cd["parties"] if p.get("role") == "our_side"]


def _live_issue_ids(cd: dict) -> set:
    return {i.get("id") for i in cd["issues"] if i.get("status") != "dropped"}


def validate_brief(cd: dict) -> list[str]:
    """Справке нужен валидный matter-слой и заданная наша сторона."""
    errs: list[str] = []
    if not _our_side(cd):
        errs.append("наша сторона не задана: в matter-facts нет стороны с role: our_side")
    errs.extend(model.validate_all({"events": cd["events"]}))
    errs.extend(facts.validate_all({"parties": cd["parties"], "gaps": cd["gaps"]}))
    errs.extend(positions.validate_all({"issues": cd["issues"], "positions": cd["positions"]},
                                       cd["parties"]))
    return errs


def validate_analysis(cd: dict) -> list[str]:
    """Анализу нужно всё, что справке, плюс полный, структурно валидный и согласованный
    case-analysis.yaml. Ошибка — всегда список строк, никогда исключение (A2): чужой/
    LLM-написанный файл может нарушить типы полей как угодно."""
    errs = validate_brief(cd)
    if cd.get("analysis_error"):
        return errs + [cd["analysis_error"]]
    a = cd.get("analysis")
    if a is None:
        return errs + [f"нет {ANALYSIS_FILE.as_posix()} — сначала исследование "
                       "(skill case-analysis, шаги 4–5)"]
    version = a.get("schema_version", 1)
    if type(version) is not int or version not in (1, 2):
        errs.append("schema_version: поддерживаются целые версии 1 и 2")
    if version == 2 or "case_structure" in a:
        errs.extend(facts.validate_all({"facts": cd.get("facts", [])}))
        errs.extend(structure.validate(a.get("case_structure"), cd))
        if version != 2:
            errs.append("case_structure требует schema_version: 2")
    if a.get("our_side") not in {p.get("id") for p in _our_side(cd)}:
        errs.append(f"our_side {a.get('our_side')!r} не совпадает со стороной "
                    "role: our_side в matter-facts")

    # A3: чекпоинт должен быть пройден целиком — хотя бы один подтверждённый вопрос,
    # ни одного забытого в 'proposed'. Проверка только здесь — brief от неё не зависит.
    all_statuses = [i.get("status") for i in cd["issues"]]
    if "confirmed" not in all_statuses:
        errs.append("нет ни одного подтверждённого (confirmed) вопроса — анализировать нечего")
    for i in cd["issues"]:
        if i.get("status") == "proposed":
            errs.append(f"{i.get('id')}: вопрос ещё не прошёл чекпоинт (status 'proposed') — "
                        "подтвердить или снять")

    raw_issues = a.get("issues")
    if raw_issues is not None and not isinstance(raw_issues, list):
        errs.append(f"issues должен быть списком, а не {type(raw_issues).__name__}")
        raw_issues = []
    status = {i.get("id"): i.get("status") for i in cd["issues"]}
    covered = set()
    seen_refs: set = set()
    for n, it in enumerate(raw_issues or [], 1):
        if not isinstance(it, dict):
            errs.append(f"issues[{n}]: ожидается объект")
            continue
        ref = it.get("issue_ref")
        tag = str(ref or f"issues[{n}]")
        if ref in seen_refs:
            errs.append(f"{tag}: issue_ref дублируется в case-analysis.yaml")
        seen_refs.add(ref)
        if ref not in status:
            errs.append(f"{tag}: issue_ref нет в matter-positions")
        elif status[ref] != "confirmed":
            errs.append(f"{tag}: вопрос не confirmed (status {status[ref]!r}) — анализ только "
                        "по подтверждённым юристом вопросам")
        covered.add(ref)
        for field, allowed in (("our_position_strength", STRENGTHS),
                               ("certainty", CERTAINTIES), ("impact", IMPACTS)):
            if it.get(field) not in allowed:
                errs.append(f"{tag}: {field} должен быть из {allowed}, а не {it.get(field)!r}")
        for field in REQUIRED_ISSUE_TEXT:
            if not isinstance(it.get(field), str) or _blank(it.get(field)):
                errs.append(f"{tag}: {field} должен быть непустой строкой")
        cv = it.get("counterarguments")
        if cv is not None and not isinstance(cv, str):
            errs.append(f"{tag}: counterarguments должен быть строкой")
        for field in ("dependencies", "mitigation", "to_prove", "key_sources"):
            errs.extend(_str_list_errors(it.get(field), f"{tag}: {field}"))
        ks = it.get("key_sources")
        if isinstance(ks, list) and not [s for s in ks if isinstance(s, str) and not _blank(s)]:
            errs.append(f"{tag}: пустые key_sources — вывод без источника не собирается")
    for iid, st in status.items():
        if st == "confirmed" and iid not in covered:
            errs.append(f"{iid}: подтверждённый вопрос без анализа в case-analysis.yaml")

    strategy_raw = a.get("strategy")
    if strategy_raw is not None and not isinstance(strategy_raw, dict):
        errs.append(f"strategy должен быть объектом, а не {type(strategy_raw).__name__}")
        strategy_raw = {}
    strategy = strategy_raw or {}
    if not isinstance(strategy.get("summary"), str) or _blank(strategy.get("summary")):
        errs.append("strategy.summary пустой")

    per_issue_raw = strategy.get("per_issue")
    if per_issue_raw is not None and not isinstance(per_issue_raw, list):
        errs.append(f"strategy.per_issue должен быть списком, а не {type(per_issue_raw).__name__}")
        per_issue_raw = []
    for n, x in enumerate(per_issue_raw or [], 1):
        if not isinstance(x, dict):
            errs.append(f"strategy.per_issue[{n}]: ожидается объект")
            continue
        pref = x.get("issue_ref")
        if pref not in covered:
            errs.append(f"strategy.per_issue[{n}]: issue_ref {pref!r} не среди "
                        "проанализированных вопросов")
        if _blank(x.get("line")):
            errs.append(f"strategy.per_issue[{n}]: пустой line")

    for field in ("evidence_to_collect", "procedural_steps"):
        errs.extend(_str_list_errors(strategy.get(field), f"strategy.{field}"))

    findings_raw = strategy.get("critic_findings")
    if findings_raw is not None and not isinstance(findings_raw, list):
        errs.append(f"strategy.critic_findings должен быть списком, а не "
                    f"{type(findings_raw).__name__}")
        findings_raw = []
    for n, f in enumerate(findings_raw or [], 1):
        if not isinstance(f, dict):
            errs.append(f"critic_findings[{n}]: ожидается объект")
            continue
        if f.get("priority") not in PRIORITIES:
            errs.append(f"critic_findings[{n}]: priority должен быть из {PRIORITIES}, "
                        f"а не {f.get('priority')!r}")
        if _blank(f.get("text")):
            errs.append(f"critic_findings[{n}]: пустой text")

    nd = strategy.get("next_document")
    if nd is not None and not isinstance(nd, str):
        errs.append("strategy.next_document должен быть строкой")

    errs.extend(_str_list_errors(a.get("lawyer_notes"), "lawyer_notes"))

    bs = a.get("brief_summary")
    if bs is not None and not isinstance(bs, str):
        errs.append("brief_summary должен быть строкой")

    return errs


# ---------- документы ----------

def _event_line(ev: dict) -> str:
    date = str(ev.get("date") or "дата не внесена")
    date_mark = f" {model.DATE_CHECK}" if ev.get("date_status") != "confirmed" else ""
    fact_mark = f" {model.FACT_CHECK}" if ev.get("fact_status") != "CONFIRMED" else ""
    return f"**{date}**{date_mark} — {ev.get('event')}{fact_mark}"


def _list_block(doc: NoteDoc, label: str, items) -> None:
    items = [str(x).strip() for x in (items or []) if not _blank(x)]
    if items:
        doc.para(f"**{label}:**", after=2, keep_next=True)
        for x in items:
            doc.bullet(x)


def build_brief(cd: dict, out: Path) -> Path:
    errs = validate_brief(cd)
    if errs:
        raise RenderError("справка не собирается:\n  " + "\n  ".join(errs))
    parties = {p.get("id"): p for p in cd["parties"]}
    live = _live_issue_ids(cd)
    live_positions = [p for p in cd["positions"] if p.get("issue_ref") in live]
    ctx = cd["context"]
    matter = cd["case"].name
    summary = (cd.get("analysis") or {}).get("brief_summary")

    doc = NoteDoc()
    doc.header(f"{BRIEF_TITLE} · {matter} · черновик")
    doc.title(BRIEF_TITLE.upper(), matter)
    if not _blank(summary):
        doc.heading("Коротко")
        doc.para(str(summary).strip())

    doc.heading("1. Дело")
    doc.bullet(f"**Папка дела:** {matter}")
    if ctx["case_number"]:
        doc.bullet(f"**Номер дела:** {ctx['case_number']}")
    if ctx["status"]:
        doc.bullet(f"**Статус:** {STATUS_LABELS.get(ctx['status'], ctx['status'])}")
    # Стадия — не пропускается даже при пустом значении (маркер вместо угадывания).
    doc.bullet(f"**Стадия:** {ctx['stage'] or model.FACT_CHECK}")

    doc.heading("2. Стороны")
    for p in cd["parties"]:
        req = ""
        if not _blank(p.get("requisites")):
            mark = f" {facts.REQ_CHECK}" if p.get("req_status") != "verified" else ""
            req = f"; {p['requisites']}{mark}"
        doc.bullet(f"**{p.get('name')}** — {ROLE_LABELS[p.get('role')]}{req}")

    doc.heading("3. Фактические обстоятельства")
    events = sorted(cd["events"], key=model.sort_key)
    for ev in events:
        doc.bullet(_event_line(ev))
    if not events:
        doc.para("В хронологии дела событий нет.")

    doc.heading("4. Что хотят стороны")
    theirs = [p for p in live_positions if p.get("kind") == "claim"
              and parties[p["party_ref"]].get("role") not in positions.NOT_OPPOSING_ROLES]
    for p in theirs:
        doc.bullet(f"**{parties[p['party_ref']].get('name')}**: {p.get('statement')}")
    if not theirs:
        doc.para("Требования других участников в карте позиций не выписаны.")

    doc.heading("5. Что хотим мы")
    ours = [p for p in live_positions if p.get("kind") == "claim"
            and parties[p["party_ref"]].get("role") == "our_side"]
    for p in ours:
        doc.bullet(str(p.get("statement")))
    if not ours:
        doc.para("Требования нашей стороны в карте позиций не выписаны.")

    doc.heading("6. Чего не хватает")
    gaps = [g for g in cd["gaps"] if g.get("status", "open") in ("open", "searching")]
    for g in gaps:
        doc.bullet(f"{g.get('unknown')} — {g.get('why_relevant')}")
    leads = positions.detect_leads({"issues": cd["issues"], "positions": cd["positions"]},
                                   cd["parties"])
    bare_ids = {cid for lead in leads if lead["type"] == "no_evidence" for cid in lead["ids"]}
    bare = [p for p in cd["positions"] if p.get("id") in bare_ids]
    ours_bare = [p for p in bare if parties[p["party_ref"]].get("role") == "our_side"]
    for p in ours_bare:
        doc.bullet(f"Наша позиция без указанных доказательств: «{p.get('statement')}»")
    if not gaps and not ours_bare:
        doc.para("Пробелы не зафиксированы.")

    doc.heading("7. Позиции других участников без доказательств")
    theirs_bare = [p for p in bare
                   if parties[p["party_ref"]].get("role") not in positions.NOT_OPPOSING_ROLES]
    for p in theirs_bare:
        doc.bullet(f"**{parties[p['party_ref']].get('name')}**: «{p.get('statement')}»")
    if not theirs_bare:
        doc.para("Позиций других участников без доказательств в карте нет.")

    doc.footer()
    return Path(doc.save(str(out)))


def _render_structure(doc: NoteDoc, cd: dict) -> None:
    """Render the validated contract without upgrading any declared status."""
    data = cd["analysis"]["case_structure"]
    records = {x["id"]: x for key in ("facts", "events", "gaps") for x in cd.get(key, [])}
    def source_lines(label, refs):
        for ident in refs:
            item = records[ident]
            value = item.get("statement") or item.get("event") or item.get("unknown")
            status = item.get("fact_status", "UNKNOWN")
            anchor = item.get("anchor") or {}
            anchored = model.evidence_anchor.is_verified(anchor)
            marker = "" if status == "CONFIRMED" and anchored else f" {model.FACT_CHECK}"
            paragraph = doc.bullet(f"**{label} {ident}:** {value} (статус: {status}){marker}")
            paragraph.paragraph_format.keep_with_next = bool(item.get("source_doc") or anchor.get("quote"))
            if status == "CONFIRMED" and not anchored:
                doc.para("Статус источника требует проверки: цитата не подтверждена.",
                         keep_next=bool(item.get("source_doc") or anchor.get("quote")))
            if item.get("source_doc"):
                doc.para(f"Источник: {item['source_doc']}, {item.get('source_fragment', '')}.",
                         keep_next=bool(anchor.get("quote")))
            if anchor.get("quote"):
                doc.para(f"Цитата: «{anchor['quote']}»; {anchor.get('location', '')}; "
                         f"сверка: {anchor.get('quote_check', 'не выполнена')}.")
    def rule_line(label, rule):
        mark = " [ПРОВЕРИТЬ НОРМУ]" if rule["status"] != "VERIFIED" else ""
        doc.para(f"**{label}:** {rule['text']}; источник: {rule['source']}; "
                 f"статус проверки: {rule['status']}{mark}.")
    suff = dict(zip(structure.SUFFICIENCY, ("полнота утверждений", "не хватает фактов",
        "структурный порок", "правовая неопределённость", "неопределённость квалификации")))
    doc.heading("Структура требований и доказательственные вопросы", 2)
    obj = data["objective"]
    doc.para(f"**Юридическая цель:** {obj['legal_outcome']}. **Бизнес-цель:** {obj['business_goal']}. "
             f"**Стадия:** {obj['stage']}.")
    doc.para("Полнота утверждений не означает доказанность. Статусы источников заявлены "
             "в анализе; структурная проверка не заменяет проверку права и оценку юриста.")
    for c in data["claims"]:
        doc.heading(f"{c['id']}: {c['outcome']}", 3)
        doc.para(f"Позиция {c['position_ref']}; вопрос {c['issue_ref']}.")
        for b in c["bases"]:
            doc.para(f"**{b['id']} ({b['role']}):** {suff[b['sufficiency']]}. {b['assessment']}")
            rule_line("Правовое основание", b["rule"])
            for e in b["elements"]:
                doc.para(f"**{e['id']}: {e['criterion']}.** {e['assessment']} "
                         f"(наличие утверждения: {e['allegation_status']}).", keep_next=True)
                source_lines("Факт", e["fact_refs"])
                source_lines("Пробел", e["gap_refs"])
    for x in data["excluded_claims"]:
        doc.bullet(f"Вне самостоятельного разбора {x['position_ref']}: {x['reason']}")
    for r in data["responses"]:
        doc.para(f"**{r['id']} / позиция {r['position_ref']} → {r['target_ref']}:** "
                 f"{r['assessment']}; существенность: {'да' if r['material'] else 'нет'}; "
                 f"состояние: {r['state']}.")
    for p in data["proof_issues"]:
        doc.heading(f"{p['id']}: доказательственная проблема {p['element_ref']}", 3)
        doc.para(f"Основание углублённой проверки: {p['trigger']}; позиция другой стороны: "
                 f"{p['party_position']}. Значимость: {p['materiality']}.")
        rule_line("Бремя и специальные правила", p["burden"])
        source_lines("Подтверждение", p["support_refs"])
        source_lines("Опровержение", p["counter_refs"])
        doc.para(f"**Проблема:** {p['problems']}. **Доступность:** {p['availability']}. "
                 f"**Последствие неподтверждения:** {p['nonproof_consequence']}. "
                 f"**Оценка:** {p['state']}.")
    labels = dict(zip(structure.STEP_KINDS, ("Уточнить факты", "Получить доказательства",
        "Исследовать право", "Сравнить основания", "Решение юриста")))
    for kind, tasks in structure.queues(data).items():
        if tasks:
            doc.para(f"**{labels[kind]}:**", keep_next=True)
            for task in tasks:
                owner = task.get("owner") or "ответственный не определён"
                doc.bullet(f"{task['item_ref']}: {task['action']}; {owner}.")


def build_analysis(cd: dict, out: Path) -> Path:
    errs = validate_analysis(cd)
    if errs:
        raise RenderError("анализ не собирается:\n  " + "\n  ".join(errs))
    a = cd["analysis"]
    parties = {p.get("id"): p for p in cd["parties"]}
    questions = {i.get("id"): i.get("question") for i in cd["issues"]}
    matter = cd["case"].name
    items = a["issues"]

    doc = NoteDoc()
    doc.header(f"{ANALYSIS_TITLE} · {matter} · черновик")
    doc.title(ANALYSIS_TITLE.upper(), matter)
    if a.get("schema_version", 1) == 1:
        doc.para("Структура элементов не проверялась: анализ прежнего формата (legacy). "
                 "Это не подтверждение полноты требования или доказательств.")

    doc.heading("1. Выводы кратко")
    doc.table(
        ["Вопрос", "Чья позиция сильнее", "Наша позиция", "Уверенность", "Значимость"],
        [[f"{it['issue_ref']}. {questions[it['issue_ref']]}",
          stronger_side(it["our_position_strength"]),
          STRENGTH_LABELS[it["our_position_strength"]],
          CERTAINTY_LABELS[it["certainty"]],
          IMPACT_LABELS[it["impact"]]] for it in items],
        [6.2, 3.0, 3.0, 2.4, 2.4], center_cols=(1, 2, 3, 4))

    doc.heading("2. Карта позиций сторон")
    for it in items:
        ref = it["issue_ref"]
        doc.heading(f"{ref}. {questions[ref]}", 2)
        rows = [[str(parties[p["party_ref"]].get("name")), KIND_LABELS[p["kind"]],
                 str(p.get("statement")), "; ".join(p.get("evidence") or []) or "не указаны",
                 str(p.get("stated_basis") or "—")]
                for p in cd["positions"] if p.get("issue_ref") == ref]
        if rows:
            doc.table(["Сторона", "Вид", "Позиция", "Доказательства", "Сослалась на"],
                      rows, [3.0, 2.2, 5.6, 3.4, 2.8])
        else:
            doc.para("Позиций по вопросу не выписано.")

    doc.heading("3. Мотивировка по вопросам")
    for it in items:
        ref = it["issue_ref"]
        doc.heading(f"{ref}. {questions[ref]}", 2)
        doc.para(f"**Правило.** {str(it['rule']).strip()}")
        doc.para(f"**Анализ.** {str(it['analysis']).strip()}")
        if not _blank(it.get("counterarguments")):
            doc.para(f"**Контраргументы.** {str(it['counterarguments']).strip()}")
        doc.para(f"**Итог.** {str(it['conclusion']).strip()}")
        doc.para(f"**Оценка:** позиция нашей стороны — "
                 f"{STRENGTH_LABELS[it['our_position_strength']]}; чья позиция сильнее — "
                 f"{stronger_side(it['our_position_strength'])}; уверенность — "
                 f"{CERTAINTY_LABELS[it['certainty']]}; значимость — "
                 f"{IMPACT_LABELS[it['impact']]}.")
        _list_block(doc, "Зависит от", it.get("dependencies"))
        _list_block(doc, "Как снизить риск", it.get("mitigation"))
        _list_block(doc, "Что доказать", it.get("to_prove"))
        _list_block(doc, "Ключевые источники", it.get("key_sources"))

    if a.get("schema_version") == 2:
        _render_structure(doc, cd)

    doc.heading("4. Стратегия")
    strategy = a.get("strategy") or {}
    doc.para(str(strategy["summary"]).strip())
    lines = [f"**{x.get('issue_ref')}. {questions.get(x.get('issue_ref'), '')}** — {x.get('line')}"
             for x in strategy.get("per_issue") or [] if not _blank(x.get("line"))]
    _list_block(doc, "Линия по вопросам", lines)
    _list_block(doc, "Что собрать", strategy.get("evidence_to_collect"))
    _list_block(doc, "Процессуальные шаги", strategy.get("procedural_steps"))
    if not _blank(strategy.get("next_document")):
        doc.para(f"**Следующий документ (рекомендация):** {str(strategy['next_document']).strip()}")

    doc.heading("5. Риски и замечания")
    findings = sorted(strategy.get("critic_findings") or [],
                      key=lambda f: PRIORITIES.index(f["priority"]))
    if findings:
        doc.table(["Приоритет", "Замечание"],
                  [[f["priority"], str(f["text"]).strip()] for f in findings],
                  [3.0, 14.0], center_cols=(0,), bold_cols=(0,))
    else:
        doc.para("Замечаний проверки стратегии не зафиксировано.")

    doc.heading("6. Заметка юристу")
    for note in a.get("lawyer_notes") or []:
        if not _blank(note):
            doc.bullet(str(note).strip())
    doc.bullet("Выбор стратегии и следующего документа — [СТРАТЕГИЧЕСКОЕ РЕШЕНИЕ ЮРИСТА]. "
               "Документ — черновик для проверки юристом.")

    doc.heading("7. Источники")
    seen: list[str] = []
    for it in items:
        for src in it.get("key_sources") or []:
            src = str(src).strip()
            if src and src not in seen:
                seen.append(src)
    for src in seen:
        doc.bullet(src)

    doc.footer()
    return Path(doc.save(str(out)))


def output_path(case: Path, title: str, date: str) -> Path:
    """Путь в корне папки дела; существующий файл не перезаписывается."""
    try:
        dt.date.fromisoformat(date)
    except ValueError as e:
        raise RenderError(f"дата должна быть в формате ГГГГ-ММ-ДД: {date!r}") from e
    case = Path(case)
    existing = {p.name for p in case.iterdir()}
    return case / unique_name(f"{date} {title}.docx", existing)


# ---------- демо-дело (фикстура selftest и тестов) ----------

def write_demo_case(case: Path) -> Path:
    """Обезличенное демо-дело: полный matter-слой и итог анализа."""
    case = Path(case)
    case.mkdir(parents=True, exist_ok=True)
    tl, ff, pf = (str(technical_path(case, name, create_parent=True)) for name in MATTER_FILES)
    technical_path(case, "case-context.md", create_parent=True).write_text(
        "---\nstatus: active\njurisdiction: RF\ncase_number: \"А40-1/2026\"\n---\n\n"
        "# Контекст дела: Альфа\n\n## Суть и статус\n\n"
        "- Предмет: взыскание долга по договору поставки\n"
        "- Стадия: первая инстанция, подготовка отзыва\n"
        "- Следующий шаг: отзыв на иск\n", encoding="utf-8")

    model.run(["init", "--file", tl, "--matter", case.name])
    model.run(["add", "--file", tl, "--event", "Заключён договор поставки",
               "--date", "2023-01-10", "--date-status", "confirmed",
               "--source-doc", "договор", "--source-fragment", "стр. 1",
               "--fact-status", "CONFIRMED"])
    model.run(["add", "--file", tl, "--event", "Последняя поставка по договору",
               "--date", "2023-03-01", "--date-status", "needs_check",
               "--source-doc", "иск", "--source-fragment", "стр. 2",
               "--fact-status", "REPORTED"])

    facts.run(["init", "--file", ff, "--matter", case.name])
    facts.run(["add-party", "--file", ff, "--name", "ООО «Альфа»", "--role", "our_side",
               "--source-doc", "иск", "--source-fragment", "шапка"])
    facts.run(["add-party", "--file", ff, "--name", "ООО «Бета»", "--role", "opponent",
               "--source-doc", "иск", "--source-fragment", "шапка"])
    facts.run(["add-gap", "--file", ff, "--unknown", "Акт сверки за 2025 год",
               "--why-relevant", "может прервать течение срока"])

    positions.run(["init", "--file", pf, "--matter", case.name])
    positions.run(["add-issue", "--file", pf, "--question", "Пропущен ли срок исковой давности?",
                   "--status", "confirmed"])
    positions.run(["add-issue", "--file", pf, "--question", "Подсудно ли дело этому суду?",
                   "--status", "dropped"])
    positions.run(["add-position", "--file", pf, "--party-ref", "P-002", "--issue-ref", "I-001",
                   "--kind", "claim", "--statement", "Взыскать 105 000 руб. долга",
                   "--source-doc", "иск", "--source-fragment", "просительная часть",
                   "--evidence", "Иск_приложения/договор.pdf"])
    positions.run(["add-position", "--file", pf, "--party-ref", "P-001", "--issue-ref", "I-001",
                   "--kind", "defense", "--statement", "Срок исковой давности истёк",
                   "--source-doc", "отзыв (проект)", "--source-fragment", "п. 3"])
    positions.run(["add-position", "--file", pf, "--party-ref", "P-001", "--issue-ref", "I-001",
                   "--kind", "claim", "--statement", "Отказать в иске полностью",
                   "--source-doc", "отзыв (проект)", "--source-fragment", "просительная часть",
                   "--evidence", "Отзыв_приложения/расчёт срока.xlsx"])
    positions.run(["add-position", "--file", pf, "--party-ref", "P-002", "--issue-ref", "I-002",
                   "--kind", "argument", "--statement", "Дело подсудно суду по месту истца",
                   "--source-doc", "иск", "--source-fragment", "стр. 1"])

    analysis = {
        "schema_version": 1,
        "matter": case.name,
        "our_side": "P-001",
        "brief_summary": "Спор о взыскании долга по договору поставки; "
                         "ключевой вопрос — исковая давность.",
        "issues": [{
            "issue_ref": "I-001",
            "our_position_strength": "moderately_strong",
            "certainty": "medium",
            "impact": "high",
            "rule": "Общий срок исковой давности — три года (ГК РФ, ст. 196) [ПРОВЕРИТЬ НОРМУ].",
            "analysis": "Истец узнал о нарушении не позднее даты последней поставки "
                        "[ПРОВЕРИТЬ СРОК].",
            "counterarguments": "Истец может сослаться на перерыв срока признанием долга.",
            "conclusion": "Позиция о пропуске срока скорее сильная, если нет акта сверки.",
            "dependencies": ["Нет акта сверки, подписанного ответчиком"],
            "mitigation": ["Запросить у бухгалтерии переписку об оплате"],
            "to_prove": ["Дату, когда истец узнал о нарушении"],
            "key_sources": ["ГК РФ, ст. 196 [ПРОВЕРИТЬ НОРМУ]"],
        }],
        "strategy": {
            "summary": "Строить защиту на пропуске срока исковой давности.",
            "per_issue": [{"issue_ref": "I-001", "line": "Заявить о пропуске срока в отзыве"}],
            "evidence_to_collect": ["Переписка сторон за 2025 год"],
            "procedural_steps": ["Заявить о пропуске срока до вынесения решения"],
            "next_document": "Отзыв на исковое заявление",
            "critic_findings": [{"priority": "высокое", "text": "Акт сверки может прервать срок"}],
        },
        "lawyer_notes": ["Уточнить у бизнеса, подписывался ли акт сверки"],
    }
    (case / "_analysis").mkdir(exist_ok=True)
    (case / ANALYSIS_FILE).write_text(
        yaml.safe_dump(analysis, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8")
    return case


# ---------- CLI ----------

def cmd_validate(args) -> int:
    cd = load_case(Path(args.case))
    # Битый case-analysis.yaml (analysis_error) — тоже «анализ есть»: показать ошибку
    # разбора через validate_analysis, а не молча свести к проверке одной справки (A4).
    full = cd["analysis"] is not None or bool(cd.get("analysis_error"))
    errs = validate_analysis(cd) if full else validate_brief(cd)
    if errs:
        print(f"НЕВАЛИДНО ({len(errs)}):")
        for e in errs:
            print(f"  - {e}")
        return 1
    scope = "справка и анализ" if full else f"справка ({ANALYSIS_FILE.as_posix()} ещё нет)"
    print(f"OK: собирается {scope}")
    return 0


def cmd_brief(args) -> int:
    case = Path(args.case)
    out = build_brief(load_case(case), output_path(case, BRIEF_TITLE, args.date))
    print(f"OK: {out}")
    return 0


def cmd_analysis(args) -> int:
    case = Path(args.case)
    out = build_analysis(load_case(case), output_path(case, ANALYSIS_TITLE, args.date))
    print(f"OK: {out}")
    return 0


def selftest() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        case = write_demo_case(Path(td) / "2026.09.24 CLAIM Альфа")
        assert run(["validate", "--case", str(case)]) == 0
        assert run(["brief", "--case", str(case), "--date", "2026-09-24"]) == 0
        assert run(["analysis", "--case", str(case), "--date", "2026-09-24"]) == 0
        names = sorted(p.name for p in case.glob("*.docx"))
        assert names == ["2026-09-24 Анализ дела и стратегия.docx",
                         "2026-09-24 Краткая справка по делу.docx"], names
    print("SELFTEST OK: справка и анализ собраны на демо-деле")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--case", required=True)
    for name in ("brief", "analysis"):
        p = sub.add_parser(name)
        p.add_argument("--case", required=True)
        p.add_argument("--date", default=dt.date.today().isoformat())
    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    return {"validate": cmd_validate, "brief": cmd_brief, "analysis": cmd_analysis}[args.cmd](args)


def main() -> int:
    try:
        return run(sys.argv[1:])
    except RenderError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
