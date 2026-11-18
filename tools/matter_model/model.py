#!/usr/bin/env python3
"""Matter model — timeline: machine-readable chronology of a matter (pilot core).

Реализует MVP-пилот структурного слоя дела : один
машиночитаемый артефакт `matter-timeline.yaml` в папке дела внутри workflow/ и
детерминированный Python-тул к нему — по образцу tools/deadline_tracker.

Что делает тул (детерминированное, low-freedom — architecture-first):
- validate  — проверяет схему yaml и обязательную traceability каждого события
              (source_doc + source_fragment) и словарь fact_status;
- report    — сортирует хронологию по дате и печатает markdown-сводку, а также
              КАНДИДАТОВ в противоречия/двойной счёт (формальный детект);
- add/update/init — ведение файла (как в deadline_tracker).

Разделение LLM vs код (из ТЗ, §4):
- ИЗВЛЕЧЕНИЕ событий/фактов из документов, их юридическая квалификация и ОЦЕНКА
  противоречий — работа агента/юриста, НЕ этого скрипта.
- Скрипт лишь валидирует схему, сортирует, ищет ФОРМАЛЬНЫЕ совпадения
  (один и тот же (место, сумма) в разных событиях → кандидат двойного счёта;
  одна claim_key с расходящимся fact_status → кандидат противоречия) и рендерит
  сводку. Кандидат — это лид для юриста, НЕ утверждённое противоречие.

Инварианты (не сокращаются):
- fact_status берётся из fact-matrix (references/legal-opinion-method.md), один
  источник истины: CONFIRMED / REPORTED / INFERRED / DISPUTED / UNKNOWN / ASSUMED.
- traceability обязательна: событие без source_doc + source_fragment не вносится
  (иначе хронология не переиспользуема и не проверяема).
- date_status=confirmed требует непустую date; иначе событие идёт как
  needs_check и рендерится с маркером [ПРОВЕРИТЬ СРОК] (как в deadline_tracker).
- любой fact_status != CONFIRMED рендерится с маркером [ПРОВЕРИТЬ ФАКТ].
- файл не удаляется; события закрываются статусом, а не удалением.

Usage:
    python tools/matter_model/model.py init   --file PATH --matter NAME
    python tools/matter_model/model.py add     --file PATH --event T
        --source-doc D --source-fragment F --fact-status STATUS
        [--date YYYY-MM-DD] [--date-status confirmed|needs_check]
        [--participant ...] [--location ...] [--amount N]
        [--claim-key K] [--notes ...]
    python tools/matter_model/model.py update  --file PATH --id T-001 [...]
    python tools/matter_model/model.py validate --file PATH
    python tools/matter_model/model.py report   --file PATH
    python tools/matter_model/model.py selftest
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from tools.evidence_anchor import anchor as evidence_anchor  # noqa: E402

# Windows-консоль по умолчанию cp1251 — кириллица и значки отчёта ломаются.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SCHEMA_VERSION = 1
# Словарь статусов факта — из fact-matrix (references/legal-opinion-method.md).
# Единый источник истины; здесь НЕ расширяется без правки reference.
FACT_STATUSES = ("CONFIRMED", "REPORTED", "INFERRED", "DISPUTED", "UNKNOWN", "ASSUMED")
DATE_STATUSES = ("confirmed", "needs_check")
DATE_CHECK = "[ПРОВЕРИТЬ СРОК]"
FACT_CHECK = "[ПРОВЕРИТЬ ФАКТ]"


class ModelError(Exception):
    pass


# ---------- якорь доказательства (Т3: дословная цитата + место + проверка) ----------

UNANCHORED = "CONFIRMED без подтверждённой цитаты (anchor.quote_check ≠ matched/ocr_fuzzy)"


def build_anchor(source_doc: str, quote: str | None, quote_location: str | None,
                 base_dir: Path) -> dict | None:
    """Якорь с немедленной проверкой цитаты по источнику; None — цитата не дана."""
    if not (quote or "").strip():
        return None
    return evidence_anchor.make_anchor(source_doc, quote, quote_location, base_dir)


def enforce_confirmed(item: dict) -> bool:
    """Решение юриста 2026-10-13: CONFIRMED без проверенной цитаты понижается до REPORTED.

    Пишет переход в status_history. True — если понижено.
    """
    if item.get("fact_status") != "CONFIRMED" or evidence_anchor.is_verified(item.get("anchor")):
        return False
    item["fact_status"] = "REPORTED"
    item.setdefault("status_history", []).append({
        "from": "CONFIRMED", "to": "REPORTED", "date": dt.date.today().isoformat(),
        "reason": UNANCHORED,
    })
    return True


def anchor_note(item: dict) -> str:
    a = item.get("anchor")
    if not isinstance(a, dict):
        return ""
    loc = f", {a['location']}" if a.get("location") else ""
    return f" · цитата: «{a.get('quote')}»{loc} [{a.get('quote_check', 'not_checked')}]"


# ---------- storage ----------

def load(path: Path) -> dict:
    if not path.exists():
        raise ModelError(f"timeline не найден: {path} (сначала init)")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "events" not in data:
        raise ModelError(f"файл не похож на matter-timeline: {path}")
    return data


def save(path: Path, data: dict) -> None:
    data["updated"] = dt.date.today().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def parse_date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError as e:
        raise ModelError(f"дата должна быть в формате YYYY-MM-DD: {s!r}") from e


def parse_amount(s) -> float | None:
    if s is None or s == "":
        return None
    try:
        val = float(str(s).replace(" ", "").replace(",", "."))
    except ValueError as e:
        raise ModelError(f"amount должен быть числом: {s!r}") from e
    if val < 0:
        raise ModelError(f"amount не может быть отрицательным: {val}")
    return val


def next_id(data: dict) -> str:
    mx = 0
    for ev in data["events"]:
        try:
            mx = max(mx, int(str(ev.get("id", "")).split("-")[-1]))
        except ValueError:
            continue
    return f"T-{mx + 1:03d}"


# ---------- validation ----------

def validate_event_fields(ev: dict) -> list[str]:
    """Возвращает список ошибок по одному событию (пусто = валидно)."""
    errs = []
    eid = ev.get("id", "?")
    if not str(ev.get("event", "")).strip():
        errs.append(f"{eid}: пустое поле event")
    # traceability обязательна
    if not str(ev.get("source_doc", "")).strip():
        errs.append(f"{eid}: пустой source_doc (traceability обязательна)")
    if not str(ev.get("source_fragment", "")).strip():
        errs.append(f"{eid}: пустой source_fragment (traceability обязательна)")
    fs = ev.get("fact_status")
    if fs not in FACT_STATUSES:
        errs.append(f"{eid}: fact_status должен быть одним из {FACT_STATUSES}, а не {fs!r}")
    ds = ev.get("date_status", "needs_check")
    if ds not in DATE_STATUSES:
        errs.append(f"{eid}: date_status должен быть одним из {DATE_STATUSES}, а не {ds!r}")
    date = ev.get("date")
    if date:
        try:
            parse_date(str(date))
        except ModelError as e:
            errs.append(f"{eid}: {e}")
    elif ds == "confirmed":
        errs.append(f"{eid}: date_status=confirmed требует непустую date")
    amt = ev.get("amount")
    if amt is not None:
        try:
            parse_amount(amt)
        except ModelError as e:
            errs.append(f"{eid}: {e}")
    errs.extend(evidence_anchor.validate_anchor(ev.get("anchor"), eid))
    return errs


def validate_all(data: dict) -> list[str]:
    errs = []
    ids = [ev.get("id") for ev in data["events"]]
    if len(ids) != len(set(ids)):
        errs.append(f"дублирующиеся id событий: {ids}")
    for ev in data["events"]:
        errs.extend(validate_event_fields(ev))
    return errs


# ---------- contradiction / double-count candidates (formal only) ----------

def _norm(s) -> str:
    return str(s or "").strip().lower()


def detect_candidates(events: list[dict]) -> list[dict]:
    """Формальный детект. НЕ выносит юридической оценки — только кандидаты.

    Типы:
    - duplicate     — совпадают (date, event, participant, location, amount);
    - double_count  — одна (location, amount != null) в >=2 разных событиях;
    - status_conflict — одна claim_key с >=2 разными fact_status ИЛИ группа
      claim_key, где DISPUTED соседствует с CONFIRMED/REPORTED/INFERRED.
    """
    out: list[dict] = []

    # duplicate
    seen: dict[tuple, list[str]] = {}
    for ev in events:
        key = (_norm(ev.get("date")), _norm(ev.get("event")),
               _norm(ev.get("participant")), _norm(ev.get("location")),
               parse_amount(ev.get("amount")))
        seen.setdefault(key, []).append(ev.get("id"))
    for key, group in seen.items():
        if len(group) > 1:
            out.append({"type": "duplicate", "ids": group,
                        "detail": f"совпадают дата/событие/участник/место/сумма ({group})"})

    # double_count — та же сумма на том же месте в разных событиях
    by_loc_amt: dict[tuple, list[str]] = {}
    for ev in events:
        amt = parse_amount(ev.get("amount"))
        loc = _norm(ev.get("location"))
        if amt is None or not loc:
            continue
        by_loc_amt.setdefault((loc, amt), []).append(ev.get("id"))
    for (loc, amt), group in by_loc_amt.items():
        if len(group) > 1:
            out.append({"type": "double_count", "ids": group,
                        "detail": f"одна сумма {amt:g} по месту «{loc}» в событиях {group} "
                                  f"— возможен двойной счёт"})

    # status_conflict — по claim_key
    by_claim: dict[str, list[dict]] = {}
    for ev in events:
        ck = _norm(ev.get("claim_key"))
        if ck:
            by_claim.setdefault(ck, []).append(ev)
    for ck, group in by_claim.items():
        statuses = {ev.get("fact_status") for ev in group}
        if len(statuses) > 1:
            ids = [ev.get("id") for ev in group]
            out.append({"type": "status_conflict", "ids": ids,
                        "detail": f"claim «{ck}»: расходящиеся статусы факта "
                                  f"{sorted(statuses)} в событиях {ids}"})
    return out


# ---------- sorting ----------

def sort_key(ev: dict):
    """Хронологически по дате; события без даты — в конец."""
    date = ev.get("date")
    if date:
        return (0, str(date), str(ev.get("id")))
    return (1, "", str(ev.get("id")))


# ---------- commands ----------

def cmd_init(args) -> int:
    path = Path(args.file)
    if path.exists():
        raise ModelError(f"timeline уже существует: {path} (init повторно не выполняется)")
    today = dt.date.today().isoformat()
    save(path, {
        "schema_version": SCHEMA_VERSION,
        "matter": args.matter,
        "created": today,
        "updated": today,
        "events": [],
    })
    print(f"OK: создан matter-timeline {path} (matter: {args.matter})")
    return 0


def _build_event(args, data: dict) -> dict:
    today = dt.date.today().isoformat()
    ev = {
        "id": next_id(data),
        "date": args.date,
        "date_status": args.date_status,
        "event": args.event,
        "participant": args.participant or "",
        "location": args.location or "",
        "amount": parse_amount(args.amount),
        "source_doc": args.source_doc,
        "source_fragment": args.source_fragment,
        "fact_status": args.fact_status,
        "claim_key": args.claim_key or "",
        "notes": args.notes or "",
        "created": today,
        "updated": today,
    }
    anchor = build_anchor(args.source_doc, args.quote, args.quote_location, Path(args.file).parent)
    if anchor:
        ev["anchor"] = anchor
    return ev


def cmd_add(args) -> int:
    path = Path(args.file)
    data = load(path)
    ev = _build_event(args, data)
    errs = validate_event_fields(ev)
    if errs:
        raise ModelError("событие не прошло валидацию:\n  " + "\n  ".join(errs))
    if enforce_confirmed(ev):
        print(f"ВНИМАНИЕ: {ev['id']} понижен до REPORTED — {UNANCHORED}; "
              f"{(ev.get('anchor') or {}).get('check_detail') or 'укажите --quote'}")
    data["events"].append(ev)
    save(path, data)
    marks = ""
    if ev["date_status"] != "confirmed":
        marks += f" {DATE_CHECK}"
    if ev["fact_status"] != "CONFIRMED":
        marks += f" {FACT_CHECK}"
    print(f"OK: {ev['id']} «{ev['event']}» date={ev['date'] or '—'} "
          f"[{ev['fact_status']}]{marks}")
    return 0


def cmd_update(args) -> int:
    path = Path(args.file)
    data = load(path)
    ev = next((e for e in data["events"] if e.get("id") == args.id), None)
    if ev is None:
        raise ModelError(f"событие {args.id} не найдено в {path}")
    for field, val in (
        ("date", args.date), ("date_status", args.date_status),
        ("event", args.event), ("participant", args.participant),
        ("location", args.location), ("source_doc", args.source_doc),
        ("source_fragment", args.source_fragment), ("fact_status", args.fact_status),
        ("claim_key", args.claim_key), ("notes", args.notes),
    ):
        if val is not None:
            ev[field] = val
    if args.amount is not None:
        ev["amount"] = parse_amount(args.amount)
    if args.quote is not None or (args.source_doc is not None and ev.get("anchor")):
        quote = args.quote if args.quote is not None else ev["anchor"]["quote"]
        qloc = (args.quote_location if args.quote_location is not None
                else (ev.get("anchor") or {}).get("location"))
        ev["anchor"] = build_anchor(ev["source_doc"], quote, qloc, path.parent)
    errs = validate_event_fields(ev)
    if errs:
        raise ModelError("после update событие не валидно:\n  " + "\n  ".join(errs))
    if args.fact_status == "CONFIRMED" and not evidence_anchor.is_verified(ev.get("anchor")):
        raise ModelError(f"{args.id}: CONFIRMED требует цитату, найденную в источнике "
                         "(--quote, при необходимости --quote-location)")
    ev["updated"] = dt.date.today().isoformat()
    save(path, data)
    print(f"OK: {args.id} обновлён [{ev['fact_status']}]")
    return 0


def cmd_validate(args) -> int:
    path = Path(args.file)
    data = load(path)
    errs = validate_all(data)
    if errs:
        print(f"НЕВАЛИДНО ({len(errs)}):")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"OK: matter-timeline валиден — событий {len(data['events'])}")
    return 0


def _fmt_amount(amt: float | None) -> str:
    if amt is None:
        return ""
    if amt == int(amt):
        return f"{int(amt):,}".replace(",", " ") + " ₽"
    return f"{amt:,.2f}".replace(",", " ") + " ₽"


def fmt_event(ev: dict) -> str:
    date = ev.get("date") or "дата не внесена"
    date_mark = f" {DATE_CHECK}" if ev.get("date_status") != "confirmed" else ""
    parts = []
    if ev.get("participant"):
        parts.append(str(ev["participant"]))
    if ev.get("location"):
        parts.append(str(ev["location"]))
    amt = _fmt_amount(parse_amount(ev.get("amount")))
    if amt:
        parts.append(amt)
    ctx = f" ({'; '.join(parts)})" if parts else ""
    fs = ev.get("fact_status")
    fact_mark = f" [{fs}] {FACT_CHECK}" if fs != "CONFIRMED" else ""
    src = f" — {ev.get('source_doc')}, {ev.get('source_fragment')}"
    return f"- {ev.get('id')} {date}{date_mark}: {ev.get('event')}{ctx}{src}{fact_mark}{anchor_note(ev)}"


def cmd_report(args) -> int:
    path = Path(args.file)
    data = load(path)
    events = sorted(data["events"], key=sort_key)
    matter = data.get("matter", path.stem)
    today = dt.date.today().isoformat()

    lines = [f"# Хронология дела: {matter} (на {today})", ""]
    if events:
        lines.append("## Хронология")
        lines.extend(fmt_event(ev) for ev in events)
        lines.append("")
    else:
        lines.append("Событий не внесено.")
        lines.append("")

    candidates = detect_candidates(events)
    if candidates:
        titles = {
            "double_count": "🟠 Кандидаты двойного счёта",
            "duplicate": "🟠 Дубликаты событий",
            "status_conflict": "🔴 Кандидаты противоречий (расходящийся статус факта)",
        }
        order = ["status_conflict", "double_count", "duplicate"]
        lines.append("## ⚠️ Кандидаты противоречий / двойного счёта")
        lines.append("_Формальный детект. Юридическую оценку даёт юрист — это лид, не вывод._")
        lines.append("")
        for typ in order:
            group = [c for c in candidates if c["type"] == typ]
            if group:
                lines.append(f"### {titles[typ]}")
                lines.extend(f"- {c['detail']}" for c in group)
                lines.append("")

    n_facts = sum(1 for ev in events if ev.get("fact_status") != "CONFIRMED")
    n_dates = sum(1 for ev in events if ev.get("date_status") != "confirmed")
    lines.append(f"Итого: событий {len(events)}, кандидатов на проверку {len(candidates)}.")
    if n_facts:
        lines.append(f"⚠️ Событий с непроверенным фактом (fact_status != CONFIRMED): "
                     f"{n_facts} — {FACT_CHECK}.")
    if n_dates:
        lines.append(f"⚠️ Событий с неподтверждённой датой: {n_dates} — {DATE_CHECK}.")
    print("\n".join(lines))
    return 0


# ---------- selftest (TDD на данных условного дела) ----------

def selftest() -> int:
    import tempfile
    ok = 0
    with tempfile.TemporaryDirectory() as td:
        f = str(Path(td) / "ДелоАльфа" / "matter-timeline.yaml")

        run(["init", "--file", f, "--matter", "ДелоАльфа"])
        try:
            run(["init", "--file", f, "--matter", "x"])
            raise AssertionError("повторный init должен падать")
        except ModelError:
            ok += 1

        # traceability: без source_fragment внести нельзя
        try:
            run(["add", "--file", f, "--event", "пожар",
                 "--source-doc", "Справка контрагента", "--fact-status", "CONFIRMED",
                 "--date", "2026-08-06", "--date-status", "confirmed"])
            raise AssertionError("add без source_fragment должен падать")
        except SystemExit:
            # argparse: --source-fragment required
            ok += 1

        # confirmed без даты — падает на валидации события
        try:
            run(["add", "--file", f, "--event", "оферта",
                 "--source-doc", "Оферта.pdf", "--source-fragment", "п.11.3",
                 "--fact-status", "CONFIRMED", "--date-status", "confirmed"])
            raise AssertionError("confirmed без date должен падать")
        except ModelError:
            ok += 1

        # нормальные события ДелоАльфа
        run(["add", "--file", f, "--event", "утрата товара, пожар на складе",
             "--date", "2026-08-06", "--date-status", "confirmed",
             "--participant", "ООО «Ромашка»", "--location", "Склад-1", "--amount", "105000",
             "--source-doc", "Реестр атак", "--source-fragment", "стр. 3",
             "--fact-status", "REPORTED", "--claim-key", "loss-kotovsk"])
        run(["add", "--file", f, "--event", "та же утрата в расчёте размера",
             "--date", "2026-08-06", "--date-status", "confirmed",
             "--participant", "ООО «Ромашка»", "--location", "Склад-1", "--amount", "105000",
             "--source-doc", "Приложение №1.xlsx", "--source-fragment", "строка Склад-1",
             "--fact-status", "REPORTED", "--claim-key", "loss-kotovsk"])
        run(["add", "--file", f, "--event", "контрагент заявил о сохранности склада",
             "--date", "2026-08-10", "--date-status", "confirmed",
             "--participant", "ООО «Ромашка»", "--location", "Склад-1",
             "--source-doc", "Позиция контрагента", "--source-fragment", "письмо",
             "--fact-status", "DISPUTED", "--claim-key", "loss-kotovsk"])
        run(["add", "--file", f, "--event", "инвентаризация артефактных складов",
             "--date-status", "needs_check",
             "--source-doc", "нет", "--source-fragment", "н/д",
             "--fact-status", "UNKNOWN"])

        data = load(Path(f))
        assert [e["id"] for e in data["events"]] == ["T-001", "T-002", "T-003", "T-004"], "id-нумерация"
        ok += 1

        # валидация чистая
        assert validate_all(data) == [], f"валидация должна быть чистой: {validate_all(data)}"
        ok += 1

        # сортировка: событие без даты — последним
        srt = sorted(data["events"], key=sort_key)
        assert srt[-1]["id"] == "T-004", "событие без даты должно быть в конце"
        assert [e["id"] for e in srt[:3]] == ["T-001", "T-002", "T-003"], "хронология"
        ok += 1

        # детект кандидатов
        cands = detect_candidates(data["events"])
        types = {c["type"] for c in cands}
        assert "double_count" in types, "должен найтись кандидат двойного счёта Склад-1"
        dc = next(c for c in cands if c["type"] == "double_count")
        assert set(dc["ids"]) >= {"T-001", "T-002"}, f"двойной счёт по T-001/T-002: {dc['ids']}"
        assert "status_conflict" in types, "должен найтись конфликт статусов по loss-kotovsk"
        sc = next(c for c in cands if c["type"] == "status_conflict")
        assert set(sc["ids"]) >= {"T-001", "T-003"}, f"конфликт REPORTED vs DISPUTED: {sc['ids']}"
        ok += 1

        # update: несуществующий id падает
        try:
            run(["update", "--file", f, "--id", "T-404", "--notes", "x"])
            raise AssertionError("несуществующий id должен падать")
        except ModelError:
            ok += 1

        # update меняет статус факта
        (Path(f).parent / "Акт инвентаризации.md").write_text(
            "1. Инвентаризация складов проведена 20.08.2026.", encoding="utf-8")
        run(["update", "--file", f, "--id", "T-004", "--fact-status", "CONFIRMED",
             "--source-doc", "Акт инвентаризации.md", "--source-fragment", "п.1",
             "--quote", "Инвентаризация складов проведена 20.08.2026",
             "--date", "2026-08-20", "--date-status", "confirmed"])
        data = load(Path(f))
        assert next(e for e in data["events"] if e["id"] == "T-004")["fact_status"] == "CONFIRMED"
        ok += 1

        # report не падает
        run(["report", "--file", f])
        run(["validate", "--file", f])
    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


# ---------- CLI ----------

def _add_event_args(p, required_core: bool) -> None:
    p.add_argument("--file", required=True)
    p.add_argument("--event", required=required_core)
    p.add_argument("--date")
    p.add_argument("--date-status", dest="date_status",
                   default=("needs_check" if required_core else None),
                   choices=DATE_STATUSES)
    p.add_argument("--participant")
    p.add_argument("--location")
    p.add_argument("--amount")
    p.add_argument("--source-doc", dest="source_doc", required=required_core)
    p.add_argument("--source-fragment", dest="source_fragment", required=required_core)
    p.add_argument("--fact-status", dest="fact_status", required=required_core,
                   choices=FACT_STATUSES)
    p.add_argument("--claim-key", dest="claim_key")
    p.add_argument("--notes")
    p.add_argument("--quote", help="дословная цитата из source_doc (проверяется по тексту)")
    p.add_argument("--quote-location", dest="quote_location", help="место цитаты: пункт, страница")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--file", required=True)
    p.add_argument("--matter", required=True)

    p = sub.add_parser("add")
    _add_event_args(p, required_core=True)

    p = sub.add_parser("update")
    p.add_argument("--id", required=True)
    _add_event_args(p, required_core=False)

    p = sub.add_parser("validate")
    p.add_argument("--file", required=True)

    p = sub.add_parser("report")
    p.add_argument("--file", required=True)

    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    return {
        "init": cmd_init, "add": cmd_add, "update": cmd_update,
        "validate": cmd_validate, "report": cmd_report,
    }[args.cmd](args)


def main() -> int:
    try:
        return run(sys.argv[1:])
    except ModelError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
