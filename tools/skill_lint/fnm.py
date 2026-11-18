"""SKILL-DESIGN-FNM-01 как код: таблица дизайна скилла существует, полна и ссылается на реальные проверки.

Один источник правил таблицы:
`tools/legal_dd/fnm.py` импортирует отсюда.

Где таблица:
- `skills/<skill>/design/fnm-design-table.yaml` (по умолчанию);

Скилл из `fnm_scope.yaml` без валидной таблицы — ERROR линтера. Скилл вне списка, но с
таблицей в `design/` — таблица тоже проверяется. Остальные — одна итоговая строка (старые
скиллы задним числом не переделываются).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REQUIRED_DESIGN_FIELDS = (
    "professional_method", "human_procedure", "purpose", "failure_mode", "required_invariant",
    "constraint_type", "ai_implementation", "validator", "eval",
)
CONSTRAINT_TYPES = ("HARD", "INVARIANT", "HEURISTIC", "PRESENTATION")
DEFAULT_TABLE = "design/fnm-design-table.yaml"
SCOPE_FILE = Path(__file__).resolve().parent / "fnm_scope.yaml"

_PATH = re.compile(r"`?((?:[\w.-]+/)+[\w.-]+\.(?:py|md|ya?ml|json))`?")
_ID = re.compile(r"^([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b")


def load_scope(path: Path = SCOPE_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(data.get("skills") or {})


def validate_rows(rows: list[dict]) -> list[str]:
    """Обязательные поля и тип ограничения по строкам таблицы."""
    errors = []
    if not rows:
        return ["таблица FNM пуста"]
    for n, row in enumerate(rows, 1):
        rid = row.get("id") or f"строка {n}"
        missing = [f for f in REQUIRED_DESIGN_FIELDS if not str(row.get(f) or "").strip()]
        if missing:
            errors.append(f"{rid} missing FNM fields: {missing}")
        ctype = row.get("constraint_type")
        if ctype and ctype not in CONSTRAINT_TYPES:
            errors.append(f"{rid}: constraint_type {ctype!r} не из {CONSTRAINT_TYPES}")
    return errors


def _id_exists(token: str, search_roots: list[Path], exclude: Path) -> bool:
    for base in search_roots:
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if f.is_file() and f.suffix in (".yaml", ".yml", ".md", ".py", ".json") and f != exclude:
                try:
                    if token in f.read_text(encoding="utf-8", errors="ignore"):
                        return True
                except OSError:
                    continue
    return False


def validate_refs(rows: list[dict], table: Path, repo_root: Path) -> list[str]:
    """validator/eval: путь — должен существовать; ID (VAL-…, EVAL-…) — должен встречаться в пакете или эвалах."""
    errors = []
    package = table.parent.parent
    roots = [package, repo_root / "tests" / "skill-evals"]
    for n, row in enumerate(rows, 1):
        rid = row.get("id") or f"строка {n}"
        for field in ("validator", "eval"):
            value = str(row.get(field) or "").strip()
            for m in _PATH.finditer(value):
                if not (repo_root / m.group(1)).exists():
                    errors.append(f"{rid}.{field}: файл {m.group(1)} не найден")
            ident = _ID.match(value)
            if ident and not _id_exists(ident.group(1), roots, table):
                errors.append(f"{rid}.{field}: {ident.group(1)} не найден ни в пакете, ни в tests/skill-evals")
    return errors


def validate_table(table: Path, repo_root: Path) -> list[str]:
    if not table.exists():
        return [f"нет таблицы FNM: {table.relative_to(repo_root).as_posix()}"]
    try:
        data = yaml.safe_load(table.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [f"таблица FNM не читается: {exc}"]
    rows = data.get("rows") or []
    return validate_rows(rows) + validate_refs(rows, table, repo_root)


def lint_fnm(repo_root: Path, scope_file: Path | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """({skill: errors}, skills_without_table). Ошибки только у скиллов в scope и у тех, где таблица есть."""
    scope = load_scope(scope_file or SCOPE_FILE)
    errors: dict[str, list[str]] = {}
    without: list[str] = []
    for skill_md in sorted(repo_root.glob("skills/*/SKILL.md")):
        name = skill_md.parent.name
        table = repo_root / scope[name] if scope.get(name) else skill_md.parent / DEFAULT_TABLE
        if name in scope or table.exists():
            errs = validate_table(table, repo_root)
            if errs:
                errors[name] = errs
        else:
            without.append(name)
    for name in scope:
        if not (repo_root / "skills" / name / "SKILL.md").exists():
            errors.setdefault(name, []).append("скилл из fnm_scope.yaml не найден в skills/")
    return errors, without
