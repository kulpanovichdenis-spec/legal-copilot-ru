#!/usr/bin/env python3
"""Case bootstrap: раскладка разобранного документа по папке дела (класс A).

Вызывается агентом после того, как субагент `intake-classifier` вернул валидную
классификацию с достаточной уверенностью. Делает только детерминированное:
  1) находит/создаёт папку дела `workflow/<дело>/` (имя — через safe_folder_name);
  2) кладёт документ из `processed/` в папку дела, не затирая существующие;
  3) создаёт `case-context.md`, если его нет (существующий НЕ трогает — его ведёт
     агент по правилам CLAUDE.md «Контекст дела»);
  4) добавляет событие в `matter-timeline.yaml` через tools/matter_model
     (схема и валидация — оттуда же, здесь не дублируются).

Ничего не финализирует, ничего не отправляет, правовых выводов не делает.

"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "matter_model"))

import core  # noqa: E402
import model  # noqa: E402  (tools/matter_model/model.py — единственный источник схемы)

CONTEXT_TEMPLATE = """---
status: active
jurisdiction: RU
task_types: [{task_types}]
entities: [{entities}]
products: []
topics: []
case_number: {case_number}
related: []
---

# Контекст дела: {title}

> Карточка заведена автоматически конвейером приёма ({created}). Проверьте и дополните —
> дальше её ведёт агент по правилам CLAUDE.md «Контекст дела (case-context)».

## Стороны

{entities_list}

## Стадия

`[ПРОВЕРИТЬ ФАКТ]` — определить по документу.

## Хронология

Машиночитаемая хронология — `matter-timeline.yaml` (ведётся через `tools/matter_model`).

## Стратегические решения юриста

Пока нет.

## Следующий шаг

`[ВОПРОС ЮРИСТУ]` — определить после ознакомления с документом.
"""


def _yaml_list(items: list[str]) -> str:
    # json.dumps экранирует кавычки в наименованиях («ООО "Альфа"») — валидный YAML-скаляр
    return ", ".join(json.dumps(i, ensure_ascii=False) for i in items if i)


def ensure_case_folder(workflow_root: Path, name: str) -> Path:
    """Папка дела по безопасному имени. Существующую не трогает."""
    folder = workflow_root / core.safe_folder_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def ensure_case_context(folder: Path, *, case_number: str | None,
                        entities: list[str], matter_type: str | None) -> tuple[Path, bool]:
    """Создать `case-context.md`, если его нет. Возвращает (путь, создан ли сейчас).

    Существующий файл **не изменяется**: его ведёт агент/юрист, конвейер не вправе
    переписывать зафиксированные там решения.
    """
    ctx = folder / "case-context.md"
    if ctx.exists():
        return ctx, False
    ctx.write_text(CONTEXT_TEMPLATE.format(
        task_types=_yaml_list([matter_type] if matter_type else []),
        entities=_yaml_list(entities),
        case_number=case_number or "null",
        title=folder.name,
        created=dt.date.today().isoformat(),
        entities_list="\n".join(f"- {e}" for e in entities) or "`[ПРОВЕРИТЬ РЕКВИЗИТЫ]`",
    ), encoding="utf-8")
    return ctx, True


def file_document(folder: Path, source: Path, name: str | None = None) -> Path:
    """Положить документ в папку, не затирая существующие. name — целевое имя
    (переименование); None → имя источника."""
    existing = {p.name for p in folder.iterdir()} if folder.exists() else set()
    dest = folder / core.unique_name(name or source.name, existing)
    shutil.copy2(str(source), str(dest))
    return dest


def add_timeline_event(folder: Path, *, matter: str, doc_kind: str,
                       doc_name: str, fragment: str, date: str | None,
                       date_confirmed: bool = False) -> str:
    """Добавить событие поступления документа в matter-timeline.yaml.

    Статусы осознанно: сам факт поступления документа — `CONFIRMED` (файл у нас на
    руках); дата документа приходит от класс-B классификатора и не сверялась
    человеком, поэтому `date_status = needs_check`, пока юрист не подтвердит.
    """
    path = folder / "matter-timeline.yaml"
    if not path.exists():
        today = dt.date.today().isoformat()
        model.save(path, {
            "schema_version": model.SCHEMA_VERSION,
            "matter": matter,
            "created": today,
            "updated": today,
            "events": [],
        })
    data = model.load(path)
    # Класс-B классификатор отдаёт дату как в тексте («01.09.2026») — приводим к ISO
    # здесь, кодом. Не разобралась — остаётся пустой, дату не выдумываем.
    iso_date = core.parse_ru_date(date)
    event = {
        "id": model.next_id(data),
        "date": iso_date,
        "date_status": "confirmed" if date_confirmed else "needs_check",
        "event": f"Поступил документ: {doc_kind}",
        "source_doc": doc_name,
        "source_fragment": fragment[:300],
        "fact_status": "CONFIRMED",
    }
    errs = model.validate_event_fields(event)
    if errs:
        raise ValueError("событие не прошло валидацию matter_model: " + "; ".join(errs))
    data["events"].append(event)
    data["updated"] = dt.date.today().isoformat()
    model.save(path, data)
    return event["id"]


def send_to_unsorted(source: Path, unsorted_dir: Path, reason: str) -> Path:
    """Документ, который не удалось уверенно разложить, — в unsorted/ с причиной."""
    unsorted_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in unsorted_dir.iterdir()}
    dest = unsorted_dir / core.unique_name(source.name, existing)
    shutil.move(str(source), str(dest))
    dest.with_suffix(dest.suffix + ".reason.txt").write_text(reason + "\n", encoding="utf-8")
    return dest


def place(workflow_root: Path, *, source: Path, folder_name: str,
          doc_kind: str, fragment: str, case_number: str | None = None,
          entities: list[str] | None = None, matter_type: str | None = None,
          doc_date: str | None = None, expertise_name: str | None = None,
          third_party_name: str | None = None) -> dict:
    """Полная раскладка одного документа. Возвращает отчёт для строки юристу."""
    entities = entities or []
    # Сначала валидируем событие хронологии, только потом трогаем файлы (регрессия
    # 2026-09-08: упавший на хронологии прогон оставлял скопированный документ).
    probe = {
        "id": "T-000", "date": core.parse_ru_date(doc_date),
        "date_status": "needs_check", "event": f"Поступил документ: {doc_kind}",
        "source_doc": source.name, "source_fragment": (fragment or "")[:300],
        "fact_status": "CONFIRMED",
    }
    errs = model.validate_event_fields(probe)
    if errs:
        raise ValueError("событие не прошло валидацию matter_model: " + "; ".join(errs))

    folder = ensure_case_folder(workflow_root, folder_name)
    ctx, created = ensure_case_context(folder, case_number=case_number,
                                       entities=entities, matter_type=matter_type)
    sub = core.role_folder(doc_kind, expertise_name=expertise_name,
                           third_party_name=third_party_name)
    dest_dir = folder / sub if sub else folder
    dest_dir.mkdir(parents=True, exist_ok=True)

    party = entities[0] if entities else None
    new_name = core.document_filename(doc_kind, party,
                                      doc_date=core.parse_ru_date(doc_date),
                                      ext=source.suffix)
    placed = file_document(dest_dir, source, new_name)
    event_id = add_timeline_event(folder, matter=folder.name, doc_kind=doc_kind,
                                  doc_name=placed.name, fragment=fragment, date=doc_date)
    return {
        "case_folder": folder.name,
        "case_subfolder": sub,
        "case_context_created": created,
        "document": placed.name,
        "timeline_event": event_id,
    }


# --- CLI для агента ------------------------------------------------------------

MIN_CONFIDENCE = 0.7
# Извлечённый на приёме текст и классификация не выбрасываются: карточка очереди
# переезжает в папку дела рядом со слоем знаний (matter-knowledge читает её, а не OCR заново).
# Порог слоя знаний и гейт закрытия задачи — knowledge_gate.py (единственное место).
from knowledge_gate import INTAKE_DIR, knowledge_layer_status  # noqa: E402


def keep_intake_card(card: dict, card_path: Path, dest: Path, *, placed_as: str | None = None,
                     queue_ref: str | None = None) -> str:
    """Перенести карточку очереди (text_head, classification, OCR-метаданные) в dest.
    queue_ref связывает её с задачей единой очереди (гейт закрытия в queue_cli)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in dest.parent.iterdir()}
    dest = dest.parent / core.unique_name(dest.name, existing)
    data = dict(card, status="placed" if placed_as else "unsorted")
    if placed_as:
        data["placed_as"] = placed_as.replace("\\", "/")
    if queue_ref:
        data["queue_ref"] = queue_ref
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    card_path.unlink(missing_ok=True)
    return dest.name


def _queue_ref(card_path: Path, root: Path) -> str:
    """Ссылка на карточку очереди в том виде, как её пишет QueueStore (от корня репо, через /)."""
    p = card_path.resolve()
    try:
        return p.relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def apply_card(card_path: Path, *, root: Path | None = None) -> dict:
    """Разложить документ по карточке задачи, в которую агент вписал `classification`.

    Решение принимается здесь, а не в промпте: пустая классификация, непустой
    `escalate`, `confidence` ниже порога или неопределённая папка дела → unsorted.
    """
    import json  # noqa: PLC0415

    root = root or Path(__file__).resolve().parents[2]
    card = json.loads(card_path.read_text(encoding="utf-8"))
    src = root / card["processed_path"]
    unsorted_dir = src.parent.parent / "unsorted"
    cls = card.get("classification") or {}
    res = cls.get("result") or {}

    reason = None
    if not cls:
        reason = "классификация не выполнена"
    elif cls.get("escalate"):
        reason = f"классификатор эскалировал: {cls['escalate']}"
    elif float(cls.get("confidence") or 0) < MIN_CONFIDENCE:
        reason = f"низкая уверенность классификации: {cls.get('confidence')}"

    matter_type = core.classify_matter_type(res.get("doc_kind"), res.get("addressee_authority"))

    folder_name = card.get("matched_case_folder")
    if not folder_name and not reason:
        numbers = card.get("case_numbers") or []
        parties = res.get("parties") or []
        short = (parties[0] if parties else (numbers[0] if numbers else None))
        if not short:
            reason = "не удалось определить дело (нет сторон и номера дела)"
        else:
            folder_name = core.case_folder_name(short, matter_type=matter_type)

    if reason:
        dest = send_to_unsorted(src, unsorted_dir, reason)
        keep_intake_card(card, card_path, dest.with_name(dest.name + ".intake.json"))
        return {"status": "unsorted", "reason": reason, "file": dest.name}

    rep = place(
        root / "workflow", source=src, folder_name=folder_name,
        doc_kind=res.get("doc_kind") or "документ",
        fragment=(cls.get("source_fragments") or [card.get("text_head", "")[:200]])[0],
        case_number=(card.get("case_numbers") or [None])[0],
        entities=res.get("parties") or [], matter_type=matter_type,
        doc_date=res.get("doc_date"),
        expertise_name=res.get("expertise_name"),
        third_party_name=res.get("third_party_name"),
    )
    src.unlink(missing_ok=True)          # оригинал уже скопирован в папку дела
    case_dir = root / "workflow" / rep["case_folder"]
    rep["intake_card"] = keep_intake_card(
        card, card_path,
        case_dir / INTAKE_DIR / f"{Path(rep['document']).stem}.intake.json",
        placed_as=str(Path(rep["case_subfolder"] or "") / rep["document"]),
        queue_ref=_queue_ref(card_path, root),
    )
    rep["knowledge_layer"] = knowledge_layer_status(case_dir)
    rep["status"] = "placed"
    rep["suggested_skill"] = core.suggested_skill(matter_type, res.get("doc_kind"))
    return rep


def main(argv=None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="Раскладка документа по карточке задачи")
    ap.add_argument("card", help="путь к workflow/_claims/queue/<файл>.json")
    args = ap.parse_args(argv)
    rep = apply_card(Path(args.card))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
