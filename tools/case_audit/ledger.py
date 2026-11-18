"""Local, append-only task ledger. No network access or implicit transcript scan."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]
KINDS = {"run", "request", "document", "result", "revision", "approval", "action", "conclusion", "gap", "usage"}
BEGIN = "<!-- case-audit:begin -->"
END = "<!-- case-audit:end -->"
CODEX_ID_RE = __import__("re").compile(r"^[0-9a-f-]{36}$")
OPENAI_STANDARD_PRICING_2026_10_21 = {
    "gpt-6.1-sol": {"input_uncached": "2.00", "input_cached": "0.10", "output": "10.00"},
    "gpt-5.6-sol": {"input_uncached": "4.00", "input_cached": "0.40", "output": "20.00"},
}
OPENAI_PRICING_URL = "https://developers.openai.com/api/docs/pricing"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def task_path(value: str | Path) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to((ROOT / "workflow").resolve()):
        raise ValueError("Папка задачи должна находиться в workflow/")
    # The anonymizer guard only permits generated drafts; do not read originals.
    if "_anonymizer" in path.relative_to(ROOT / "workflow").parts:
        raise ValueError("Для проекта анонимайзера используйте отдельную папку задачи вне _anonymizer с обезличенными материалами")
    return path


def records(task: Path) -> list[dict]:
    path = task / "case-audit.jsonl"
    if not path.exists():
        return []
    result = []
    previous = None
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        actual = record.pop("hash")
        if record.get("previous_hash") != previous or digest(encoded(record)) != actual:
            raise ValueError("Нарушена целостность журнала")
        record["hash"] = actual
        previous = actual
        result.append(record)
    return result


def amount(value) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Некорректная сумма/ставка") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("Сумма/ставка должна быть конечной и неотрицательной")
    return number


def validate_usage(data: dict) -> None:
    for field in ("provider", "model", "request_id", "usage_source", "service_tier"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"usage требует {field}")
    counts = data.get("tokens", {})
    if not counts or not isinstance(counts, dict):
        raise ValueError("tokens: нужны раздельные категории расхода")
    for key, value in counts.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Некорректный счётчик {key}")
    if "total" in counts or "reasoning" in counts:
        raise ValueError("total/reasoning не являются отдельными оплачиваемыми категориями; reasoning уже включён в output")
    pricing = data.get("pricing")
    if pricing is not None:
        for field in ("model", "provider", "service_tier"):
            if pricing.get(field) != data[field]:
                raise ValueError(f"Тариф не соответствует {field}")
        if pricing.get("currency") != "USD" or not pricing.get("source_url"):
            raise ValueError("Тариф требует USD и source_url")
        datetime.fromisoformat(pricing["checked_at"].replace("Z", "+00:00"))
        for category in counts:
            amount(pricing["per_million"][category])
    if data.get("actual_charge_usd") is not None:
        amount(data["actual_charge_usd"])
        if not data.get("charge_source"):
            raise ValueError("Фактическое списание требует charge_source")


LEGAL_SOURCE_KINDS = {"norm": "норма", "practice": "практика", "guidance": "разъяснение"}


def validate_legal_source(data: dict) -> None:
    """A norm/practice the work relies on: what, by which route, verified or from model memory."""
    if data.get("source_kind") not in LEGAL_SOURCE_KINDS:
        raise ValueError(f"source_kind: одно из {sorted(LEGAL_SOURCE_KINDS)}")
    for field in ("ref", "route"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"source_kind требует {field}")
    if not isinstance(data.get("checked"), bool):
        raise ValueError("source_kind требует checked: true/false")


def append(task: Path, kind: str, data: dict, *, actor: str, run_id: str, event_id: str | None = None) -> dict:
    if kind not in KINDS or not actor.strip() or not run_id.strip() or not isinstance(data, dict):
        raise ValueError("Нужны тип события, actor, run_id и объект data")
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("Нужно краткое описание summary")
    if kind == "usage":
        validate_usage(data)
    if kind == "document" and "source_kind" in data:
        validate_legal_source(data)
    if kind == "run" and not all(data.get(k) for k in ("runner", "provider", "model", "usage_status")):
        raise ValueError("run требует runner, provider, model, usage_status")
    if kind in {"approval", "revision", "conclusion"} and not data.get("refs"):
        raise ValueError(f"{kind} требует refs на события/версии документов")
    if kind == "approval" and not all(data.get(k) for k in ("decision", "authority_source")):
        raise ValueError("Согласование требует decision и authority_source (реплика/письмо юриста)")
    task.mkdir(parents=True, exist_ok=True)
    # Exclusive single-writer lock: conflicting processes fail instead of losing events.
    lock = task / ".case-audit.lock"
    with lock.open("x", encoding="utf-8") as lock_handle:
        lock_handle.close()  # Windows cannot unlink a file while this handle is open.
        try:
            old = records(task)
            if kind in {"approval", "revision", "conclusion"}:
                known = {item["id"] for item in old}
                if not isinstance(data["refs"], list) or any(not isinstance(ref, str) or ref not in known for ref in data["refs"]):
                    raise ValueError("refs должны ссылаться на существующие ID событий этого дела")
            if event_id:
                for item in old:
                    if item["id"] == event_id:
                        if (item["kind"], item["data"], item["actor"], item["run_id"]) != (kind, data, actor, run_id):
                            raise ValueError("event_id уже занят другим событием")
                        return item
            if kind == "usage":
                key = (data["provider"], data["request_id"])
                for item in old:
                    if item["kind"] == "usage" and (item["data"]["provider"], item["data"]["request_id"]) == key:
                        if item["data"] != data or item["run_id"] != run_id:
                            raise ValueError("Запрос уже учтён с другими данными")
                        return item
            item = {"schema_version": 1, "id": event_id or str(uuid.uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(), "actor": actor,
                    "run_id": run_id, "kind": kind, "data": data,
                    "previous_hash": old[-1]["hash"] if old else None}
            item["hash"] = digest(encoded(item))
            with (task / "case-audit.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
            return item
        finally:
            lock.unlink()


def capture(task: Path, source: str, *, actor: str, run_id: str, version: str, summary: str,
            extra: dict | None = None) -> dict:
    path = (task / source).resolve()
    if not path.is_relative_to(task) or not path.is_file():
        raise ValueError("Документ должен находиться внутри папки задачи")
    if "_anonymizer" in path.parts or path.name.endswith(".mapping.json"):
        raise ValueError("Оригиналы и mappings анонимайзера не регистрируются этим инструментом")
    content = path.read_bytes()
    sha = digest(content)
    archive = task / "_audit" / "versions" / sha
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with archive.open("xb") as out:
            out.write(content)
    except FileExistsError:
        if archive.read_bytes() != content:
            raise ValueError("Повреждён архив версии")
    data = dict(extra or {})
    data.update({"summary": summary, "path": path.relative_to(task).as_posix(),
                 "version": version, "sha256": sha, "snapshot": archive.relative_to(task).as_posix()})
    return append(task, "document", data, actor=actor, run_id=run_id)


def codex_rollout(session_id: str, sessions_root: Path | None = None) -> Path:
    if not CODEX_ID_RE.fullmatch(session_id):
        raise ValueError("Некорректный Codex session_id")
    root = sessions_root or Path.home() / ".codex" / "sessions"
    matches = list(root.glob(f"*/*/*/*{session_id}.jsonl"))
    if len(matches) != 1:
        raise ValueError(f"Codex rollout не найден однозначно: {len(matches)}")
    return matches[0]


def read_codex_turn(path: Path, turn_id: str) -> dict:
    if not CODEX_ID_RE.fullmatch(turn_id):
        raise ValueError("Некорректный Codex turn_id")
    session = {}
    context = None
    active_turn = None
    completed = False
    usage = []
    for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
        item = json.loads(raw)
        payload = item.get("payload") or {}
        if item.get("type") == "session_meta":
            session = {key: payload.get(key) for key in ("id", "originator", "cli_version", "cwd")}
        elif item.get("type") == "turn_context" and payload.get("turn_id") == turn_id:
            context = {"model": payload.get("model"), "effort": payload.get("effort")}
        elif item.get("type") == "event_msg" and payload.get("type") == "task_started":
            active_turn = payload.get("turn_id")
        elif item.get("type") == "event_msg" and payload.get("type") == "token_count" and active_turn == turn_id:
            last = (payload.get("info") or {}).get("last_token_usage")
            if isinstance(last, dict):
                usage.append({"ordinal": item.get("ordinal"), "timestamp": item.get("timestamp"),
                              "source_hash": digest(raw.encode("utf-8")), "usage": last})
        elif item.get("type") == "event_msg" and payload.get("type") == "task_complete":
            if payload.get("turn_id") == turn_id:
                completed = True
            if active_turn == payload.get("turn_id"):
                active_turn = None
    if context is None:
        raise ValueError("turn_context не найден")
    return {"session": session, "turn_id": turn_id, "context": context,
            "completed": completed, "usage": usage}


def codex_pricing(model: str) -> dict | None:
    rates = OPENAI_STANDARD_PRICING_2026_10_21.get(model)
    if rates is None:
        return None
    return {"provider": "openai", "model": model, "service_tier": "standard-api-equivalent",
            "currency": "USD", "checked_at": "2026-10-21T00:00:00Z", "source_url": OPENAI_PRICING_URL,
            "basis": "Public Standard API rates captured 2026-10-21; not a subscription charge",
            "per_million": rates}


def bind_codex(task: Path, *, sessions_root: Path | None = None,
               session_id: str | None = None, turn_id: str | None = None) -> dict:
    session_id = session_id or __import__("os").environ.get("CODEX_SESSION_ID")
    if not session_id:
        raise ValueError("CODEX_SESSION_ID недоступен")
    rollout = codex_rollout(session_id, sessions_root)
    if turn_id is None:
        contexts = []
        for raw in rollout.read_text(encoding="utf-8").splitlines():
            item = json.loads(raw)
            if item.get("type") == "turn_context":
                contexts.append((item.get("payload") or {}).get("turn_id"))
        turn_id = contexts[-1] if contexts else None
    if not turn_id:
        raise ValueError("Текущий Codex turn_id не найден")
    parsed = read_codex_turn(rollout, turn_id)
    model = parsed["context"].get("model") or "unknown"
    run_id = f"codex:{session_id}:{turn_id}"
    event = append(task, "run", {"summary": "Запуск Codex Desktop", "runner": "codex-desktop",
                   "provider": "openai", "model": model, "usage_status": "pending",
                   "settings": {"reasoning_effort": parsed["context"].get("effort")},
                   "implementation": {"codex_version": parsed["session"].get("cli_version")},
                   "codex_session_id": session_id, "codex_turn_id": turn_id},
                   actor="codex-bind", run_id=run_id, event_id=f"codex-run:{session_id}:{turn_id}")
    binding = ROOT / "workflow" / "_case_audit_bindings" / session_id / f"{turn_id}.jsonl"
    binding.parent.mkdir(parents=True, exist_ok=True)
    relative = task.relative_to(ROOT / "workflow").as_posix()
    existing = binding.read_text(encoding="utf-8").splitlines() if binding.exists() else []
    record = json.dumps({"case": relative}, ensure_ascii=False)
    if record not in existing:
        with binding.open("a", encoding="utf-8") as out:
            out.write(record + "\n")
    sync(task)
    return event


def import_codex_turn(task: Path, session_id: str, turn_id: str,
                      *, sessions_root: Path | None = None, require_complete: bool = True) -> int:
    parsed = read_codex_turn(codex_rollout(session_id, sessions_root), turn_id)
    if require_complete and not parsed["completed"]:
        raise ValueError("Codex turn ещё не завершён")
    model = parsed["context"].get("model") or "unknown"
    run_id = f"codex:{session_id}:{turn_id}"
    imported = 0
    existing_requests = {(record["data"].get("provider"), record["data"].get("request_id"))
                         for record in records(task) if record["kind"] == "usage"}
    for item in parsed["usage"]:
        raw = item["usage"]
        input_tokens = int(raw.get("input_tokens", 0))
        cached = int(raw.get("cached_input_tokens", 0))
        cache_write = int(raw.get("cache_write_input_tokens", 0))
        output = int(raw.get("output_tokens", 0))
        uncached = input_tokens - cached - cache_write
        if min(input_tokens, cached, cache_write, output, uncached) < 0:
            raise ValueError("Некорректные счётчики Codex")
        tokens = {"input_uncached": uncached, "input_cached": cached, "output": output}
        if cache_write:
            tokens["input_cache_write"] = cache_write
        pricing = None if cache_write else codex_pricing(model)
        request_id = f"codex:{session_id}:{turn_id}:{item['ordinal']}"
        if ("openai", request_id) in existing_requests:
            continue
        data = {"summary": "Фактический расход генерации Codex Desktop",
                "provider": "openai", "model": model,
                "request_id": request_id,
                "service_tier": "standard-api-equivalent",
                "usage_source": f"local-codex-rollout sha256:{item['source_hash']}",
                "tokens": tokens,
                "token_details": {"reasoning_output_tokens": int(raw.get("reasoning_output_tokens", 0))}}
        if pricing:
            data["pricing"] = pricing
        append(task, "usage", data, actor="codex-stop-import", run_id=run_id)
        existing_requests.add(("openai", request_id))
        imported += 1
    sync(task)
    return imported


def report(task: Path) -> str:
    items = records(task)
    usage = [x for x in items if x["kind"] == "usage"]
    runs = {x["run_id"] for x in items if x["kind"] == "run"}
    covered = {x["run_id"] for x in usage}
    counts: dict[str, int] = {}
    equivalent = Decimal(0)
    actual = Decimal(0)
    priced = charged = 0
    groups: dict[tuple, dict] = {}
    for item in usage:
        data = item["data"]
        validate_usage(data)
        group = groups.setdefault((item["run_id"], data["provider"], data["model"]),
                                  {"tokens": 0, "cost": Decimal(0), "priced": 0, "requests": 0})
        group["requests"] += 1
        group["tokens"] += sum(data["tokens"].values())
        for key, value in data["tokens"].items():
            counts[key] = counts.get(key, 0) + value
        if data.get("pricing"):
            priced += 1
            cost = sum((Decimal(value) * amount(data["pricing"]["per_million"][key]) / Decimal(1000000)
                        for key, value in data["tokens"].items()), Decimal(0))
            equivalent += cost
            group["cost"] += cost
            group["priced"] += 1
        if data.get("actual_charge_usd") is not None:
            charged += 1
            actual += amount(data["actual_charge_usd"])
    models = sorted({f"{x['data'].get('provider', '?')}/{x['data'].get('model', '?')}"
                     for x in items if x["kind"] in {"run", "usage"}})
    lines = ["## История работы и стоимость", "", "Журнал: [case-audit.jsonl](case-audit.jsonl).",
             f"Событий: {len(items)}. Модели: {', '.join(models) or 'нет данных'}.",
             f"Токены (учтённая часть): {json.dumps(counts, ensure_ascii=False) if usage else 'нет данных'}.",
             f"API-эквивалент USD: {equivalent if priced else 'нет данных'}; тариф есть для {priced}/{len(usage)} запросов.",
             f"Фактические списания USD: {actual if charged else 'нет данных'}; подтверждены для {charged}/{len(usage)} запросов.",
             f"Запуски без записей расхода: {', '.join(sorted(runs - covered)) or 'не выявлены среди зарегистрированных' }.",
             "Codex usage импортируется автоматически только для явно привязанного завершённого turn; суммы относятся к зарегистрированным запросам.", "",
             "| Событие | Тип | Запуск | Содержание |", "|---|---|---|---|"]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    if groups:
        position = len(lines) - 2
        breakdown = ["| Запуск / модель | Токены | API-эквивалент USD (учтённая часть) |", "|---|---|---|"]
        for key, group in sorted(groups.items()):
            cost_text = str(group["cost"]) if group["priced"] else "нет данных"
            breakdown.append(f"| {cell(' / '.join(key))} | {group['tokens']} | {cost_text}; тариф {group['priced']}/{group['requests']} |")
        lines[position:position] = breakdown + [""]
    lines.extend("| " + " | ".join(cell(x) for x in (item["id"], item["kind"], item["run_id"], item["data"]["summary"])) + " |"
                 for item in items[-10:])
    if len(items) > 10:
        lines.append("В карточке показаны последние 10 событий; полная история — в журнале.")
    sources = [x["data"] for x in items if x["kind"] == "document" and "source_kind" in x["data"]]
    if sources:
        lines += ["", "### Опора на нормы и практику", "",
                  "| Вид | Источник | Маршрут | Статус | Где использовано |", "|---|---|---|---|---|"]
        lines.extend("| " + " | ".join(cell(x) for x in (
            LEGAL_SOURCE_KINDS[d["source_kind"]], d["ref"], d["route"],
            "проверено" if d["checked"] else "не проверено", d.get("used_in", ""))) + " |" for d in sources)
    return "\n".join(lines) + "\n"


def sync(task: Path) -> None:
    path = task / "case-context.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "# Контекст задачи\n\n"
    block = BEGIN + "\n" + report(task) + END
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(END) < text.index(BEGIN):
            raise ValueError("Повреждены границы сводки; карточка не изменена")
        start, finish = text.index(BEGIN), text.index(END) + len(END)
        text = text[:start] + block + text[finish:]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")


def validate(task: Path) -> int:
    items = records(task)
    for item in items:
        data = item["data"]
        if item["kind"] == "usage":
            validate_usage(data)
        if item["kind"] == "document" and data.get("snapshot"):
            path = (task / data["snapshot"]).resolve()
            if not path.is_relative_to(task) or digest(path.read_bytes()) != data["sha256"]:
                raise ValueError("Повреждена сохранённая версия документа")
    return len(items)


def import_openai(task: Path, path: Path, *, run_id: str, pricing: dict | None = None) -> dict:
    """Import an explicitly supplied API response, not an estimated token count."""
    response = json.loads(path.read_text(encoding="utf-8-sig"))
    usage = response["usage"]
    cached = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
    total_input = usage["input_tokens"]
    if cached > total_input:
        raise ValueError("cached_tokens превышает input_tokens")
    # Fail closed for new cache-write billing until separate rates are supplied.
    if usage.get("input_tokens_details", {}).get("cache_write_tokens", 0):
        raise ValueError("Ответ содержит cache_write_tokens: импортируйте раздельные категории через event usage")
    data = {"summary": "Расход из ответа OpenAI Responses API", "provider": "openai",
            "model": response["model"], "request_id": response["id"],
            "service_tier": response.get("service_tier") or "unknown",
            "usage_source": {"path": path.relative_to(task).as_posix(), "sha256": digest(path.read_bytes())},
            "tokens": {"input_uncached": total_input - cached, "input_cached": cached, "output": usage["output_tokens"]}}
    # Source locator is a human-readable string in the common contract.
    data["usage_source"] = json.dumps(data["usage_source"], ensure_ascii=False)
    if pricing is not None:
        data["pricing"] = pricing
    return append(task, "usage", data, actor="openai-response-import", run_id=run_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["event", "document", "bind-codex", "import-codex",
                                                   "import-openai", "report", "sync", "validate"])
    parser.add_argument("--case", required=True)
    parser.add_argument("--kind", choices=sorted(KINDS))
    parser.add_argument("--data", help="Локальный JSON с data события; не передавайте секреты")
    parser.add_argument("--actor", default="agent")
    parser.add_argument("--run-id")
    parser.add_argument("--event-id")
    parser.add_argument("--file")
    parser.add_argument("--version")
    parser.add_argument("--summary")
    parser.add_argument("--pricing", help="JSON снимка тарифа внутри папки задачи")
    parser.add_argument("--session-id")
    parser.add_argument("--turn-id")
    args = parser.parse_args()
    try:
        task = task_path(args.case)
        if args.command in {"event", "document", "import-openai"} and not args.run_id:
            raise ValueError("Нужен --run-id")
        if args.command == "event":
            if not args.kind or not args.data:
                raise ValueError("Нужны --kind и --data")
            payload_path = Path(args.data).resolve()
            if not payload_path.is_relative_to(task) or payload_path.name.endswith(".mapping.json"):
                raise ValueError("JSON события должен находиться внутри папки задачи")
            data = json.loads(payload_path.read_text(encoding="utf-8-sig"))
            append(task, args.kind, data, actor=args.actor, run_id=args.run_id, event_id=args.event_id)
            sync(task)
        elif args.command == "document":
            if not all((args.file, args.version, args.summary)):
                raise ValueError("Нужны --file, --version и --summary")
            capture(task, args.file, actor=args.actor, run_id=args.run_id, version=args.version, summary=args.summary)
            sync(task)
        elif args.command == "bind-codex":
            bind_codex(task, session_id=args.session_id, turn_id=args.turn_id)
        elif args.command == "import-codex":
            if not args.session_id or not args.turn_id:
                raise ValueError("Нужны --session-id и --turn-id")
            imported = import_codex_turn(task, args.session_id, args.turn_id)
            print(f"OK: импортировано {imported} новых записей usage")
        elif args.command == "import-openai":
            source = (task / (args.file or "")).resolve()
            if not source.is_relative_to(task) or source.name.endswith(".mapping.json"):
                raise ValueError("Ответ API должен находиться внутри папки задачи")
            pricing = None
            if args.pricing:
                price_path = (task / args.pricing).resolve()
                if not price_path.is_relative_to(task) or price_path.name.endswith(".mapping.json"):
                    raise ValueError("Тариф должен находиться внутри папки задачи")
                pricing = json.loads(price_path.read_text(encoding="utf-8-sig"))
            import_openai(task, source, run_id=args.run_id, pricing=pricing)
            sync(task)
        elif args.command == "sync":
            sync(task)
        elif args.command == "report":
            print(report(task))
        else:
            print(f"OK: {validate(task)} событий")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Ошибка: {exc}\n")
    return 0
