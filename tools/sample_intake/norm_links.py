"""Связи образцов с нормами: поля `norm_links` / `guidance_links` в карточках и NORMS-INDEX.md.

Карточка образца хранит в frontmatter, с какими нормами связаны пункты формы:

    norm_links:
      - norm: "381-ФЗ ст. 9 ч. 4"       # единый формат ключа, см. NORM_RE
        clause: "п. 8.6"                # пункт формы (необязательно)
        role: limit                     # basis | limit | reference
        status: verified                # verified — текст нормы открыт; unverified — навигация
        edition: "ред. от 04.07.2026"
        checked: 2026-11-01
        source: "КонсультантПлюс"
    guidance_links:                     # разъяснения, письма, практика — только применимые
      - doc: "Разъяснения ФАС России …"
        norm: "381-ФЗ ст. 9 ч. 4"
        clause: "п. 8.6"
        status: verified
        checked: 2026-11-01

`build_norms_index()` собирает обратный указатель «норма → образцы и пункты».
`extract_mentions()` вытаскивает упоминания норм из текста (для автозаполнения
со статусом unverified — это навигация, не проверенное основание).
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

NORMS_INDEX_NAME = "NORMS-INDEX.md"
ROLES = ("basis", "limit", "reference")
STATUSES = ("verified", "unverified")

CODES = ("ГК РФ", "НК РФ", "КоАП РФ", "АПК РФ", "ГПК РФ", "ТК РФ", "ЖК РФ", "ЗК РФ", "УК РФ")
CODES_POINTS = ("ГК РФ", "НК РФ", "ЗК РФ")  # статьи делятся на пункты; в остальных кодексах — части
_ACT = (
    r"(?:" + "|".join(re.escape(c) for c in CODES) + r"|\d+-ФЗ"
    r"|(?:ПП РФ|Решение Совета ЕЭК|Решение Коллегии ЕЭК|Инструкция Банка России|Приказ [А-ЯЁа-яё]+(?: России)?)"
    r" № [\w./-]+(?: от \d\d\.\d\d\.\d{4})?)"
)
_UNIT = r"(?: ст\. \d+(?:\.\d+)*)?(?: ч\. \d+(?:\.\d+)?)?(?: п\. \d+(?:\.\d+)*)?(?: пп\. \d+(?:\.\d+)*)?(?: абз\. \d+)?"
NORM_RE = re.compile(rf"^{_ACT}{_UNIT}$")

ROLE_RU = {"basis": "основание", "limit": "ограничение", "reference": "справочно"}
STATUS_RU = {"verified": "сверено", "unverified": "не сверено"}


def card_meta(text: str) -> dict:
    """Полный YAML frontmatter карточки (пустой dict, если его нет или он битый)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    try:
        meta = yaml.safe_load(text[3:end if end != -1 else None]) or {}
    except yaml.YAMLError:
        return {}
    return meta if isinstance(meta, dict) else {}


def validate_links(meta: dict) -> list[str]:
    """Проблемы формата в norm_links / guidance_links (пустой список — все в порядке)."""
    problems: list[str] = []
    for i, link in enumerate(meta.get("norm_links") or []):
        where = f"norm_links[{i}]"
        if not isinstance(link, dict) or not link.get("norm"):
            problems.append(f"{where}: нет поля norm")
            continue
        if not NORM_RE.match(str(link["norm"])):
            problems.append(f"{where}: ключ нормы не в едином формате: «{link['norm']}»")
        if link.get("role", "reference") not in ROLES:
            problems.append(f"{where}: role «{link.get('role')}» не из {ROLES}")
        if link.get("status") not in STATUSES:
            problems.append(f"{where}: status «{link.get('status')}» не из {STATUSES}")
        if link.get("status") == "verified" and not link.get("checked"):
            problems.append(f"{where}: verified без даты checked")
    for i, link in enumerate(meta.get("guidance_links") or []):
        where = f"guidance_links[{i}]"
        if not isinstance(link, dict) or not link.get("doc"):
            problems.append(f"{where}: нет поля doc")
            continue
        if link.get("norm") and not NORM_RE.match(str(link["norm"])):
            problems.append(f"{where}: ключ нормы не в едином формате: «{link['norm']}»")
        if link.get("status") not in STATUSES:
            problems.append(f"{where}: status «{link.get('status')}» не из {STATUSES}")
        if link.get("status") == "verified" and not link.get("checked"):
            problems.append(f"{where}: verified без даты checked")
    return problems


# ---------- извлечение упоминаний из текста ----------

_FULL_NAMES = (
    (r"Гражданского кодекса|ГК(?: РФ)?\b", "ГК РФ"),
    (r"Налогового кодекса|НК(?: РФ)?\b", "НК РФ"),
    (r"Кодекса Российской Федерации об административных правонарушениях|КоАП(?: РФ)?\b", "КоАП РФ"),
    (r"Арбитражного процессуального кодекса|АПК(?: РФ)?\b", "АПК РФ"),
    (r"Гражданского процессуального кодекса|ГПК(?: РФ)?\b", "ГПК РФ"),
    (r"Трудового кодекса|ТК(?: РФ)?\b", "ТК РФ"),
)
_ART = re.compile(r"(?:ст\.|статьи|статьей|статье|статья)\s*(\d+(?:\.\d+)*)")
_BEFORE = re.compile(
    r"(?:(?:пп\.|подп\.|подпункт[а-я]*)\s*(?P<pp>\d+(?:\.\d+)*)\s*)?"
    r"(?:(?P<pk>п\.|пункт[а-я]*|ч\.|част[а-я]*)\s*(?P<p>\d+(?:\.\d+)?)\s*)?$"
)
_LAW = re.compile(r"(?:№|N)\s*(\d+-ФЗ)|\b(\d+-ФЗ)\b|\bФЗ-(\d+)\b")
_CLAUSE = re.compile(r"^\*{0,2}(\d+(?:\.\d+)+)\.")


def _act_after(tail: str) -> str | None:
    tail = re.split(r"[;\n]|\)\s|\. [А-ЯЁ]", tail, maxsplit=1)[0]
    best: tuple[int, str] | None = None
    m = _LAW.search(tail)
    if m:
        best = (m.start(), m.group(1) or m.group(2) or f"{m.group(3)}-ФЗ")
    for pat, code in _FULL_NAMES:
        m = re.search(pat, tail)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), code)
    return best[1] if best else None


def extract_mentions(text: str) -> list[tuple[str, str]]:
    """Упоминания норм в тексте: список (ключ нормы, пункт формы или "").

    Пункт формы берется из номера в начале абзаца («6.1. …»). Ключ — в едином формате
    NORM_RE; в ГК, НК, ЗК часть статьи — «п.», в остальных кодексах — «ч.», в законах — как в тексте."""
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    clause = ""
    for line in text.splitlines():
        line = re.sub(r"(\d)[  ](\d{3})\b", r"\1\2", line)  # «ст. 1 235» с неразрывным пробелом
        m = _CLAUSE.match(line.strip())
        if m:
            clause = f"п. {m.group(1)}"
        for art in _ART.finditer(line):
            act = _act_after(line[art.end(): art.end() + 120])
            if not act:
                continue
            key = f"{act} ст. {art.group(1)}"
            before = _BEFORE.search(line[max(0, art.start() - 40): art.start()])
            if before and before.group("p"):
                if act in CODES_POINTS:
                    unit = "п."
                elif act in CODES:
                    unit = "ч."
                else:
                    unit = "ч." if before.group("pk").startswith("ч") else "п."
                key += f" {unit} {before.group('p')}"
            if before and before.group("pp"):
                key += f" пп. {before.group('pp')}"
            if not NORM_RE.match(key):
                continue
            item = (key, clause)
            if item not in seen:
                seen.add(item)
                found.append(item)
    return found


def article_key(norm: str) -> str:
    """Ключ до уровня статьи — для группировки и дедупликации («381-ФЗ ст. 9 ч. 4» → «381-ФЗ ст. 9»)."""
    m = re.match(rf"^({_ACT}(?: ст\. \d+(?:\.\d+)*)?)", norm)
    return m.group(1) if m else norm


# ---------- обратный указатель ----------

def _cell(value) -> str:
    s = "" if value is None else str(value)
    return s.replace("|", "/").replace("\n", " ").strip() or "—"


def build_norms_index(samples_root: str | Path) -> tuple[Path, dict[str, list[str]]]:
    """Собрать NORMS-INDEX.md. Возвращает путь и проблемы формата по карточкам."""
    sroot = Path(samples_root)
    cards = sroot / "cards"
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    grows: list[tuple[str, str, str, str, str]] = []
    problems: dict[str, list[str]] = {}
    for f in sorted(cards.glob("*/*.md")) if cards.exists() else []:
        meta = card_meta(f.read_text(encoding="utf-8", errors="replace"))
        bad = validate_links(meta)
        if bad:
            problems[f"{f.parent.name}/{f.stem}"] = bad
        for link in meta.get("norm_links") or []:
            if not isinstance(link, dict) or not link.get("norm"):
                continue
            check = " ".join(str(x) for x in (link.get("edition"), link.get("checked"), link.get("note")) if x)
            rows.append((article_key(str(link["norm"])), str(link["norm"]), f.stem, _cell(link.get("clause")),
                         ROLE_RU.get(link.get("role", "reference"), "—"),
                         STATUS_RU.get(link.get("status"), "—"), _cell(check)))
        for link in meta.get("guidance_links") or []:
            if not isinstance(link, dict) or not link.get("doc"):
                continue
            grows.append((_cell(link["doc"]), _cell(link.get("norm")), f.stem, _cell(link.get("clause")),
                          STATUS_RU.get(link.get("status"), "—")))
    out = [
        "# Указатель образцов по нормам\n\n"
        "> Генерируется `python tools/sample_intake/intake.py index` из полей `norm_links` и `guidance_links` "
        f"карточек ({date.today().isoformat()}). Руками не править. «не сверено» — упоминание найдено в тексте "
        "образца или карточки, текст нормы не открывался: навигация, не правовое основание.\n"
    ]
    verified = sum(1 for r in rows if r[5] == "сверено")
    out.append(f"\nСвязей с нормами: {len(rows)} (сверено {verified}), с разъяснениями и практикой: {len(grows)}.\n")
    current = None
    for art, norm, stem, clause, role, status, check in sorted(rows, key=lambda r: (r[0], r[1], r[5] != "сверено", r[2])):
        if art != current:
            out.append(f"\n## {art}\n\n| Норма | Образец | Пункт | Роль | Статус | Редакция, сверка |\n|---|---|---|---|---|---|\n")
            current = art
        out.append(f"| {norm} | [[{stem}]] | {clause} | {role} | {status} | {check} |\n")
    if grows:
        out.append("\n## Разъяснения и практика\n\n| Документ | Норма | Образец | Пункт | Статус |\n|---|---|---|---|---|\n")
        for doc, norm, stem, clause, status in sorted(grows):
            out.append(f"| {doc} | {norm} | [[{stem}]] | {clause} | {status} |\n")
    path = sroot / NORMS_INDEX_NAME
    path.write_text("".join(out), encoding="utf-8")
    return path, problems


# ---------- автозаполнение (unverified) ----------

def _docx_text(path: Path) -> str:
    import docx
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


def backfill(samples_root: str | Path, today: str | None = None, dry_run: bool = False) -> dict[str, int]:
    """Дописать в карточки упоминания норм из текста образца и карточки со статусом unverified.

    Уже записанные связи (на уровне статьи + пункт формы) не дублируются и не меняются."""
    sroot = Path(samples_root)
    today = today or date.today().isoformat()
    added: dict[str, int] = {}
    for card in sorted((sroot / "cards").glob("*/*.md")):
        text = card.read_text(encoding="utf-8")
        meta = card_meta(text)
        have = {(article_key(str(l.get("norm", ""))), str(l.get("clause") or ""))
                for l in meta.get("norm_links") or [] if isinstance(l, dict)}
        have_art = {a for a, _ in have}
        mentions: list[tuple[str, str]] = []
        orig_dir = sroot / "originals" / card.parent.name
        for ext in ("md", "docx"):
            src = orig_dir / f"{card.stem}.{ext}"
            if src.exists():
                body = src.read_text(encoding="utf-8", errors="replace") if ext == "md" else _docx_text(src)
                mentions += extract_mentions(body)
        body = text.split("\n---", 1)[1] if text.startswith("---") and "\n---" in text[3:] else text
        mentions += [(n, "") for n, _ in extract_mentions(body)]
        new: list[dict] = []
        for norm, clause in mentions:
            a = article_key(norm)
            if (a, clause) in have or (not clause and a in have_art):
                continue
            have.add((a, clause)); have_art.add(a)
            item = {"norm": norm}
            if clause:
                item["clause"] = clause
            item.update({"role": "reference", "status": "unverified", "source": f"автоизвлечение из текста {today}"})
            new.append(item)
        if not new:
            continue
        added[f"{card.parent.name}/{card.stem}"] = len(new)
        if dry_run:
            continue
        card.write_text(_append_links(text, "norm_links", new), encoding="utf-8")
    return added


def _yaml_item(item: dict) -> str:
    lines = []
    for i, (k, v) in enumerate(item.items()):
        val = v if k in ("role", "status", "checked") else '"' + str(v).replace('"', "'") + '"'
        lines.append(("  - " if i == 0 else "    ") + f"{k}: {val}")
    return "\n".join(lines)


def _append_links(text: str, field: str, items: list[dict]) -> str:
    """Добавить элементы в список `field` frontmatter (создать поле, если его нет)."""
    end = text.find("\n---", 3)
    head, tail = text[:end], text[end:]
    block = "\n".join(_yaml_item(i) for i in items)
    m = re.search(rf"^{field}:\s*\n((?:[ \t]+.*\n?|-.*\n?)*)", head + "\n", flags=re.M)
    if m:
        insert_at = m.end()
        merged = (head + "\n")[:insert_at].rstrip("\n") + "\n" + block + "\n" + (head + "\n")[insert_at:]
        return merged.rstrip("\n") + tail
    return head.rstrip("\n") + f"\n{field}:\n" + block + tail
