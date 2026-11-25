"""Связи документов досье: amends (ДС изменяет договор или ДС), supersedes (документ заменяет другой
целиком), annex_to (приложение, спецификация к договору или ДС). Связь хранится в documents.yaml у
документа-источника и записывается только с дословной цитатой из него (FNM-CD-09)."""
from __future__ import annotations

from pathlib import Path

from tools.evidence_anchor.anchor import VERIFIED_CHECKS, check

from .dossier import _dump, dossier_dir, load_documents, reset_reviewed_card
from .paths import RegistryError

TYPES = ("amends", "supersedes", "annex_to")
ORDERED = ("amends", "supersedes")  # граф этих связей должен оставаться ациклическим
ANNEX_TARGET_KINDS = ("contract", "amendment", "disagreement_protocol")
ANNEX_KINDS = ("annex", "specification")
# Источник amends: ДС или протокол разногласий (протокол может изменять условия договора).
AMENDS_KINDS = ("amendment", "disagreement_protocol")
# Семейства видов для supersedes: документ заменяет только документ того же семейства.
FAMILY = {"contract": "contract", "disagreement_protocol": "contract", "amendment": "amendment",
          "annex": "annex", "specification": "annex"}
CARD_NOTE = "карточка возвращена в draft: изменились связи документов"


def _rels(doc: dict) -> list[dict]:
    return list(doc.get("relations") or [])


def _reaches(by_id: dict, start: str, goal: str, types: tuple[str, ...],
             stop: frozenset | set = frozenset()) -> bool:
    """Есть ли путь start → goal по исходящим связям указанных типов. Через документы из stop
    (кроме start и goal) путь не идёт."""
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        if cur == goal:
            return True
        if cur in seen or (cur != start and cur in stop):
            continue
        seen.add(cur)
        stack += [r.get("target") for r in _rels(by_id.get(cur, {})) if r.get("type") in types]
    return False


def _kind_error(by_id: dict, doc: str, type: str, target: str) -> str:  # noqa: A002
    """Текст ошибки вида документов для связи или пустая строка."""
    sk, tk = by_id[doc].get("kind"), by_id[target].get("kind")
    if type == "amends" and sk not in AMENDS_KINDS:
        return f"amends: {doc} вида {sk}, а изменять договор или ДС может только {AMENDS_KINDS}"
    if type == "annex_to":
        if sk not in ANNEX_KINDS:
            return f"annex_to: {doc} вида {sk}, а приложением бывает только {ANNEX_KINDS}"
        if tk not in ANNEX_TARGET_KINDS:
            return f"annex_to: {target} вида {tk}, а приложение бывает только к {ANNEX_TARGET_KINDS}"
    if type == "supersedes" and FAMILY.get(sk, sk) != FAMILY.get(tk, tk):
        return (f"supersedes: {doc} вида {sk} не может заменять {target} вида {tk} "
                "(договор заменяет договор, ДС — ДС, приложение или спецификация — приложение или спецификацию)")
    return ""


def superseded_by_signed(docs: list[dict]) -> dict[str, list[str]]:
    """id документа → id подписанных документов, которые заменяют его целиком."""
    out: dict[str, list[str]] = {}
    for doc in docs:
        if doc.get("status") != "signed":
            continue
        for r in _rels(doc):
            if r.get("type") == "supersedes":
                out.setdefault(r.get("target"), []).append(doc["id"])
    return out


def supersedes_original(by_id: dict, doc: str, orig: str, replaced: dict) -> bool:
    """Документ doc относится к подписанной незаменённой редакции, которая заменяет orig (прямо или через
    цепочку supersedes): doc сам такая редакция или сводится к ней по amends/supersedes."""
    if doc not in by_id or doc in replaced or by_id[doc].get("status") != "signed":
        return False
    editions = [n for n, x in by_id.items() if n != orig and n not in replaced and x.get("status") == "signed"
                and _reaches(by_id, n, orig, ("supersedes",))]
    return any(_reaches(by_id, doc, n, ORDERED) for n in editions)


def _quote_check(d: Path, doc: dict, quote: str) -> str:
    from .card import _quote_too_short  # noqa: PLC0415 — card импортирует links, links импортирует dossier
    if not str(quote or "").strip():
        raise RegistryError("связь без цитаты не записывается: нужна дословная цитата из документа-источника")
    if _quote_too_short(quote):
        raise RegistryError("цитата связи слишком короткая (нужно не меньше 3 слов или 15 символов)")
    res = check(d / doc["text"], quote)
    if res["quote_check"] not in VERIFIED_CHECKS:
        raise RegistryError(f"цитата не подтверждена в {doc['id']}: {res['quote_check']} {res['detail']}")
    return res["quote_check"]


def _save(d: Path, docs: list[dict]) -> dict:
    _dump(d / "documents.yaml", {"version": 1, "documents": docs})
    note = reset_reviewed_card(d, CARD_NOTE)
    return {"card_note": note} if note else {}


def link_doc(root, key, *, doc: str, type: str, target: str, quote: str) -> dict:  # noqa: A002
    if type not in TYPES:
        raise RegistryError(f"type должен быть из {TYPES}")
    d = dossier_dir(root, key)
    docs = load_documents(d)
    by_id = {x["id"]: x for x in docs}
    for i in (doc, target):
        if i not in by_id:
            raise RegistryError(f"{i} нет в documents.yaml")
    if doc == target:
        raise RegistryError(f"{doc} не может ссылаться сам на себя")
    src = by_id[doc]
    if any(r.get("type") == type and r.get("target") == target for r in _rels(src)):
        raise RegistryError(f"связь {doc} {type} {target} уже есть")
    kind_err = _kind_error(by_id, doc, type, target)
    if kind_err:
        raise RegistryError(kind_err)
    if type in ORDERED and _reaches(by_id, target, doc, ORDERED):
        raise RegistryError(f"связь {doc} {type} {target} создаёт цикл amends/supersedes")
    rel = {"type": type, "target": target, "quote": quote, "quote_check": _quote_check(d, src, quote)}
    src["relations"] = [*_rels(src), rel]
    return {"doc": doc, "relation": rel, **_save(d, docs)}


def unlink_doc(root, key, *, doc: str, type: str, target: str) -> dict:  # noqa: A002
    d = dossier_dir(root, key)
    docs = load_documents(d)
    src = next((x for x in docs if x.get("id") == doc), None)
    if src is None:
        raise RegistryError(f"{doc} нет в documents.yaml")
    rels = _rels(src)
    keep = [r for r in rels if not (r.get("type") == type and r.get("target") == target)]
    if len(keep) == len(rels):
        raise RegistryError(f"связи {doc} {type} {target} нет")
    if keep:
        src["relations"] = keep
    else:
        src.pop("relations", None)
    return {"doc": doc, "removed": {"type": type, "target": target}, **_save(d, docs)}


def chain(root, key) -> dict:
    """Цепочка редакций: главные документы (без исходящих связей или только с supersedes; у таких
    `supersedes` — кого заменяют), для каждого его ДС по дате (без даты — после датированных) и id
    со статусом и признаком замены, приложения по документам и связи замены. Рядом с каждой связью её
    цитата (`relations` у главного документа и ДС, `quote` у приложений и замен): юрист видит, что цитата
    называет цель. В цепочку главного документа не идут документы, которые сводятся к нему только через
    другой главный документ. Приложения и спецификации без связей — в `unlinked`."""
    d = dossier_dir(root, key)
    docs = load_documents(d)
    by_id = {x["id"]: x for x in docs}
    sup = superseded_by_signed(docs)
    def only_supersedes(x: dict) -> bool:
        return all(rel.get("type") == "supersedes" for rel in _rels(x))

    # Главный документ — договор или протокол разногласий без связей либо только с supersedes
    # (новая редакция). ДС, заменяющий другой ДС, остаётся в цепочке своего договора.
    roots = [x for x in docs if x.get("kind") not in ANNEX_KINDS and x.get("kind") != "amendment"
             and only_supersedes(x)]
    root_ids = {r["id"] for r in roots}

    def belongs(x: dict, r: dict) -> bool:
        # Через supersedes в другой главный документ не идём: ДС к новой редакции не попадает
        # в цепочку заменённого договора, а сама новая редакция идёт отдельным главным документом.
        return x["id"] not in root_ids and _reaches(by_id, x["id"], r["id"], TYPES, stop=root_ids)

    def rel_view(x: dict) -> list[dict]:
        return [{"type": rel.get("type"), "target": rel.get("target"), "quote": rel.get("quote", "")}
                for rel in _rels(x)]

    attached = {x["id"] for x in docs for r in roots if x is r or belongs(x, r)}
    unlinked = [{"doc": x["id"], "kind": x.get("kind"), "status": x.get("status")}
                for x in docs if x["id"] not in attached]
    out = []
    for r in roots:
        members = [x for x in docs if belongs(x, r)]
        amend_docs = [x for x in members if x.get("kind") == "amendment"
                      or any(rel.get("type") == "amends" for rel in _rels(x))]
        amend_docs.sort(key=lambda x: (not x.get("date"), str(x.get("date") or ""), x["id"]))
        annexes: dict[str, list[dict]] = {}
        supersessions = []
        for x in [r, *members]:
            for rel in _rels(x):
                if rel.get("type") == "annex_to":
                    annexes.setdefault(rel["target"], []).append({"doc": x["id"], "quote": rel.get("quote", "")})
                elif rel.get("type") == "supersedes":
                    supersessions.append({"doc": x["id"], "supersedes": rel["target"], "status": x.get("status"),
                                          "quote": rel.get("quote", "")})
        out.append({
            "doc": r["id"], "kind": r.get("kind"), "status": r.get("status"), "date": r.get("date", ""),
            "superseded": r["id"] in sup, "superseded_by": sup.get(r["id"], []),
            "supersedes": [rel["target"] for rel in _rels(r)],
            "relations": rel_view(r),
            "amendments": [{"doc": x["id"], "date": x.get("date", ""), "status": x.get("status"),
                            "amends": [rel["target"] for rel in _rels(x) if rel.get("type") == "amends"],
                            "relations": rel_view(x),
                            "superseded": x["id"] in sup, "superseded_by": sup.get(x["id"], [])}
                           for x in amend_docs],
            "annexes": annexes,
            "supersessions": supersessions,
        })
    return {"contracts": out, "unlinked": unlinked}


def validate(root, key) -> tuple[list[str], list[str]]:
    """(ошибки, предупреждения). Ошибки: неизвестный тип или документ, связь на себя, дубль связи,
    цикл amends/supersedes, вид документов не подходит связи (amends, annex_to, supersedes), цитата связи
    не подтверждена. Предупреждения: ДС без исходящих связей; ДС из карты изменений без пути amends или
    supersedes к исходному документу пункта; приложение или спецификация без annex_to."""
    d = dossier_dir(root, key)
    docs = load_documents(d)
    by_id = {x["id"]: x for x in docs}
    errs, warns = [], []
    for doc in docs:
        pairs = set()
        for rel in _rels(doc):
            t, tgt = rel.get("type"), rel.get("target")
            where = f"связь {doc['id']} {t} {tgt}"
            if (t, tgt) in pairs:
                errs.append(f"{where}: дубль связи")
                continue
            pairs.add((t, tgt))
            if t not in TYPES:
                errs.append(f"{where}: неизвестный тип")
                continue
            if tgt not in by_id:
                errs.append(f"{where}: {tgt} нет в documents.yaml")
                continue
            if tgt == doc["id"]:
                errs.append(f"{where}: документ ссылается сам на себя")
            kind_err = _kind_error(by_id, doc["id"], t, tgt)
            if kind_err:
                errs.append(f"{where}: {kind_err}")
            if t in ORDERED and _reaches(by_id, tgt, doc["id"], ORDERED):
                errs.append(f"{where}: цикл amends/supersedes")
            try:
                _quote_check(d, doc, rel.get("quote", ""))
            except (RegistryError, OSError) as exc:
                errs.append(f"{where}: цитата не подтверждена ({exc})")
        if doc.get("kind") in ANNEX_KINDS and not any(r.get("type") == "annex_to" for r in _rels(doc)):
            warns.append(f"Приложение {doc['id']} не связано отношением annex_to с договором или ДС")
        if doc.get("kind") == "amendment" and not _rels(doc):
            warns.append(f"ДС {doc['id']} ни с чем не связан")
    from .amendments import _load  # noqa: PLC0415 — amendments импортирует relations
    seen = set()
    for c in _load(d).get("clauses", []):
        orig = c["original"]["doc"]
        for ch in c.get("changes", []):
            src = ch["doc"]
            if (src, orig) in seen or by_id.get(src, {}).get("kind") != "amendment":
                continue
            seen.add((src, orig))
            if not _reaches(by_id, src, orig, ORDERED):
                warns.append(f"ДС {src} не связан с {orig} через amends или supersedes")
    return errs, warns
