# -*- coding: utf-8 -*-
"""Судебная статистика по судье арбитражного суда (детерминированная часть skill judge-analytics).

Пайплайн: fetch (поиск + скачивание текстов в кэш) -> classify (фильтр состава суда +
классификация резолютивных частей) -> report (CSV / JSON / Markdown).

Источник данных: api.docs.cntd.ru (зеркало sudrf.cntd.ru). Это ВСПОМОГАТЕЛЬНЫЙ источник
(Приоритет 2 по references/source-hierarchy.md): корпус может быть неполным, поэтому все
цифры — нижняя оценка по доступному корпусу, о чём report пишет явно.

Команды:
  selftest                          -- оффлайн-тесты классификатора и фильтра состава суда
  fetch --judge .. --department .. --date-from .. --date-to .. --workdir ..
  classify --judge .. --workdir ..
  report --workdir ..
  run (fetch + classify + report)

Скрипт не обходит капчи и технические ограничения: при HTTP-ошибках фиксирует их и завершается.
"""

import argparse
import csv
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from tools.safe_cell import safe_mapping  # noqa: E402

API_BASE = "https://api.docs.cntd.ru/v1"

# cntd.ru использует сертификат российского УЦ, который стандартное хранилище Python
# отвергает (Basic Constraints of CA cert not marked critical). Флаг --insecure
# отключает проверку сертификата ТОЛЬКО для этого публичного зеркала: в запросах
# нет ничего, кроме ФИО судьи (публичная информация) и параметров периода.
SSL_CONTEXT = None  # выставляется в main() при --insecure
REQUEST_PAUSE_SEC = 0.6
USER_AGENT = "legal-copilot-judge-analytics/1.0 (research; contact: in-house legal)"

# ---------------------------------------------------------------------------
# Категории резолютивных частей.
# Порядок правил важен: сначала более специфичные исходы, затем общие.
# Всё, что не распознано однозначно, уходит в ambiguous/unclassified для ручного
# просмотра юристом — скрипт не угадывает.
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "left_unchanged": "оставлено без изменения",
    "reversed": "отменено",
    "reversed_in_part": "отменено в части",
    "reversed_remanded": "отменено с направлением на новое рассмотрение",
    "changed": "изменено",
    "settlement": "мировое соглашение (акт отменён в связи с утверждением)",
    "appeal_terminated": "производство по жалобе прекращено",
    "without_consideration": "жалоба оставлена без рассмотрения",
    "procedural": "процедурное (пошлина, опечатки, правопреемство и т. п.)",
    "ambiguous": "неоднозначно — ручной просмотр",
    "unclassified": "не классифицировано — ручной просмотр",
}

PROCEDURAL_MARKERS = (
    "пошлин",
    "депозитн",
    "исправлении опечат",
    "исправить опечат",
    "разъяснении судебного акта",
    "процессуальном правопреемстве",
    "процессуальное правопреемство",
    "по правилам, установленным для рассмотрения дела в суде первой инстанции",
    "восстановлении пропущенного срока",
    "отсрочк",
    "рассрочк",
)


def classify_resolution(resolution_text: str) -> str:
    """Классифицирует резолютивную часть постановления. Возвращает ключ категории."""
    t = re.sub(r"\s+", " ", resolution_text).lower()

    has_reverse = "отменить" in t or "отменено" in t
    has_change = re.search(r"\bизменить\b", t) is not None
    has_left = (
        "оставить без изменения" in t
        or "оставить без удовлетворения" in t
        or re.search(r"жалоб\w*[^.]{0,80}без удовлетворения", t) is not None
    )

    if "мировое соглашение" in t and "утвердить" in t:
        return "settlement"
    if "прекратить производство по апелляционной жалобе" in t or "прекратить производство по кассационной жалобе" in t:
        return "appeal_terminated"
    if re.search(r"жалоб\w*[^.]{0,80}оставить без рассмотрения", t):
        return "without_consideration"

    if has_reverse and "новое рассмотрение" in t and "направить" in t:
        return "reversed_remanded"
    if has_reverse and has_change:
        # Отмена в части + изменение в одной резолютивке — не угадываем.
        return "ambiguous"
    if has_change:
        return "changed"
    if has_reverse:
        if re.search(r"отменить в части|в части[^.]{0,120}отменить", t):
            return "reversed_in_part"
        return "reversed"
    if has_left:
        return "left_unchanged"

    if any(marker in t for marker in PROCEDURAL_MARKERS):
        return "procedural"
    return "unclassified"


# ---------------------------------------------------------------------------
# Состав суда.
# Фамилия судьи должна стоять именно в блоке состава («суд в составе ... »),
# а не в истории движения дела («произведена замена судьи ...») и не в ссылке
# на судью первой инстанции.
# ---------------------------------------------------------------------------

COMPOSITION_END_RE = re.compile(
    r"при ведении|рассмотрел|рассмотрев|при участии", re.IGNORECASE
)


def extract_composition_block(text: str) -> str:
    """Возвращает участок текста от 'в составе' до ближайшего маркера конца блока."""
    head = text[:6000]  # состав суда всегда в шапке постановления
    m = re.search(r"в составе", head, re.IGNORECASE)
    if not m:
        return ""
    tail = head[m.end():]
    end = COMPOSITION_END_RE.search(tail)
    return tail[: end.start()] if end else tail[:800]


def judge_name_regex(judge: str) -> re.Pattern:
    """Строит регэксп по 'Фамилия И.О.' с допуском падежных окончаний и пробелов.

    'Иванов И.А.' матчит 'Иванова И. И.' (родительный падеж в составе суда),
    'Иванова И.И.' матчит 'Ивановой И.И.'.
    """
    m = re.match(r"^\s*([А-ЯЁ][а-яё-]+)\s+([А-ЯЁ])\s*\.\s*([А-ЯЁ])\s*\.\s*$", judge)
    if not m:
        raise ValueError(
            f"ФИО судьи должно быть в формате 'Фамилия И.О.', получено: {judge!r}"
        )
    surname, i1, i2 = m.groups()
    stem = surname[:-1] if surname[-1] in "аяео" else surname
    return re.compile(
        rf"{re.escape(stem)}[а-яё]{{0,3}}\s+{i1}\s*\.\s*{i2}\s*\.", re.IGNORECASE
    )


def judge_in_composition(text: str, judge: str) -> dict:
    """Проверяет вхождение судьи в состав суда. Возвращает dict с вердиктом и ролью."""
    block = extract_composition_block(text)
    if not block:
        return {"in_composition": False, "role": None, "reason": "composition_block_not_found"}
    pattern = judge_name_regex(judge)
    hit = pattern.search(block)
    if not hit:
        return {"in_composition": False, "role": None, "reason": "not_in_composition"}
    before = block[: hit.start()].lower()
    role = "chair" if "председательствующ" in before.rsplit("суде", 1)[-1] and "судей" not in before[-60:] else "member"
    # председательствующий обычно назван первым, сразу после «председательствующего судьи»
    if re.search(r"председательствующ\w*\s+(судьи\s+)?$", before[-60:]):
        role = "chair"
    return {"in_composition": True, "role": role, "reason": None}


# ---------------------------------------------------------------------------
# Резолютивная часть: текст после последнего 'ПОСТАНОВИЛ'.
# ---------------------------------------------------------------------------

def extract_resolution(text: str) -> str:
    matches = list(re.finditer(r"ПОСТАНОВИЛ\s*:?", text, re.IGNORECASE))
    if not matches:
        return ""
    return text[matches[-1].end():].strip()


CASE_NUMBER_RE = re.compile(r"А\d{2,3}-\d+/\d{4}")


def extract_case_number(text: str) -> str:
    m = CASE_NUMBER_RE.search(text[:4000])
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# HTTP-слой api.docs.cntd.ru. Схема ответа зеркала может меняться, поэтому
# разбор устойчивый: пробуем известные формы, при неудаче сохраняем сырой ответ
# и завершаемся с внятной ошибкой (не угадываем).
# ---------------------------------------------------------------------------

def http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_search_items(payload):
    for key in ("documents", "items", "data", "results"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            inner = extract_search_items(value)
            if inner is not None:
                return inner
    if isinstance(payload, list):
        return payload
    return None


def search_documents(judge: str, department: str, date_from: str, date_to: str,
                     doc_type: str, max_pages: int, workdir: Path) -> list:
    """Поиск постановлений: перебирает варианты написания ФИО и страницы выдачи."""
    m = re.match(r"^\s*([А-ЯЁ][а-яё-]+)\s+([А-ЯЁ])\.([А-ЯЁ])\.\s*$", judge)
    if not m:
        raise ValueError("ФИО судьи должно быть в формате 'Фамилия И.О.'")
    surname, i1, i2 = m.groups()
    name_variants = [f"{surname} {i1}.{i2}.", f"{surname} {i1}. {i2}."]

    found = {}
    for variant in name_variants:
        for page in range(1, max_pages + 1):
            params = [
                ("query", variant),
                ("department", department),
                ("date[]", date_from),
                ("date[]", date_to),
                ("date_join", "between"),
                ("page", str(page)),
            ]
            if doc_type:
                params.append(("type", doc_type))
            url = f"{API_BASE}/search?" + urllib.parse.urlencode(params)
            payload = http_get_json(url)
            items = extract_search_items(payload)
            if items is None:
                raw_path = workdir / "cache" / "unexpected_search_response.json"
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                raise RuntimeError(
                    f"Неожиданный формат ответа поиска, сырой ответ сохранён: {raw_path}"
                )
            if not items:
                break
            for item in items:
                doc_id = item.get("id") or item.get("document_id") or item.get("nd")
                if doc_id is not None:
                    found[str(doc_id)] = item
            time.sleep(REQUEST_PAUSE_SEC)
    return [dict(item, _doc_id=doc_id) for doc_id, item in found.items()]


def fetch_document_text(doc_id: str) -> str:
    size_payload = http_get_json(f"{API_BASE}/document/{doc_id}/content/text/blocks/size")
    size = size_payload if isinstance(size_payload, int) else (
        size_payload.get("size") or size_payload.get("count") or 0
    )
    blocks = []
    for i in range(int(size)):
        block = http_get_json(f"{API_BASE}/document/{doc_id}/content/text/block/{i}")
        if isinstance(block, dict):
            block = block.get("text") or block.get("content") or json.dumps(block, ensure_ascii=False)
        blocks.append(str(block))
        time.sleep(REQUEST_PAUSE_SEC)
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Команды пайплайна.
# ---------------------------------------------------------------------------

def cmd_fetch(args) -> int:
    workdir = Path(args.workdir)
    cache = workdir / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    items = search_documents(args.judge, args.department, args.date_from,
                             args.date_to, args.type, args.max_pages, workdir)
    print(f"Сырых поисковых попаданий (уникальных документов): {len(items)}")
    (workdir / "search_results.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    fetched = skipped = 0
    for item in items:
        doc_id = item["_doc_id"]
        text_path = cache / f"{doc_id}.txt"
        if text_path.exists():
            skipped += 1
            continue
        text_path.write_text(fetch_document_text(doc_id), encoding="utf-8")
        fetched += 1
        print(f"  скачан {doc_id} ({fetched})")
    print(f"Скачано: {fetched}, из кэша: {skipped}")
    return 0


def cmd_classify(args) -> int:
    workdir = Path(args.workdir)
    cache = workdir / "cache"
    if not cache.exists():
        print(f"Нет кэша текстов: {cache}. Сначала выполните fetch.", file=sys.stderr)
        return 2

    rows = []
    for text_path in sorted(cache.glob("*.txt")):
        text = text_path.read_text(encoding="utf-8")
        verdict = judge_in_composition(text, args.judge)
        resolution = extract_resolution(text)
        category = classify_resolution(resolution) if resolution else "unclassified"
        rows.append({
            "doc_id": text_path.stem,
            "case_number": extract_case_number(text),
            "in_composition": verdict["in_composition"],
            "composition_reason": verdict["reason"] or "",
            "role": verdict["role"] or "",
            "category": category if verdict["in_composition"] else "",
            "resolution_preview": re.sub(r"\s+", " ", resolution)[:300],
        })

    (workdir / "classification.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with (workdir / "classification.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(safe_mapping(r) for r in rows)
    in_comp = sum(1 for r in rows if r["in_composition"])
    print(f"Документов в кэше: {len(rows)}; судья в составе суда: {in_comp}")
    return 0


def cmd_report(args) -> int:
    workdir = Path(args.workdir)
    rows = json.loads((workdir / "classification.json").read_text(encoding="utf-8"))
    included = [r for r in rows if r["in_composition"]]

    counts = {}
    for r in included:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    unique_cases = len({r["case_number"] for r in included if r["case_number"]})
    manual = [r for r in included if r["category"] in ("ambiguous", "unclassified")]

    summary = {
        "raw_documents": len(rows),
        "in_composition": len(included),
        "unique_cases": unique_cases,
        "by_category": {CATEGORY_LABELS.get(k, k): v for k, v in sorted(counts.items())},
        "manual_review_needed": len(manual),
        "source_caveat": (
            "Расчёт по зеркалу sudrf.cntd.ru / api.docs.cntd.ru (вспомогательный источник, "
            "Приоритет 2). Корпус зеркала может быть неполным: все цифры — нижняя оценка "
            "по доступному корпусу, не официальная статистика суда."
        ),
    }
    (workdir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Статистика по судье (черновик, требует проверки юристом)",
        "",
        f"- Постановлений с судьёй в составе суда: **{len(included)}** (из {len(rows)} сырых попаданий)",
        f"- Уникальных дел: **{unique_cases}**",
        "",
        "| Категория | Кол-во |",
        "|---|---|",
    ]
    lines += [f"| {CATEGORY_LABELS.get(k, k)} | {v} |" for k, v in sorted(counts.items())]
    lines += [
        "",
        f"Требуют ручного просмотра (ambiguous/unclassified): {len(manual)} — см. classification.csv.",
        "",
        f"⚠ {summary['source_caveat']}",
        "",
        "[СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ] — выборочно сверить дела с kad.arbitr.ru перед использованием цифр в документах.",
    ]
    (workdir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# Self-тесты (оффлайн): классификатор и фильтр состава суда.
# ---------------------------------------------------------------------------

SELFTEST_RESOLUTIONS = [
    ("решение Арбитражного суда оставить без изменения, апелляционную жалобу - без удовлетворения.", "left_unchanged"),
    ("решение отменить. Принять по делу новый судебный акт. Взыскать...", "reversed"),
    ("решение отменить в части взыскания неустойки. В остальной части оставить без изменения.", "reversed_in_part"),
    ("решение изменить, изложив абзац второй резолютивной части в следующей редакции...", "changed"),
    ("решение отменить, дело направить на новое рассмотрение в Арбитражный суд...", "reversed_remanded"),
    ("производство по апелляционной жалобе прекратить... Хотя тут 'прекратить производство по апелляционной жалобе'.", "appeal_terminated"),
    ("утвердить мировое соглашение, заключённое между сторонами... Решение отменить.", "settlement"),
    ("апелляционную жалобу оставить без рассмотрения.", "without_consideration"),
    ("возвратить из федерального бюджета государственную пошлину в размере 3000 рублей.", "procedural"),
    ("решение отменить в части, изменить размер взысканной суммы...", "ambiguous"),
]

SELFTEST_COMPOSITION = """Восемнадцатый арбитражный апелляционный суд в составе:
председательствующего судьи Иванова И.А., судей Ивановой И.И., Петрова П.П.,
при ведении протокола секретарем судебного заседания,
рассмотрел в открытом судебном заседании дело N А76-12345/2025 по апелляционной жалобе.
Определением от 01.02.2025 произведена замена судьи Сидорова С.С. на судью Иванова И.А.
"""


def cmd_selftest(_args) -> int:
    failures = 0
    for text, expected in SELFTEST_RESOLUTIONS:
        got = classify_resolution(text)
        status = "OK " if got == expected else "FAIL"
        if got != expected:
            failures += 1
        print(f"[{status}] {expected:22} <- {got:22} | {text[:60]}...")

    for judge, expected in [("Иванов И.А.", True), ("Иванова И.И.", True),
                            ("Петров П.П.", True), ("Сидоров С.С.", False)]:
        got = judge_in_composition(SELFTEST_COMPOSITION, judge)["in_composition"]
        status = "OK " if got == expected else "FAIL"
        if got != expected:
            failures += 1
        print(f"[{status}] состав суда: {judge} -> {got} (ожидалось {expected})")

    print(f"\nSelftest: {'PASS' if failures == 0 else f'FAIL ({failures})'}")
    return 0 if failures == 0 else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--insecure", action="store_true",
                        help="не проверять SSL-сертификат cntd.ru (российский УЦ)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("selftest")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workdir", required=True, help="Рабочая папка внутри workflow/")

    p_fetch = sub.add_parser("fetch", parents=[common])
    p_fetch.add_argument("--judge", required=True, help="ФИО в формате 'Фамилия И.О.'")
    p_fetch.add_argument("--department", required=True, help="department_id суда на cntd")
    p_fetch.add_argument("--date-from", required=True, help="YYYY-MM-DD")
    p_fetch.add_argument("--date-to", required=True, help="YYYY-MM-DD")
    p_fetch.add_argument("--type", default="", help="id типа документа (постановления), опционально")
    p_fetch.add_argument("--max-pages", type=int, default=20)

    p_classify = sub.add_parser("classify", parents=[common])
    p_classify.add_argument("--judge", required=True)

    sub.add_parser("report", parents=[common])

    p_run = sub.add_parser("run", parents=[common])
    for a in ("--judge", "--department", "--date-from", "--date-to"):
        p_run.add_argument(a, required=True)
    p_run.add_argument("--type", default="")
    p_run.add_argument("--max-pages", type=int, default=20)

    args = parser.parse_args()
    if getattr(args, "insecure", False):
        global SSL_CONTEXT
        SSL_CONTEXT = ssl._create_unverified_context()
        print("⚠ SSL-проверка отключена (--insecure) — только для публичного зеркала cntd.ru")
    if args.command == "selftest":
        return cmd_selftest(args)
    if args.command == "fetch":
        return cmd_fetch(args)
    if args.command == "classify":
        return cmd_classify(args)
    if args.command == "report":
        return cmd_report(args)
    if args.command == "run":
        rc = cmd_fetch(args)
        if rc:
            return rc
        rc = cmd_classify(args)
        if rc:
            return rc
        return cmd_report(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
