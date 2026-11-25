"""Карта изменённых пунктов: исходная редакция → изменения → текущая (только из signed)."""
from __future__ import annotations

from pathlib import Path

import yaml

from tools.evidence_anchor.anchor import VERIFIED_CHECKS, check

from .dossier import _dump, dossier_dir, load_documents
from .paths import RegistryError


def _load(d: Path) -> dict:
    return yaml.safe_load((d / "amendments.yaml").read_text(encoding="utf-8"))


def _docs(d: Path) -> dict:
    return {doc["id"]: doc for doc in load_documents(d)}


def _anchored(d: Path, doc_id: str, quote: str, location: str) -> str:
    docs = _docs(d)
    if doc_id not in docs:
        raise RegistryError(f"{doc_id} нет в documents.yaml")
    # Инвариант FNM-CD-03 — дословность цитаты. Место (location) хранится как указано, но в проверку
    # не передаётся: эвристика заголовков evidence_anchor даёт ложный location_mismatch на нумерации договоров.
    res = check(d / docs[doc_id]["text"], quote)
    if res["quote_check"] not in VERIFIED_CHECKS:
        raise RegistryError(f"цитата не подтверждена в {doc_id}: {res['quote_check']} {res['detail']}")
    return res["quote_check"]


def add_clause(root, key, *, clause: str, doc_id: str, quote: str, location: str) -> dict:
    d = dossier_dir(root, key)
    data = _load(d)
    if any(c["clause"] == clause for c in data["clauses"]):
        raise RegistryError(f"пункт {clause} уже в карте")
    qc = _anchored(d, doc_id, quote, location)
    item = {"clause": clause, "original": {"doc": doc_id, "quote": quote, "location": location, "quote_check": qc},
            "changes": []}
    data["clauses"].append(item)
    _dump(d / "amendments.yaml", data)
    return item


def add_change(root, key, *, clause: str, doc_id: str, quote: str, location: str, date: str = "") -> dict:
    d = dossier_dir(root, key)
    data = _load(d)
    item = next((c for c in data["clauses"] if c["clause"] == clause), None)
    if item is None:
        raise RegistryError(f"пункта {clause} нет в карте: сначала add-clause с исходной редакцией")
    qc = _anchored(d, doc_id, quote, location)
    change = {"doc": doc_id, "date": date, "quote": quote, "location": location, "quote_check": qc}
    item["changes"].append(change)
    _dump(d / "amendments.yaml", data)
    return change


def current(root, key) -> list[dict]:
    from .relations import superseded_by_signed, supersedes_original  # noqa: PLC0415 — relations импортирует amendments
    d = dossier_dir(root, key)
    docs = _docs(d)
    replaced = superseded_by_signed(list(docs.values()))
    out = []
    def status(doc_id: str) -> str:
        return docs.get(doc_id, {}).get("status", "missing")

    for c in _load(d)["clauses"]:
        # Порядок changes это хронология изменений: действует последнее из signed.
        # Исходная редакция из неподписанного документа действующей не считается (FNM-CD-02).
        # Изменение из документа, заменённого подписанным документом, не действует (FNM-CD-09).
        cur = c["original"]
        pending = [] if status(cur["doc"]) == "signed" else [cur["doc"]]
        superseded = [cur["doc"]] if cur["doc"] in replaced else []
        for ch in c["changes"]:
            if ch["doc"] in replaced:
                superseded.append(ch["doc"])
            elif status(ch["doc"]) == "signed":
                cur, pending = ch, []
            else:
                pending.append(ch["doc"])
        # Заменён документ исходной редакции. Текст из подписанной незаменённой новой редакции (или из ДС
        # к ней), которая заменяет исходный документ: это действующая редакция, source_status signed, а
        # исходный документ в superseded не идёт. Иначе текст из заменённой редакции: source_status superseded.
        orig = c["original"]["doc"]
        if orig in replaced and supersedes_original(docs, cur["doc"], orig, replaced):
            superseded = [x for x in superseded if x != orig]
            src_status = status(cur["doc"])
        elif orig in replaced or cur["doc"] in replaced:
            src_status = "superseded"
        else:
            src_status = status(cur["doc"])
        out.append({"clause": c["clause"], "text": cur["quote"], "source": cur["doc"],
                    "source_status": src_status,
                    "location": cur["location"], "quote_check": cur.get("quote_check", "not_checked"),
                    "pending": pending, "superseded": superseded})
    return out


def validate(root, key) -> list[str]:
    d = dossier_dir(root, key)
    docs = _docs(d)
    errs = []
    for c in _load(d)["clauses"]:
        for rec in [c["original"], *c["changes"]]:
            where = f"п. {c['clause']} / {rec['doc']}"
            if rec["doc"] not in docs:
                errs.append(f"{where}: документа нет в documents.yaml")
            if rec.get("quote_check") not in VERIFIED_CHECKS:
                errs.append(f"{where}: цитата не подтверждена ({rec.get('quote_check')})")
    return errs
