"""Validate anonymized case-study cards kept in profile/knowledge."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
import yaml


SCHEMA_PATH = Path(__file__).with_name("case-study.schema.json")
VOCAB_DIR = Path(__file__).with_name("vocab")
VOCAB_FIELDS = {
    "matter_kind": "matter_kind.json",
    "matter_stage": "matter_stage.json",
    "our_role": "our_role.json",
    "dispute_type": "dispute_type.json",
}
DIRECT_IDENTIFIER_PATTERNS = (
    re.compile(r"\b(?:ООО|АО|ПАО)\b", re.IGNORECASE),
    re.compile(r"\b(?:ИНН|ОГРН|СНИЛС|паспорт)\b", re.IGNORECASE),
    re.compile(r"ИНН\s*\d{10,12}", re.IGNORECASE),
    re.compile(r"ОГРН\s*\d{13,15}", re.IGNORECASE),
    re.compile(r"р/с\s*\d{20}", re.IGNORECASE),
    re.compile(r"[А-ЯЁ][а-яё]+\s[А-ЯЁ]\.\s?[А-ЯЁ]\."),
    re.compile(r"[A-ZА-Я0-9._%+-]+@[A-ZА-Я0-9.-]+\.[A-ZА-Я]{2,}", re.IGNORECASE),
    re.compile(r"(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"),
)
INDEX_HEADER = (
    "| case_study_id | matter_kind | dispute_type | our_role | matter_stage "
    "| merits_result | recovery_status | topics | файл |"
)
INDEX_RULE = "|---|---|---|---|---|---|---|---|---|"


class CaseStudyError(ValueError):
    """Controlled validation failure for a case-study card."""


@dataclass(frozen=True)
class CaseStudy:
    path: Path
    metadata: dict[str, Any]
    body: str


def _load_schema() -> dict[str, Any]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for field, filename in VOCAB_FIELDS.items():
        values = json.loads((VOCAB_DIR / filename).read_text(encoding="utf-8"))
        if not isinstance(values, list) or not values:
            raise CaseStudyError(f"vocab {filename} must be a non-empty array")
        schema["properties"][field]["enum"] = values
    return schema


def _split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CaseStudyError(f"missing YAML frontmatter: {path}")
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise CaseStudyError(f"unclosed YAML frontmatter: {path}") from exc
    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        raise CaseStudyError(f"invalid YAML frontmatter: {path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise CaseStudyError(f"frontmatter must be a mapping: {path}")
    return metadata, "\n".join(lines[closing + 1 :]).strip()


def _validate_metadata(metadata: dict[str, Any], path: Path) -> None:
    schema = _load_schema()
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(metadata),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "root"
        raise CaseStudyError(f"invalid case-study contract at {location}: {first.message} ({path})")


def _normalize_yaml_scalars(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(metadata)
    if isinstance(normalized.get("updated"), date):
        normalized["updated"] = normalized["updated"].isoformat()
    return normalized


def _audit_anonymization(card_text: str, path: Path) -> None:
    for pattern in DIRECT_IDENTIFIER_PATTERNS:
        match = pattern.search(card_text)
        if match:
            raise CaseStudyError(
                f"anonymization check failed for {path}: direct identifier marker {match.group(0)!r}"
            )


def load_case_study(path: Path) -> CaseStudy:
    path = path.resolve()
    metadata, body = _split_frontmatter(path.read_text(encoding="utf-8-sig"), path)
    metadata = _normalize_yaml_scalars(metadata)
    _validate_metadata(metadata, path)
    if not body:
        raise CaseStudyError(f"case-study body is empty: {path}")
    _audit_anonymization(body, path)
    return CaseStudy(path=path, metadata=metadata, body=body)


def validate_tree(root: Path) -> list[CaseStudy]:
    root = root.resolve()
    cards = [load_case_study(path) for path in sorted(root.rglob("*.md")) if path.name.casefold() != "readme.md"]
    seen: dict[str, Path] = {}
    for card in cards:
        case_id = str(card.metadata["case_study_id"])
        if case_id in seen:
            raise CaseStudyError(f"duplicate case_study_id {case_id}: {seen[case_id]} and {card.path}")
        seen[case_id] = card.path
    return cards


def render_index(cards: list[CaseStudy], root: Path) -> str:
    root = root.resolve()
    kinds = json.loads((VOCAB_DIR / "matter_kind.json").read_text(encoding="utf-8"))
    grouped: dict[str, list[CaseStudy]] = {kind: [] for kind in kinds}
    for card in cards:
        grouped.setdefault(str(card.metadata["matter_kind"]), []).append(card)
    lines = ["# Case studies", ""]
    for kind in kinds:
        group = grouped.get(kind) or []
        if not group:
            continue
        lines.append(f"## {kind}")
        lines.append("")
        lines.append(INDEX_HEADER)
        lines.append(INDEX_RULE)
        for card in sorted(group, key=lambda item: str(item.metadata["case_study_id"])):
            meta = card.metadata
            outcome = meta["outcome"]
            topics = ", ".join(str(item) for item in meta["topics"])
            rel = card.path.resolve().relative_to(root).as_posix()
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(meta["case_study_id"]),
                        str(meta["matter_kind"]),
                        str(meta["dispute_type"]),
                        str(meta["our_role"]),
                        str(meta["matter_stage"]),
                        str(outcome["merits_result"]),
                        str(outcome["recovery_status"]),
                        topics,
                        rel,
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_index(root: Path) -> Path:
    root = root.resolve()
    cards = validate_tree(root)
    destination = root.parent / "index.md"
    destination.write_text(render_index(cards, root), encoding="utf-8", newline="\n")
    return destination


def stale_lines(knowledge_root: Path, months: int, today: date | None = None) -> list[str]:
    if months < 1:
        raise CaseStudyError("months must be >= 1")
    today = today or date.today()
    threshold = today - timedelta(days=months * 30)
    verified = knowledge_root / "verified"
    if not verified.is_dir():
        return []
    lines: list[str] = []
    for path in sorted(verified.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("valid_as_of")
        if not raw:
            continue
        as_of = date.fromisoformat(str(raw)[:10])
        if as_of > threshold:
            continue
        age = (today - as_of).days
        knowledge_id = str(payload.get("knowledge_id") or path.stem)
        lines.append(f"{knowledge_id} {as_of.isoformat()} {age}")
    return lines


def _cmd_validate(root: Path) -> int:
    cards = validate_tree(root)
    print(f"PASS: {len(cards)} case-study card(s) validated")
    return 0


def _cmd_selftest() -> int:
    import tempfile

    card = """---
schema_version: 2
case_study_id: cs_selftest_claim
matter_kind: claim
jurisdiction: RU
source_case_ids: [C-001]
dispute_type: services_partial_stage_refund
stages: [pretrial]
our_role: customer
matter_stage: closed_unknown
outcome:
  merits_result: unknown
  appeal_status: unknown
  settlement_status: unknown
  enforcement_status: unknown
  recovery_status: unknown
  outcome_evidence: []
evidence_chain_completeness: unknown
law_as_of: unknown
requires_current_law_check: true
topics: [самопроверка]
anonymization: verified
review_status: candidate
source_refs:
  - source_id: selftest
    source_type: analytical_case_card
    source_path: workflow/selftest/card.md
knowledge_candidate_ids: []
updated: 2026-09-24
---

## 1. Контекст и роли
Покупатель и Поставщик. [КОМПАНИЯ_1] не является прямым идентификатором.
"""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "cards"
        root.mkdir()
        (root / "card.md").write_text(card, encoding="utf-8")
        validate_tree(root)
        build_index(root)
        knowledge = Path(raw) / "knowledge" / "verified"
        knowledge.mkdir(parents=True)
        old = date.today() - timedelta(days=800)
        (knowledge / "ko_old.json").write_text(
            json.dumps({"knowledge_id": "ko_old", "valid_as_of": old.isoformat()}),
            encoding="utf-8",
        )
        found = stale_lines(knowledge.parent, 12)
        if len(found) != 1 or not found[0].startswith("ko_old "):
            raise CaseStudyError(f"selftest stale-check expected 1 line, got {found}")
    print("PASS: selftest")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate case-study cards")
    validate.add_argument("root", type=Path)

    index = sub.add_parser("build-index", help="Write the case-study navigator")
    index.add_argument("root", type=Path)

    stale = sub.add_parser("stale-check", help="List verified objects older than the threshold")
    stale.add_argument("root", type=Path)
    stale.add_argument("--months", type=int, default=12)

    sub.add_parser("selftest", help="Run an in-process smoke check")

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return _cmd_validate(args.root)
        if args.command == "build-index":
            path = build_index(args.root)
            print(f"PASS: {path}")
            return 0
        if args.command == "stale-check":
            for line in stale_lines(args.root, args.months):
                print(line)
            return 0
        if args.command == "selftest":
            return _cmd_selftest()
    except CaseStudyError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"ERROR: unknown command {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
