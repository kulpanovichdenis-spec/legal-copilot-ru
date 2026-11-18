"""Чтение карточек договорного плейбука по разделам.

Карточки большие, поэтому агент читает не файл целиком, а нужный раздел:

    python tools/contract_playbook/cards.py find поставка
    python tools/contract_playbook/cards.py show postavka --section 1
    python tools/contract_playbook/cards.py show postavka --section "Проверка договора"
    python tools/contract_playbook/cards.py neighbors postavka

Ключ карточки: имя файла без расширения, `id` или прежний `contract_id`.
Карточка — навигация, не источник права: норму проверять по маршруту
route_norm_verification(jurisdiction="RU", probe=true).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / "references" / "contract-playbook-cards"


def load(root: Path = CARDS) -> tuple[dict, dict]:
    index = json.loads((root / "_index.json").read_text(encoding="utf-8"))
    graph = json.loads((root / "_graph.json").read_text(encoding="utf-8"))
    return index, graph


def resolve(index: dict, key: str) -> dict | None:
    wanted = key.strip().casefold()
    for card in index["cards"]:
        if wanted in (card["slug"].casefold(), card["id"].casefold()):
            return card
    for alias in index["aliases"]:
        if wanted == alias["old_id"].casefold():
            return resolve(index, alias["slug"])
    return None


def norm(text: str) -> str:
    return text.casefold().replace("ё", "е")


def token_hit(q: str, key: str) -> bool:
    """Совпадение по целой части идентификатора, а не по куску слова."""
    parts = re.split(r"[-_.]", norm(key))
    return q == norm(key) or any(part.startswith(q) for part in parts if part)


def find(index: dict, query: str) -> list[dict]:
    q = norm(query.strip())
    hits = [c for c in index["cards"] if q in norm(c["title"]) or token_hit(q, c["slug"]) or token_hit(q, c["id"])]
    seen = {c["slug"] for c in hits}
    for alias in index["aliases"]:
        if (q in norm(alias["old_title"]) or token_hit(q, alias["old_id"])) and alias["slug"] not in seen:
            card = resolve(index, alias["slug"])
            if card:
                hits.append(card)
                seen.add(card["slug"])
    return hits


def split_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Возвращает вводную часть и список (заголовок, текст раздела)."""
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    parts = re.split(r"^## (.*)$", body, flags=re.M)
    intro = parts[0].strip()
    sections = [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts), 2)]
    return intro, sections


def section_text(root: Path, card: dict, section: str | None) -> str:
    text = (root / card["path"]).read_text(encoding="utf-8")
    intro, sections = split_sections(text)
    if section is None:
        listing = "\n".join(f"- {title}" for title, _ in sections)
        return f"{intro}\n\nРазделы:\n{listing}"
    wanted = section.strip().casefold()
    for title, body in sections:
        number = title.split(".", 1)[0].strip()
        if wanted == number or wanted in title.casefold():
            return f"## {title}\n\n{body}"
    raise KeyError(section)


def neighbors(index: dict, graph: dict, card: dict) -> list[dict]:
    titles = {c["slug"]: c["title"] for c in index["cards"]}
    out = []
    for edge in graph["edges"]:
        if edge["from"] == card["slug"]:
            out.append({"rel": edge["rel"], "card": edge["to"], "title": titles.get(edge["to"], ""), "scope": edge.get("scope", "")})
        elif edge["to"] == card["slug"] and edge["rel"] in ("specializes", "distinguishes_from"):
            out.append({"rel": edge["rel"] + " (обратная)", "card": edge["from"], "title": titles.get(edge["from"], ""), "scope": edge.get("scope", "")})
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Карточки договорного плейбука по разделам")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--family")
    p_find = sub.add_parser("find")
    p_find.add_argument("query")
    p_show = sub.add_parser("show")
    p_show.add_argument("card")
    p_show.add_argument("--section")
    p_nb = sub.add_parser("neighbors")
    p_nb.add_argument("card")
    args = parser.parse_args(argv)
    index, graph = load()
    if args.cmd == "list":
        for card in index["cards"]:
            if args.family and card["family"] != args.family:
                continue
            print(f"{card['slug']}\t{card['kind']}\t{card['family']}\t{card['title']}")
        return 0
    if args.cmd == "find":
        hits = find(index, args.query)
        for card in hits:
            print(f"{card['slug']}\t{card['kind']}\t{card['title']}\t{card['path']}")
        return 0 if hits else 1
    card = resolve(index, args.card)
    if card is None:
        print(f"Карточка не найдена: {args.card}. Попробуйте find.", file=sys.stderr)
        return 1
    if args.cmd == "show":
        try:
            print(section_text(CARDS, card, args.section))
        except KeyError:
            print(f"Раздел не найден: {args.section}. Разделы: {'; '.join(card['sections'])}", file=sys.stderr)
            return 1
        return 0
    for item in neighbors(index, graph, card):
        scope = f" — {item['scope']}" if item["scope"] else ""
        print(f"{item['rel']}\t{item['card']}\t{item['title']}{scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
