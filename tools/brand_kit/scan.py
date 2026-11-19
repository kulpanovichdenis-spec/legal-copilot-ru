# -*- coding: utf-8 -*-
"""Разбор папки фирменного стиля: бланки .docx/.dotx → черновик манифеста brand.yaml.

Детерминированный проход без LLM. Находит в каждом бланке места для заполнения
(поля MACROBUTTON, элементы управления содержимым, абзацы-подсказки) и предлагает
слоты по словарю. Предложение — черновик (status: draft): агент сверяет его с
превью бланка, юрист подтверждает (status: confirmed). Правила —
references/brand-letterhead.md.
"""

from __future__ import annotations

import datetime as dt
import re
import shutil
from pathlib import Path

import yaml
from docx.oxml.ns import qn

from .letterhead import SCHEMA, _bare, _norm, anchors, brand_root, open_blank

BLANK_EXT = (".docx", ".dotx")
SKIP_NAMES = {".gitkeep", "README.md", "Thumbs.db", "desktop.ini"}

# подпись поля-заполнителя → слот (для повторяющихся подписей — по порядку появления)
FIELD_SLOTS = {
    "дата": ["date"],
    "кому": ["addressee_name"],
    "адресат": ["addressee"],
    "организация": ["addressee_org"],
    "адрес": ["addressee_address"],
    "должность": ["addressee_position", "signer_position"],
    "заголовок письма": ["title"],
    "заголовок": ["title"],
    "тема": ["title"],
    "имя": ["salutation_name"],
    "имя отчество": ["salutation_name"],
    "обращение": ["salutation"],
    "текст": ["body"],
    "текст письма": ["body"],
    "фио": ["signer_name"],
    "подписант": ["signer_name"],
    "исполнитель": ["executor"],
    "телефон": ["executor_phone"],
    "номер": ["out_number"],
    "исх. номер": ["out_number"],
}

# абзац-подсказка → слот; prefix — подпись строки сохраняется при заполнении
TEXT_RULES = [
    (r"^указание адресата", "addressee", {}),
    (r"^адресат\b", "addressee", {}),
    (r"^заголовок( письма)?$", "title", {}),
    (r"^уважаем", "salutation", {}),
    (r"^_{3,}\s*№\s*_{3,}$", "reg_line", {"optional": True}),
    (r"^на №", "reply_to", {"optional": True}),
    (r"^исполнитель:?$", "executor", {"prefix": True}),
    (r"^(тел\.|телефон):?$", "executor_phone", {"prefix": True}),
    (r"^(почта|e-?mail|эл\. почта):?$", "executor_email", {"prefix": True}),
]

COMPANY_RE = re.compile(r"\b(?:ООО|АО|ПАО|ЗАО|ОАО|НАО|ИП)\s*«[^»]{2,80}»")


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "blank"
    slug, i = base, 2
    while slug in taken:
        slug, i = f"{base}_{i}", i + 1
    taken.add(slug)
    return slug


def _theme_font(doc) -> str | None:
    for rel in doc.part.rels.values():
        if rel.reltype.endswith("/theme"):
            m = re.search(rb'<a:minorFont><a:latin typeface="([^"]+)"', rel.target_part.blob)
            if m:
                return m.group(1).decode("utf8")
    return None


def _body_font(doc) -> dict:
    sizes = [r.font.size.pt for p in doc.paragraphs for r in p.runs if r.text.strip() and r.font.size]
    names = [r.font.name for p in doc.paragraphs for r in p.runs if r.text.strip() and r.font.name]
    normal = doc.styles["Normal"].font
    name = (max(set(names), key=names.count) if names else None) or normal.name or _theme_font(doc)
    size = (max(set(sizes), key=sizes.count) if sizes else None) or (normal.size.pt if normal.size else None)
    if size is None:
        dd = doc.styles.element.find(qn("w:docDefaults"))
        sz = dd.find(".//" + qn("w:sz")) if dd is not None else None
        size = int(sz.get(qn("w:val"))) / 2 if sz is not None else None
    return {"name": name, "size_pt": size}


def propose_slots(doc) -> tuple[dict, list[str]]:
    """Слоты по найденным местам. Возвращает (slots, found) — found для сверки агентом."""
    slots, found, field_seen = {}, [], {}
    all_anchors = anchors(doc)
    with_fields = {id(a["p"]) for a in all_anchors if a["kind"] in ("field", "sdt") and a["p"] is not None}
    text_seen: dict[str, int] = {}
    for a in all_anchors:
        label = a["label"].strip()
        if a["kind"] in ("field", "sdt"):
            found.append(f"{a['part']}: {a['kind']}: {label}")
            key = _bare(label)
            n = field_seen[key] = field_seen.get(key, 0) + 1
            names = FIELD_SLOTS.get(key)
            name = names[min(n, len(names)) - 1] if names else f"field_{len(slots) + 1}"
            if name in slots:
                name = f"{name}_{n}"
            spec = {"field": label}
            if n > 1:
                spec["nth"] = n
            if a["part"] != "body":
                spec["in"] = a["part"]
            if name == "body":
                spec.update({"mode": "replace", "align": "justify", "after_pt": 6, "keep_empty": 1})
            slots[name] = spec
            continue
        norm = _norm(label)
        if len(norm) > 200 or id(a["p"]) in with_fields:
            continue  # абзац с полями заполняется по полям, а не целиком
        for rx, name, extra in TEXT_RULES:
            if re.search(rx, norm) and name not in slots:
                key = label[:60]
                n = text_seen[_norm(key)] = text_seen.get(_norm(key), 0) + 1
                spec = {"text": key}
                if n > 1:
                    spec["nth"] = n
                if a["part"] != "body":
                    spec["in"] = a["part"]
                if extra.get("optional"):
                    spec["optional"] = True
                if extra.get("prefix"):
                    spec["prefix"] = label.rstrip() + " "
                nxt = a["p"].getnext()
                if name == "addressee" and nxt is not None and _norm(
                        "".join(t.text or "" for t in nxt.iter(qn("w:t")))).startswith("("):
                    spec["drop_next"] = 1
                slots[name] = spec
                found.append(f"{a['part']}: text: {label[:80]}")
                break
    if "body" not in slots and "salutation" in slots:
        sal = slots["salutation"]
        slots["body"] = {k: v for k, v in sal.items() if k in ("text", "field", "nth", "in")}
        slots["body"].update({"mode": "after", "align": "justify", "after_pt": 6, "keep_empty": 1})
    return slots, found


def _header_media(doc) -> bool:
    for s in doc.sections:
        for name in ("first_page_header", "header"):
            hf = getattr(s, name)
            if not hf.is_linked_to_previous and any(
                    r.reltype.endswith("/image") for r in hf.part.rels.values()):
                return True
    return False


def classify(path: Path, slots: dict, media: bool) -> str:
    """letterhead — бланк письма; form — фирменная форма другого назначения (оффер,
    анкета): в манифест попадает без назначения; other — не бланк."""
    name = path.as_posix().lower()
    if re.search(r"blank|бланк|letterhead|letter_?head", name) and "body" in slots:
        return "letterhead"
    if media and "body" in slots:
        return "form"
    return "other"


def describe_blank(path: Path, root: Path, taken: set[str]) -> dict:
    doc = open_blank(path)
    s = doc.sections[0]
    w, h = round(s.page_width.cm, 1), round(s.page_height.cm, 1)
    slots, found = propose_slots(doc)
    kind = classify(path.relative_to(root), slots, _header_media(doc))
    header_text = " ".join(a["label"] for a in anchors(doc) if a["part"] != "body" and a["kind"] == "text")
    landscape = w > h
    gost = "гост" in path.stem.lower() or "gost" in path.stem.lower()
    use_for = ([] if kind != "letterhead" else ["landscape"] if landscape else
               ["official_letter", "gov_response"] if gost else ["counterparty_letter", "business_letter"])
    entry = {
        "id": _slug(path.stem, taken),
        "kind": kind,
        "file": path.relative_to(root).as_posix(),
        "title": path.stem,
        "use_for": use_for,
        "orientation": "landscape" if landscape else "portrait",
        "page_cm": [w, h],
        "margins_cm": [round(x.cm, 2) for x in (s.left_margin, s.right_margin, s.top_margin, s.bottom_margin)],
        "first_page_differs": bool(s.different_first_page_header_footer),
        "font": _body_font(doc),
        "signature_in_blank": any(k.startswith("signer_") for k in slots),
        "slots": slots,
        "found": found,
    }
    m = COMPANY_RE.search(header_text.replace("\n", " "))
    entry["company_in_header"] = m.group(0) if m else None
    return entry


def _preview(path: Path, out: Path) -> str | None:
    pdf = path.with_suffix(".pdf")
    if not pdf.exists():
        return None
    try:
        import fitz
        out.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open(pdf) as d:
            d[0].get_pixmap(dpi=80).save(str(out))
        return out.as_posix()
    except Exception:
        return None


def move_inbox(root: Path) -> list[str]:
    inbox, originals = root / "_inbox", root / "originals"
    moved = []
    if not inbox.exists():
        return moved
    originals.mkdir(parents=True, exist_ok=True)
    for item in sorted(inbox.iterdir()):
        if item.name in SKIP_NAMES:
            continue
        dst = originals / item.name
        if dst.exists():
            dst = originals / f"{item.stem}_{dt.date.today():%Y%m%d}{item.suffix}"
        shutil.move(str(item), str(dst))
        moved.append(dst.relative_to(root).as_posix())
    return moved


def scan(root: Path | None = None, *, force: bool = False) -> dict:
    root = Path(root) if root else brand_root()
    moved = move_inbox(root)
    originals = root / "originals"
    files = sorted(p for p in originals.rglob("*")
                   if p.suffix.lower() in BLANK_EXT and not p.name.startswith("~$")) if originals.exists() else []
    other = {}
    if originals.exists():
        for p in originals.rglob("*"):
            if p.is_file() and p.suffix.lower() not in BLANK_EXT and p.name not in SKIP_NAMES:
                other[p.suffix.lower() or "(без расширения)"] = other.get(p.suffix.lower() or "(без расширения)", 0) + 1
    taken: set[str] = set()
    blanks, errors, other_docs = [], [], []
    for f in files:
        try:
            b = describe_blank(f, root, taken)
        except Exception as exc:  # битый файл не должен останавливать разбор остальных
            errors.append(f"{f.relative_to(root).as_posix()}: {exc}")
            continue
        if b["kind"] == "other":
            other_docs.append(b["file"])
            continue
        prev = _preview(f, root / "previews" / f"{b['id']}.png")
        if prev:
            b["preview"] = Path(prev).relative_to(root).as_posix()
        blanks.append(b)
    companies = [b["company_in_header"] for b in blanks if b.get("company_in_header")]
    letterheads = [b for b in blanks if b["kind"] == "letterhead"]
    default = next((b["id"] for b in letterheads if "counterparty_letter" in b["use_for"]),
                   letterheads[0]["id"] if letterheads else None)
    manifest = {
        "schema": SCHEMA,
        "status": "draft",
        "company": max(set(companies), key=companies.count) if companies else None,
        "scanned": dt.date.today().isoformat(),
        "default_blank": default,
        "blanks": blanks,
        "other_documents": other_docs,
        "other_assets": other,
    }
    target = root / "brand.yaml"
    if target.exists() and not force:
        target = root / "brand.draft.yaml"
    head = ("# Фирменный стиль: манифест бланков (brand_kit.v1). Черновик разбора — сверить слоты\n"
            "# с превью, поправить use_for/слоты и поставить status: confirmed (решение юриста).\n"
            "# Правила — references/brand-letterhead.md\n")
    target.write_text(head + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=110),
                      encoding="utf-8")
    return dict(manifest=target.as_posix(), moved=moved,
                blanks={b["id"]: b["kind"] for b in blanks}, default_blank=default,
                other_documents=other_docs, errors=errors, other_assets=other)
