"""contract-card.md: форма (frontmatter, разделы), опора каждого поля на документ (FNM-CD-08),
сводка для юриста и статус проверки карточки."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from tools.evidence_anchor.anchor import VERIFIED_CHECKS, check

from .paths import RegistryError

REQUIRED_FM = ("key", "counterparty", "our_party", "number", "date", "aliases", "card_status")
REQUIRED_SECTIONS = ("Стороны", "Предмет", "Цена и порядок оплаты", "Срок действия и пролонгация",
                     "Уведомления", "Применимое право и споры", "Ответственность и неустойки",
                     "Определённые термины", "Предупреждения")
NO_REF_SECTIONS = ("Предупреждения",)
# Ключевые разделы: у каждой ссылки D-00N пункта дословная цитата обязательна (FNM-CD-08).
QUOTE_SECTIONS = ("Стороны", "Цена и порядок оплаты", "Срок действия и пролонгация",
                  "Ответственность и неустойки", "Применимое право и споры")
# Минимальная цитата в ключевом разделе после нормализации: «рублей» ничего не подтверждает.
MIN_QUOTE_WORDS, MIN_QUOTE_CHARS = 3, 15
CARD_STATUSES = ("draft", "reviewed")
MARKER = "[ПРОВЕРИТЬ"
CHANGED_AFTER_REVIEW = "карточка изменена после проверки юристом: верните draft и покажите summary юристу"

_BULLET = re.compile(r"^\s*-\s+(.*\S)\s*$")
_REF = re.compile(r"D-\d{3}")


# ---------- frontmatter ----------

def _is_fence(line: bytes) -> bool:
    return line.rstrip(b"\r\n").rstrip(b" \t") == b"---"


def _fm_span(raw: bytes) -> tuple[int, int, int] | str:
    """(начало frontmatter, начало закрывающей строки ---, конец закрывающей строки) или текст ошибки.
    Ограничители ищутся как целые строки, как в links.py."""
    lines = raw.splitlines(keepends=True)
    if not lines or not _is_fence(lines[0]):
        return "нет frontmatter"
    pos = len(lines[0])
    for ln in lines[1:]:
        if _is_fence(ln):
            return len(lines[0]), pos, pos + len(ln)
        pos += len(ln)
    return "frontmatter: нет закрывающей ---"


def parse(raw: bytes) -> tuple[dict, str, bytes] | str:
    """(frontmatter, тело, байты тела) или текст ошибки. Не бросает исключений."""
    span = _fm_span(raw)
    if isinstance(span, str):
        return span
    start, close, end = span
    try:
        fm = yaml.safe_load(raw[start:close].decode("utf-8"))
        body = raw[end:].decode("utf-8")
    except UnicodeDecodeError:
        return "карточка не в UTF-8"
    except yaml.YAMLError as exc:
        return f"frontmatter: ошибка YAML ({str(exc).splitlines()[0]})"
    if fm is None:
        fm = {}
    if not isinstance(fm, dict):
        return "frontmatter: должен быть словарём «поле: значение»"
    return fm, body, raw[end:]


HASHED_FM = ("counterparty", "our_party", "number", "date", "aliases", "key")


def factual_fm(fm: dict) -> dict:
    return {k: fm.get(k) for k in HASHED_FM}


def body_hash(body: bytes, fm: dict | None = None) -> str:
    """sha256 от канонической записи фактических полей frontmatter (без card_status и reviewed_hash)
    и байтов тела: правка стороны, номера или даты после reviewed тоже видна."""
    canon = json.dumps(factual_fm(fm or {}), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8") + b"\n---\n" + body).hexdigest()


def set_fm_field(path: Path, field: str, value: str | None) -> bool:
    """Меняет (или удаляет при value=None, или дописывает перед закрывающей ---) одну строку
    `field: value` во frontmatter; остальные байты файла не трогаются. Возвращает, изменён ли файл."""
    path = Path(path)
    raw = path.read_bytes()
    span = _fm_span(raw)
    if isinstance(span, str):
        raise RegistryError(f"{path}: {span}")
    start, close, _ = span
    line_re = re.compile(rb"^" + re.escape(field.encode("utf-8")) + rb":[^\r\n]*(\r?\n)?", re.M)
    m = line_re.search(raw, start, close)
    eol = b"\r\n" if b"\r\n" in raw[:close] else b"\n"
    if value is None:
        if m is None:
            return False
        new = raw[:m.start()] + raw[m.end():]
    else:
        line = f"{field}: {value}".encode("utf-8")
        if m is None:
            new = raw[:close] + line + eol + raw[close:]
        else:
            if m.group(0).rstrip(b"\r\n") == line:
                return False
            new = raw[:m.start()] + line + (m.group(1) or b"") + raw[m.end():]
    from .links import _atomic_write  # noqa: PLC0415 — links импортирует dossier, держим граф простым
    _atomic_write(path, new)
    return True


# ---------- проверка пунктов ----------

def _load_docs(dossier: Path) -> dict:
    p = dossier / "documents.yaml"
    if not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {doc["id"]: doc for doc in data.get("documents", [])}


def _load_links(dossier: Path) -> dict:
    p = dossier / "links.yaml"
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _quote_after(line: str, m: re.Match) -> str | None:
    """Цитата «…» сразу после ссылки D-00N (до следующей ссылки); вложенные кавычки допускаются."""
    nxt = _REF.search(line, m.end())
    tail = line[m.end():nxt.start() if nxt else len(line)]
    start, end = tail.find("«"), tail.rfind("»")
    if start < 0 or end <= start:
        return None
    return tail[start + 1:end]


def _quote_too_short(quote: str) -> bool:
    norm = " ".join(quote.split()).strip(" .,;:!?«»\"'")
    return len(norm.split()) < MIN_QUOTE_WORDS and len(norm) < MIN_QUOTE_CHARS


def _check_bullets(body: str, dossier: Path, docs: dict) -> list[str]:
    from .relations import superseded_by_signed  # noqa: PLC0415 — relations импортирует card
    replaced = superseded_by_signed(list(docs.values()))
    errs, section = [], None
    for line in body.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section is None or section in NO_REF_SECTIONS:
            continue
        m = _BULLET.match(line)
        if not m:
            if line.strip():
                errs.append(f"«{section}»: {line.strip()[:60]}: поле не в формате пункта списка")
            continue
        item = m.group(1)
        where = f"«{section}»: {item[:60]}"
        refs = list(_REF.finditer(item))
        if not refs:
            if MARKER not in item:
                errs.append(f"{where}: нет ссылки на документ D-00N и нет маркера [ПРОВЕРИТЬ …]")
            continue
        for r in refs:
            ref = r.group(0)
            quote = _quote_after(item, r)
            if section in QUOTE_SECTIONS:
                if quote is None:
                    errs.append(f"{where}: нет дословной цитаты у ключевого поля после {ref}")
                elif _quote_too_short(quote):
                    errs.append(f"{where}: цитата после {ref} слишком короткая "
                                f"(нужно не меньше {MIN_QUOTE_WORDS} слов или {MIN_QUOTE_CHARS} символов)")
            doc = docs.get(ref)
            if doc is None:
                errs.append(f"{where}: {ref} нет в documents.yaml")
                continue
            if doc.get("status") != "signed" and MARKER not in item:
                errs.append(f"{where}: поле опирается на неподписанный документ {ref}: нужен маркер")
            if ref in replaced and MARKER not in item:
                errs.append(f"{where}: поле опирается на заменённый документ {ref}: нужен маркер")
            if quote is None:
                continue
            res = check(dossier / doc["text"], quote)
            if res["quote_check"] not in VERIFIED_CHECKS:
                errs.append(f"{where}: цитата не подтверждена в {ref} ({res['quote_check']})")
    return errs


def _review_errors(fm: dict, body_raw: bytes) -> list[str]:
    stored = fm.get("reviewed_hash")
    if fm.get("card_status") == "reviewed" and stored and stored != body_hash(body_raw, fm):
        return [CHANGED_AFTER_REVIEW]
    return []


def validate_card(path: Path, docs: dict | None = None, key: str | None = None) -> list[str]:
    """Ошибки карточки списком; исключений не бросает (битый файл тоже ошибка, а не трассировка)."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [f"{path}: не читается ({exc})"]
    parts = parse(raw)
    if isinstance(parts, str):
        return [f"{path.name}: {parts}"]
    fm, body, body_raw = parts
    errs = [f"frontmatter: нет поля {k}" for k in REQUIRED_FM if k not in fm]
    if fm.get("card_status") not in CARD_STATUSES:
        errs.append("frontmatter: card_status должен быть draft или reviewed")
    if key is not None and "key" in fm and str(fm.get("key")) != key:
        errs.append(f"frontmatter: key «{fm.get('key')}» не совпадает с ключом реестра «{key}»")
    errs += _review_errors(fm, body_raw)
    heads = {line[3:].strip() for line in body.splitlines() if line.startswith("## ")}
    errs += [f"нет раздела «{s}»" for s in REQUIRED_SECTIONS if s not in heads]
    try:
        if docs is None:
            docs = _load_docs(path.parent)
        errs += _check_bullets(body, path.parent, docs)
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        errs.append(f"не удалось сверить пункты карточки: {exc}")
    return errs


def _fields(body: str) -> list[dict]:
    """Пункты карточки как написаны: юрист видит значение, ссылку и цитату."""
    out, section = [], None
    for line in body.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = _BULLET.match(line)
        if m and section is not None:
            out.append({"section": section, "text": m.group(1)})
    return out


def _open_conflicts(dossier: Path) -> list[dict]:
    return [k for k in _load_links(dossier).get("conflicts", []) if k.get("status") == "open"]


def summary(dossier: Path) -> dict:
    """Предпросмотр для юриста: поля карточки, документы со статусом, датой, признаком подписания и
    superseded_by (подписанные документы, которые заменяют его целиком),
    связи документов (relations: id → список связей), маркеры, открытые расхождения, предупреждения о карточке."""
    dossier = Path(dossier)
    raw = (dossier / "contract-card.md").read_bytes()
    text = raw.decode("utf-8", "replace")
    parts = parse(raw)
    warnings = []
    if isinstance(parts, str):
        fm, body = {}, ""
        warnings.append(parts)
    else:
        fm, body, body_raw = parts
        warnings += _review_errors(fm, body_raw)
    docs = _load_docs(dossier)
    from .relations import superseded_by_signed  # noqa: PLC0415 — relations импортирует card
    replaced = superseded_by_signed(list(docs.values()))
    return {
        "dossier": dossier.name,
        "card_status": fm.get("card_status"),
        "frontmatter": factual_fm(fm),
        "warnings": warnings,
        "fields": _fields(body),
        "documents": [{**{k: doc.get(k, "") for k in ("id", "file", "kind", "status", "date", "evidence")},
                       "superseded_by": replaced.get(doc["id"], [])}
                      for doc in docs.values()],
        "relations": {i: list(doc["relations"]) for i, doc in docs.items() if doc.get("relations")},
        "markers": text.count(MARKER),
        "open_conflicts": _open_conflicts(dossier),
    }


def set_card_status(path: Path, status: str, key: str | None = None,
                    extra_errors: list[str] | None = None) -> dict:
    """Меняет card_status во frontmatter, остальные байты тела не трогаются. reviewed: только для
    карточки без ошибок validate и без открытых расхождений (extra_errors: ошибки остальной проверки досье,
    их собирает вызывающий: CLI передаёт результат полного validate); хеш полей и тела пишется в reviewed_hash.
    draft: reviewed_hash удаляется."""
    if status not in CARD_STATUSES:
        raise RegistryError(f"status должен быть из {CARD_STATUSES}")
    path = Path(path)
    parts = parse(path.read_bytes())
    if isinstance(parts, str):
        raise RegistryError(f"{path}: {parts}")
    fm, _, body_raw = parts
    if "card_status" not in fm:
        raise RegistryError(f"{path}: во frontmatter нет card_status")
    if status == "reviewed":
        errs = [e for e in validate_card(path, key=key) + list(extra_errors or [])
                if e != CHANGED_AFTER_REVIEW]
        if errs:
            raise RegistryError("reviewed не ставится: карточка с ошибками validate: " + "; ".join(errs))
        conflicts = _open_conflicts(path.parent)
        if conflicts:
            raise RegistryError("reviewed не ставится: открытые расхождения "
                                + ", ".join(str(k.get("id")) for k in conflicts))
        changed = set_fm_field(path, "reviewed_hash", body_hash(body_raw, fm))
    else:
        changed = set_fm_field(path, "reviewed_hash", None)
    changed = set_fm_field(path, "card_status", status) or changed
    return {"card_status": status, "result": "updated" if changed else "already"}
