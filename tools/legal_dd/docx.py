from __future__ import annotations

from pathlib import Path
from typing import Iterable

from tools.docx_style.profiles import NoteDoc

from .i18n import tr_status, tr_value
from .utils import utc_now


def _text(value) -> str:
    if value in (None, "", [], {}):
        return "—"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value) or "—"
    return str(value)


def _translated_list(value) -> str:
    if not value:
        return "—"
    return ", ".join(tr_value(item) for item in value)


def _sentence(value) -> str:
    text = _text(value).rstrip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


def markdown_to_docx(markdown: str, path: Path, fallback_title: str) -> Path:
    """Render the small Markdown subset produced by request generators."""
    doc = NoteDoc()
    title_written = False
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# ") and not title_written:
            doc.title(line[2:].strip())
            title_written = True
        elif line.startswith("## "):
            doc.heading(line[3:].strip(), 1)
        elif line.startswith("### "):
            doc.heading(line[4:].strip(), 2)
        elif line.startswith("- "):
            doc.bullet(line[2:].strip())
        else:
            doc.para(line)
    if not title_written:
        doc.title(fallback_title)
    doc.footer()
    path = Path(path)
    doc.save(str(path))
    return path


def _facts_section(doc: NoteDoc, facts: Iterable[dict]) -> None:
    doc.heading("3. Факты и provenance", 1)
    items = list(facts)
    if not items:
        doc.para("Факты ещё не зафиксированы.")
        return
    for fact in items:
        locator = fact.get("location") or {}
        where = " / ".join(
            str(locator.get(key))
            for key in ("document_id", "page", "section", "paragraph", "sheet", "cell", "api_field")
            if locator.get(key) not in (None, "")
        )
        doc.heading(f"{fact.get('fact_id', 'FACT')} — {fact.get('field_id', 'факт')}", 2)
        doc.para(f"Статус: {tr_status(fact.get('state'))}. Значение: {_text(fact.get('normalized_value'))}.")
        doc.para(f"Источник и точное место: {where or '[ПРОВЕРИТЬ ИСТОЧНИК]'}.")
        doc.para(f"Цитата: {_text(fact.get('quote'))}.")
        doc.para(f"Human review: {tr_status((fact.get('human_review') or {}).get('status', 'pending'))}.")


def render_dd_report(
    path: Path,
    project: dict,
    checks: list[dict],
    evidence: list[dict],
    findings: list[dict],
    facts: list[dict],
    decisions: list[dict],
    contract_inputs: dict,
) -> Path:
    """Render the human-facing DD review draft from structured project state."""
    doc = NoteDoc()
    doc.header(f"DD review · {project.get('project_id', '')} · {utc_now()[:10]}")
    doc.title(project.get("name_ru") or project.get("name") or "Юридический due diligence", "Черновик для проверки юристом")

    intake = project.get("intake") or {}
    doc.heading("1. Периметр сделки", 1)
    doc.para(f"Тип сделки: {tr_value(intake.get('transaction_type'))}.")
    doc.para(f"Активы: {_translated_list(intake.get('assets_in_scope'))}.")
    doc.para(f"Продукты: {_translated_list(intake.get('product_types'))}.")
    doc.para(f"Юрисдикции: {_text(intake.get('jurisdictions'))}.")
    doc.para(f"Модель передачи: {tr_value(intake.get('transfer_model'))}.")
    doc.para(f"Расширения: {_text(project.get('active_extensions'))}.")

    evidence_by_id = {item.get("requirement_id", item.get("id")): item for item in evidence}
    doc.heading("2. Покрытие DD и пробелы", 1)
    if not checks:
        doc.para("Активные области ещё не разрешены. [ПРОВЕРИТЬ ФАКТ]")
    for check in checks:
        agent = check.get("agent_assessment") or {}
        human = check.get("human_review") or {}
        required = check.get("evidence_requirements") or []
        missing = [
            requirement_id
            for requirement_id in required
            if (evidence_by_id.get(requirement_id) or {}).get("status")
            not in {"satisfied", "external_source", "not_applicable"}
        ]
        doc.heading(f"{check.get('id', '')} — {check.get('title_ru') or check.get('title') or ''}", 2)
        doc.para(f"Предварительная оценка: {tr_status(agent.get('status', 'not_started'))}.")
        doc.para(f"Вывод агента: {_sentence(agent.get('conclusion'))}")
        doc.para(f"Human review: {tr_status(human.get('status', 'pending'))}.")
        if missing:
            doc.para(f"Не закрытые evidence requirements: {', '.join(missing)}.")

    _facts_section(doc, facts)

    doc.heading("4. Findings и последствия для сделки", 1)
    if not findings:
        doc.para("Findings ещё не зафиксированы.")
    for finding in findings:
        doc.heading(f"{finding.get('id', 'FINDING')} — {finding.get('summary_ru') or finding.get('summary') or ''}", 2)
        doc.para(f"Существенность: {tr_status(finding.get('severity'))}.")
        doc.para(f"Последствие: {_sentence(finding.get('transaction_consequence') or finding.get('contract_effect'))}")
        doc.para(f"Human review: {tr_status((finding.get('human_review') or {}).get('status', 'pending'))}.")

    doc.heading("5. Решения юриста и drafting handoff", 1)
    if not decisions:
        doc.para("Подтверждённые Contract Decisions отсутствуют.")
    for decision in decisions:
        human = decision.get("human_decision") or {}
        doc.heading(f"{decision.get('decision_id', 'DECISION')} — {decision.get('topic_ru') or decision.get('topic') or ''}", 2)
        doc.para(f"Статус: {tr_status(human.get('status', 'pending'))}.")
        doc.para(f"Вариант: {_text(human.get('selected_option') or decision.get('agent_proposal'))}.")
    package = contract_inputs.get("suggested_document_package") or []
    if package:
        doc.para("Предлагаемый пакет документов:")
        for item in package:
            doc.bullet(tr_value(item))

    doc.heading("6. Ограничения и статус", 1)
    doc.para("Документ является черновиком. Final DD status требует явного подтверждения юристом.")
    doc.para("Карточки DD и состояние проекта не заменяют проверку действующих норм и судебной практики по правилам legal-copilot.")
    doc.footer()
    path = Path(path)
    doc.save(str(path))
    return path
