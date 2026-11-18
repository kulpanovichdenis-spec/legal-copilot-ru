#!/usr/bin/env python3
"""tools/matter_knowledge — детерминированный тул слоя знаний по делу (Stage B, класс A).

Парсит и валидирует doc-карточки (_knowledge/<slug>.card.md) и собирает навигатор
(_knowledge/index.md) из карточек + matter-timeline.yaml/matter-facts.yaml.
ИЗВЛЕЧЕНИЕ содержания (тезисы/факты/события) — работа агента (класс C), НЕ этого
скрипта. Тул только валидирует форму и детерминированно собирает навигатор.

"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REQUIRED_FIELDS = ("doc", "doc_kind", "role", "card_status")
KEY_POINTS_HEADING = "## Ключевые тезисы"


def parse_card(text: str) -> dict:
    """Разобрать карточку: YAML-frontmatter + список тезисов из тела.

    Возвращает {"frontmatter": dict, "key_points": list[str]}.
    key_points — строки-буллеты (без ведущего "- ") из раздела «Ключевые тезисы».
    """
    fm: dict = {}
    body = text
    if text.startswith("---"):
        _, _, rest = text.partition("---")
        block, sep, body_after = rest.partition("\n---")
        if sep:
            data = yaml.safe_load(block)
            fm = data if isinstance(data, dict) else {}
            body = body_after
    key_points: list[str] = []
    in_kp = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_kp = (s == KEY_POINTS_HEADING)
            continue
        if in_kp and s.startswith("- "):
            key_points.append(s[2:].strip())
    return {"frontmatter": fm, "key_points": key_points}


def key_point_has_locator(point: str) -> bool:
    """Тезис проверяем: есть ли locator — непустой источник после em-dash «—»."""
    if "—" not in point:
        return False
    _, _, src = point.partition("—")
    return bool(src.strip())


def validate_card(card: dict) -> list[str]:
    """Ошибки карточки (пусто = валидна): обязательные поля + traceability тезисов."""
    errs: list[str] = []
    fm = card.get("frontmatter") or {}
    for field in REQUIRED_FIELDS:
        val = fm.get(field)
        # role="" — корень дела (документы Stage A без ролевой подпапки, см. ROLE_ORDER)
        if field == "role" and field in fm and val is not None and not str(val).strip():
            continue
        if val is None or not str(val).strip():
            errs.append(f"нет обязательного поля frontmatter: {field}")
    kps = card.get("key_points") or []
    if not kps:
        errs.append("нет ни одного тезиса в разделе «Ключевые тезисы»")
    for i, p in enumerate(kps, 1):
        if not key_point_has_locator(p):
            errs.append(f"тезис {i} без locator (нет источника после «—»): {p[:50]!r}")
    return errs


def load_card(path: Path) -> dict:
    return parse_card(path.read_text(encoding="utf-8"))


# Порядок ролевых групп в навигаторе (совпадает с таксономией Stage A).
ROLE_ORDER = (
    "Иск_приложения", "Отзыв_приложения", "Возражения_приложения",
    "Объяснения_приложения", "Ходатайства", "Судебные акты",
    "Экспертиза", "Третье_лицо", "Доказательства", "Проекты", "",
)


def _role_key(role: str) -> tuple:
    """Ключ сортировки ролевых групп: по ROLE_ORDER, префиксные (Экспертиза_X) — по префиксу."""
    for i, r in enumerate(ROLE_ORDER):
        if r and (role == r or role.startswith(r + "_")):
            return (i, role)
    if role == "":
        return (ROLE_ORDER.index(""), "")
    return (len(ROLE_ORDER), role)


def build_index(matter: str, cards: list[dict], timeline: dict | None,
                facts: dict | None) -> str:
    """Собрать навигатор index.md из карточек + matter-timeline/matter-facts (детерминированно)."""
    lines = [f"# Навигатор по делу: {matter}", "",
             "> Слой знаний для модели (Stage B). Черновик — human review. "
             "Факты/события — в matter-timeline/matter-facts; здесь — карта входа.", ""]

    lines.append("## Документы")
    groups: dict[str, list[dict]] = {}
    for c in cards:
        role = str((c.get("frontmatter") or {}).get("role", "") or "")
        groups.setdefault(role, []).append(c)
    for role in sorted(groups, key=_role_key):
        lines.append(f"### {role or '(корень)'}")
        for c in sorted(groups[role], key=lambda x: str(x.get("path", ""))):
            fm = c.get("frontmatter") or {}
            doc = fm.get("doc") or "?"
            first = (c.get("key_points") or ["—"])[0]
            one = first.split("—")[0].strip()[:80]
            lines.append(f"- [{doc}]({c.get('path', '')}) — {one}")
        lines.append("")

    if facts and facts.get("parties"):
        lines.append("## Стороны")
        for p in facts["parties"]:
            lines.append(f"- {p.get('id', '?')} {p.get('name', '?')} "
                         f"({p.get('role', '?')}) — `../matter-facts.yaml`")
        lines.append("")

    if facts and facts.get("gaps"):
        lines.append("## Пробелы")
        for g in facts["gaps"]:
            lines.append(f"- {g.get('id', '?')} {g.get('unknown', '?')} — `../matter-facts.yaml`")
        lines.append("")

    lines.append("## Слои дела")
    lines.append("- Хронология: `../matter-timeline.yaml`")
    lines.append("- Факты/стороны/пробелы: `../matter-facts.yaml`")
    lines.append("- Контекст: `../case-context.md`")
    if timeline is not None:
        lines.append(f"- Событий в хронологии: {len(timeline.get('events', []))}")
    lines.append("")
    return "\n".join(lines)


# ---------- CLI ----------

def _load_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except yaml.YAMLError:
        return None


def cmd_validate(args) -> int:
    d = Path(args.dir)
    cards = sorted(d.glob("*.card.md"))
    if not cards:
        print(f"нет карточек (*.card.md) в {d}")
        return 1
    total = 0
    for cp in cards:
        errs = validate_card(load_card(cp))
        if errs:
            total += len(errs)
            print(f"НЕВАЛИДНО {cp.name}:")
            for e in errs:
                print("  - " + e)
    if total:
        print(f"FAIL: ошибок {total} в карточках {d}")
        return 1
    print(f"OK: карточек {len(cards)}, все валидны")
    return 0


def cmd_build_index(args) -> int:
    case = Path(args.case)
    kdir = case / "_knowledge"
    if not kdir.exists():
        print(f"нет каталога {kdir} — сначала соберите карточки (skill matter-knowledge)")
        return 1
    cards = []
    for cp in sorted(kdir.glob("*.card.md")):
        c = load_card(cp)
        c["path"] = cp.name
        cards.append(c)
    timeline = _load_yaml(case / "matter-timeline.yaml")
    facts = _load_yaml(case / "matter-facts.yaml")
    idx = build_index(case.name, cards, timeline, facts)
    (kdir / "index.md").write_text(idx, encoding="utf-8")
    print(f"OK: навигатор {kdir / 'index.md'} — карточек {len(cards)}")
    return 0


def selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        case = Path(td) / "ДелоX"
        kdir = case / "_knowledge"
        kdir.mkdir(parents=True)
        (kdir / "a.card.md").write_text(
            "---\ndoc: \"Иск_приложения/Иск.pdf\"\ndoc_kind: иск\nrole: Иск_приложения\n"
            "card_status: draft\n---\n\n## Ключевые тезисы\n\n- Требует 100 ₽ — Иск, стр. 1\n",
            encoding="utf-8")
        assert cmd_build_index(_ns(case=str(case))) == 0
        assert cmd_validate(_ns(dir=str(kdir))) == 0
        assert (kdir / "index.md").exists()
    print("SELFTEST OK: matter_knowledge")
    return 0


class _ns:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def build_parser():
    import argparse
    ap = argparse.ArgumentParser(description="Тул слоя знаний по делу (Stage B).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("--dir", required=True, help="путь к каталогу _knowledge с *.card.md")
    p = sub.add_parser("build-index")
    p.add_argument("--case", required=True, help="путь к папке дела (содержит _knowledge и matter-*.yaml)")
    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    return {"validate": cmd_validate, "build-index": cmd_build_index}[args.cmd](args)


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
