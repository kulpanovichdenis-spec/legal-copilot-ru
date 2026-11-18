# -*- coding: utf-8 -*-
"""Команда validate-cards: проверка карточек-указателей норм."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_cards as cards  # noqa: E402
import gov_store as store  # noqa: E402


def cmd_validate_cards(args) -> int:
    cards_dir = Path(args.cards_dir) if args.cards_dir else cards.CARDS_DIR
    errors = cards.validate_cards(cards_dir)
    if errors:
        print(f"ОШИБОК: {len(errors)}")
        for item in errors:
            print(f"  - {item}")
        return 1
    files = [p for p in cards_dir.glob("*.md") if p.name.lower() != "readme.md"]
    print(f"OK: карточек {len(files)}, ошибок нет")
    return 0


def register(sub) -> None:
    p = sub.add_parser("validate-cards", parents=[store.common_parser(need_slug=False)],
                       help="проверить карточки-указатели норм (references/corporate-norm-cards/llc)")
    p.add_argument("--cards-dir", help="каталог карточек (по умолчанию references/corporate-norm-cards/llc)")
    p.set_defaults(func=cmd_validate_cards)
