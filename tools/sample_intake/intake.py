#!/usr/bin/env python3
"""sample_intake — промоушен документа из workflow/ в образец профиля (A2 + T1).

Механическая часть интейка образцов:

    workflow/<...>/<документ> → обезличить (pre_anonymize, профиль sample)
      → определить категорию + slug → положить обезличенный текст в
        profile/knowledge/document-samples/originals/<категория>/<slug>.md → STOP.

Тул НЕ пишет карточку-разбор (это шаг агента) и НЕ показывает mapping.json.
Детерминированный, без LLM. Инвариант T1: исходный документ обязан лежать внутри
workflow/. Обезличивание обязательно (A2), профиль по умолчанию `full`.

CLI:
    python tools/sample_intake/intake.py promote "workflow/<дело>/<файл>.docx"
    python tools/sample_intake/intake.py promote "<файл>" --category contracts --slug my-slug
    python tools/sample_intake/intake.py index      # сводный INDEX.md по карточкам
    python tools/sample_intake/intake.py selftest

Python API:
    from tools.sample_intake.intake import promote, detect_category, make_slug
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

CATEGORIES = ("contracts", "amendments", "litigation", "koap", "gov-responses")

# Порядок и веса: сначала более специфичные жанры, «договор/соглашение» — широкий
# fallback, поэтому contracts проверяется по своим маркерам, но амендменты и
# процессуальные перебивают его при совпадении своих ключей.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "amendments": (
        "дополнительное соглашение", "доп. соглашение", "доп соглашение",
        "протокол разногласий", "протокол согласования разногласий",
    ),
    "koap": (
        "коап", "об административном правонарушении", "административное правонарушение",
        "объяснение", "объяснения", "постановление по делу об админ",
    ),
    "gov-responses": (
        "ответ на представление", "на представление", "представление об устранении",
        "предостережение", "предписание", "роспотребнадзор", "прокуратур",
        "ответ на запрос", "на запрос", "надзорн",
    ),
    "litigation": (
        "исковое заявление", "исковых требован", "отзыв на иск", "отзыв на заявление",
        "ходатайство", "возражение", "возражения", "жалоба", "жалобу", "претензия",
        "претензи", "судебный приказ", "мировое соглашение", "апелляцион", "кассацион",
        "в арбитражный суд", "истец", "ответчик",
    ),
    "contracts": (
        "договор", "контракт", "supply contract", "supply agreement",
        "license agreement", "agreement", "term sheet", "оферта", "спецификация",
        "лицензионный договор",
    ),
}

# Транслитерация для slug (кириллица → латиница).
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

HEADER = (
    "> **Обезличенный исходный текст образца** (обезличено `tools/pre_anonymize`, "
    "профиль {profile}; исходник и mapping остались в `workflow/`, в контекст не попадают).\n"
    "> Разбор, приёмы и применимость — в парной карточке "
    "`cards/{cat}/{slug}.md` (создаётся агентом, статус `candidate` → `verified`).\n\n"
    "---\n\n"
)


class IntakeError(Exception):
    """Контролируемая ошибка интейка (без чувствительных данных в тексте)."""


def make_slug(name: str) -> str:
    """Имя файла/строку → kebab-case латиницей, безопасно для файловой системы."""
    stem = Path(name).stem.lower()
    out = []
    for ch in stem:
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or "obrazec"


def detect_category(text: str, filename: str = "") -> tuple[str | None, list[str]]:
    """Определить категорию образца по ключевым словам.

    Returns:
        (категория | None, отсортированный список кандидатов). None и/или
        неоднозначность (несколько кандидатов с близким счётом) — сигнал агенту
        уточнить у юриста, а не угадывать.
    """
    # Жанр задаёт заголовок: имя файла + начало текста. Тело любого договора содержит
    # «претензии»/«возражения» (претензионный порядок, приёмка) — по телу договор
    # ошибочно уходил в litigation. Тело — только fallback, если заголовок молчит.
    head = (Path(filename).stem + "\n" + text[:HEAD_CHARS]).lower()
    head_result = _rank_categories(head)
    if head_result[0] is not None:
        return head_result
    return _rank_categories((filename + "\n" + text).lower())


# Сколько символов начала текста считать заголовком документа.
HEAD_CHARS = 500


def _rank_categories(hay: str) -> tuple[str | None, list[str]]:
    scores: dict[str, int] = {
        cat: sum(1 for kw in kws if kw in hay) for cat, kws in CATEGORY_KEYWORDS.items()
    }
    # contracts — широкий fallback: «договор»/«соглашение» встречается и в ДС, и в
    # процессуальных (со ссылкой на договор). Специфичные жанры имеют приоритет.
    specific = ("amendments", "koap", "gov-responses", "litigation")
    spec_ranked = sorted(specific, key=lambda c: scores[c], reverse=True)
    top = spec_ranked[0]
    if scores[top] > 0:
        tied = [c for c in specific if scores[c] == scores[top]]
        if len(tied) > 1:
            return None, tied  # два жанра равны — пусть уточнят
        return top, [c for c in spec_ranked if scores[c] > 0]
    if scores["contracts"] > 0:
        return "contracts", ["contracts"]
    return None, list(CATEGORIES)  # ничего не сработало — пусть уточнят


def promote(
    doc_path: str | Path,
    *,
    kind: str = "sample",
    profile: str = "sample",
    category: str | None = None,
    slug: str | None = None,
    workflow_root: str | Path | None = None,
    samples_root: str | Path | None = None,
) -> dict:
    """Промоушен документа из workflow/ в образец: обезличить → разместить оригинал.

    Карточку НЕ пишет (шаг агента). Возвращает словарь с путём оригинала,
    категорией/slug и флагом неоднозначности.
    """
    from tools.pre_anonymize.prepare import prepare, PrepareError
    from tools.pre_anonymize.quality import quality_report, summary_line

    doc = Path(doc_path).resolve()
    if kind not in ("sample", "clause"):
        raise IntakeError("kind должен быть 'sample' или 'clause'")
    if not doc.exists() or not doc.is_file():
        raise IntakeError(f"файл не найден: {doc}")

    # Инвариант T1: только из workflow/.
    wf = Path(workflow_root).resolve() if workflow_root else (ROOT / "workflow")
    try:
        doc.relative_to(wf)
    except ValueError:
        raise IntakeError(
            f"промоушен только из workflow/ (T1): {doc} не внутри {wf}"
        )

    # A2: обязательное обезличивание. anon.md + mapping.json ложатся рядом с
    # исходником в workflow/ (gitignore); mapping в LLM не передаётся.
    try:
        anon_path, _map_path = prepare(doc, profile, out_dir=doc.parent)
    except PrepareError as e:
        raise IntakeError(f"обезличивание не удалось: {e}")
    anon_text = anon_path.read_text(encoding="utf-8", errors="replace")

    # Категория + slug.
    ambiguous = False
    candidates: list[str] = []
    if category is None:
        category, candidates = detect_category(anon_text, doc.name)
        if category is None:
            ambiguous = True
    elif category not in CATEGORIES:
        raise IntakeError(f"категория должна быть одной из {list(CATEGORIES)}")
    slug = slug or make_slug(doc.name)

    if samples_root is not None:
        sroot = Path(samples_root).resolve()
    else:
        from tools.profile.profile_lib import profile_root
        sroot = Path(profile_root()).resolve() / "knowledge" / "document-samples"

    result: dict = {
        "kind": kind,
        "category": category,
        "candidates": candidates,
        "ambiguous": ambiguous,
        "slug": slug,
        "anon_source": str(anon_path),
        "original_path": None,
        "card_path_hint": None,
        # Автопроверка обезличивания (tools/pre_anonymize/quality.py): остатки и
        # ложные замены — счётчики без значений; needs_review — агент проверяет.
        "quality": quality_report(anon_text),
    }

    if kind == "clause":
        # У клаузы отдельного оригинала нет: текст клаузы = тело карточки, которую
        # пишет агент в profile/knowledge/clauses/cards/. Оригинал не размещаем.
        result["card_path_hint"] = f"profile/knowledge/clauses/cards/{slug}.md"
        return result

    if ambiguous:
        # Не угадываем категорию — оригинал не раскладываем, отдаём кандидатов агенту.
        return result

    dst_dir = sroot / "originals" / category
    dst_dir.mkdir(parents=True, exist_ok=True)
    original = dst_dir / f"{slug}.md"
    header = HEADER.format(cat=category, slug=slug, profile=profile)
    header = header.replace("\n\n---", f"\n> {summary_line(result['quality'])}\n\n---", 1)
    original.write_text(header + anon_text.strip() + "\n", encoding="utf-8")
    result["original_path"] = str(original)
    result["card_path_hint"] = f"profile/knowledge/document-samples/cards/{category}/{slug}.md"
    return result


# ---------- сводный индекс карточек ----------

INDEX_NAME = "INDEX.md"
INDEX_HEADER = (
    "# Сводный индекс образцов\n\n"
    "> Генерируется `python tools/sample_intake/intake.py index` из frontmatter карточек. "
    "Руками не править — перегенерировать после изменения карточек.\n"
    "> `paper`: ours — наша бумага, counterparty — форма контрагента, compromise — итог переговоров. "
    "`sample_level`: reference — эталон, acceptable — допустимый вариант, anti — антипример. "
    "«—» — поле не заполнено (или обзорная карточка группы).\n"
)


def _frontmatter(text: str) -> dict[str, str]:
    """Плоские `ключ: значение` верхнего уровня; комментарии и кавычки снимаются."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    meta: dict[str, str] = {}
    for line in text[3:end if end != -1 else None].splitlines():
        if not line or line[0] in " \t-#" or ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.split(" #", 1)[0].strip().strip('"').strip("'")
        meta[key.strip()] = val
    return meta


def _cell(value: str, limit: int = 0) -> str:
    value = value.replace("**", "").replace("|", "/").replace("\n", " ").strip()
    if limit and len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value or "—"


def build_index(samples_root: str | Path | None = None) -> Path:
    """Собрать INDEX.md по всем карточкам `cards/<категория>/*.md`."""
    if samples_root is not None:
        sroot = Path(samples_root).resolve()
    else:
        from tools.profile.profile_lib import profile_root
        sroot = Path(profile_root()).resolve() / "knowledge" / "document-samples"
    cards = sroot / "cards"
    out = [INDEX_HEADER]
    cats = sorted(p.name for p in cards.iterdir() if p.is_dir()) if cards.exists() else []
    for cat in sorted(cats, key=lambda c: (CATEGORIES.index(c) if c in CATEGORIES else 99, c)):
        files = sorted((cards / cat).glob("*.md"))
        if not files:
            continue
        out.append(f"\n## {cat} ({len(files)})\n\n"
                   "| Карточка | Что это | paper | sample_level | status | язык | оригинал |\n"
                   "|---|---|---|---|---|---|---|\n")
        for f in files:
            meta = _frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            orig = [ext for ext in ("md", "docx") if (sroot / "originals" / cat / f"{f.stem}.{ext}").exists()]
            out.append(
                f"| [[{f.stem}]] | {_cell(meta.get('doc_kind', ''), 160)} | {_cell(meta.get('paper', ''))} "
                f"| {_cell(meta.get('sample_level', ''))} | {_cell(meta.get('status', ''))} "
                f"| {_cell(meta.get('language', ''))} | {', '.join(orig) or '—'} |\n"
            )
    index = sroot / INDEX_NAME
    index.write_text("".join(out), encoding="utf-8")
    return index


# ---------- selftest ----------

def selftest() -> int:
    import tempfile
    ok = 0

    # make_slug
    assert make_slug("Договор поставки рус (англ).docx") == "dogovor-postavki-rus-angl", make_slug("Договор поставки рус (англ).docx")
    assert make_slug("otzyv-9l.md") == "otzyv-9l"
    ok += 1

    # detect_category
    assert detect_category("ИСКОВОЕ ЗАЯВЛЕНИЕ в арбитражный суд. Истец ... Ответчик ...")[0] == "litigation"
    assert detect_category("ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 3 к Договору поставки")[0] == "amendments"
    assert detect_category("Объяснение по делу об административном правонарушении (КоАП)")[0] == "koap"
    assert detect_category("Ответ на представление прокуратуры об устранении нарушений")[0] == "gov-responses"
    assert detect_category("ДОГОВОР ПОСТАВКИ. Продавец и Покупатель. Спецификация.")[0] == "contracts"
    assert detect_category("Просто какой-то текст без жанровых слов")[0] is None
    # Регрессия 2026-09-30: договор с разделом о претензиях/возражениях по приёмке ушёл
    # в litigation. Жанр определяет заголовок/имя файла, а не слова в теле.
    preamble = " Стороны заключили настоящий документ о нижеследующем." * 12  # > HEAD_CHARS
    body_claims = " Претензионный порядок. Претензия направляется ... Возражения по качеству." * 20
    assert detect_category("SUPPLY AGREEMENT No. 5" + preamble + body_claims,
                           "supply agreement.docx")[0] == "contracts"
    assert detect_category("ДОГОВОР ПОСТАВКИ № 5." + preamble + body_claims)[0] == "contracts"
    assert detect_category("ПРЕТЕНЗИЯ по договору поставки № 5. Требуем оплатить.")[0] == "litigation"
    assert detect_category("ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 2 к Договору поставки." + preamble + body_claims)[0] == "amendments"
    # жанр только в имени файла — заголовок текста его не содержит
    assert detect_category("Исх. № ... Между сторонами заключен договор подряда." + preamble + body_claims,
                           "Претензия последний срок.docx")[0] == "litigation"
    ok += 1

    with tempfile.TemporaryDirectory() as td:
        wf = Path(td) / "workflow"
        (wf / "delo").mkdir(parents=True)
        sroot = Path(td) / "profile" / "knowledge" / "document-samples"

        # T1: файл вне workflow → IntakeError
        outside = Path(td) / "снаружи.md"
        outside.write_text("ДОГОВОР ПОСТАВКИ. Продавец. Покупатель.", encoding="utf-8")
        try:
            promote(outside, workflow_root=wf, samples_root=sroot)
            raise AssertionError("файл вне workflow должен падать (T1)")
        except IntakeError:
            ok += 1

        # промоушен образца из workflow: обезличивание + размещение оригинала, без карточки
        src = wf / "delo" / "договор-ромашка.md"
        src.write_text(
            "ДОГОВОР ПОСТАВКИ № 7 от 01.02.2026.\n"
            "Поставщик: ООО «Ромашка Фарм», ИНН 7712345678, Иванов Иван Петрович.\n"
            "Покупатель: ООО «Лютик». Цена: 1 250 000 руб. Спецификация — приложение.",
            encoding="utf-8",
        )
        res = promote(src, workflow_root=wf, samples_root=sroot)
        assert res["kind"] == "sample" and res["category"] == "contracts", res
        assert res["slug"] == "dogovor-romashka", res["slug"]
        orig = Path(res["original_path"])
        assert orig.exists() and orig.parent.name == "contracts"
        body = orig.read_text(encoding="utf-8")
        # A2: обезличено — реальные данные не в оригинале образца
        assert "Ромашка" not in body and "7712345678" not in body and "Иванов" not in body, body
        assert "[" in body, "нет плейсхолдеров — обезличивание не сработало"
        # автопроверка обезличивания — в результате и в шапке оригинала
        assert res["quality"]["verdict"] in ("ok", "needs_review"), res["quality"]
        assert "автопроверка обезличивания" in body, body[:400]
        # STOP: карточка тулом НЕ создана
        assert not (sroot / "cards" / "contracts" / "dogovor-romashka.md").exists()
        # mapping.json остался в workflow (не в профиле)
        assert (src.parent / "договор-ромашка.mapping.json").exists()
        assert not list((sroot).rglob("*.mapping.json"))
        ok += 1

        # неоднозначная категория → оригинал не раскладывается, отдаются кандидаты
        amb = wf / "delo" / "непонятный.md"
        amb.write_text("Некий текст об услугах и работах без явного жанра документа.", encoding="utf-8")
        res2 = promote(amb, workflow_root=wf, samples_root=sroot)
        assert res2["ambiguous"] and res2["original_path"] is None, res2
        ok += 1

        # клауза: оригинал не размещается, hint на clauses/cards
        src2 = wf / "delo" / "forsmajor.md"
        src2.write_text("6.1. Стороны освобождаются от ответственности при форс-мажоре. ООО «Ромашка».", encoding="utf-8")
        res3 = promote(src2, kind="clause", workflow_root=wf, samples_root=sroot)
        assert res3["kind"] == "clause" and res3["original_path"] is None
        assert res3["card_path_hint"] == "profile/knowledge/clauses/cards/forsmajor.md", res3
        ok += 1

        # сводный индекс: поля из frontmatter, комментарии сняты, парный оригинал отмечен
        (sroot / "cards" / "contracts").mkdir(parents=True, exist_ok=True)
        (sroot / "cards" / "contracts" / "dogovor-romashka.md").write_text(
            '---\ndoc_kind: "Договор | поставки"\npaper: ours   # наша бумага\n'
            "sample_level: reference\nstatus: candidate\nlanguage: ru\ntags:\n  - x\n---\n# t\n",
            encoding="utf-8",
        )
        idx = build_index(sroot).read_text(encoding="utf-8")
        assert "## contracts (1)" in idx, idx
        assert "| [[dogovor-romashka]] | Договор / поставки | ours | reference | candidate | ru | md |" in idx, idx
        ok += 1

        # связи с нормами: формат ключа, извлечение из текста, обратный указатель, автозаполнение
        from tools.sample_intake.norm_links import (NORM_RE, extract_mentions, validate_links,
                                                    build_norms_index, backfill, card_meta)
        for good in ("381-ФЗ ст. 9 ч. 4", "ГК РФ ст. 1468 п. 2", "НК РФ ст. 149 п. 3 пп. 16.1",
                     "ГК РФ ст. 431.2", "Решение Совета ЕЭК № 87 от 03.11.2016", "Инструкция Банка России № 181-И п. 4.3"):
            assert NORM_RE.match(good), good
        for bad in ("ст. 9 381-ФЗ", "Закон о торговле ст. 9", "381-ФЗ, ст. 9"):
            assert not NORM_RE.match(bad), bad
        m = extract_mentions(
            "6.1. Правообладатель на основании ст. 431.2 ГК РФ заверяет.\n"
            "Основание — ч. 8 ст. 24 Федерального закона от 13.03.2006 № 38-ФЗ «О рекламе».\n"
            "8.6. Предел по ч. 4 ст. 9 Федерального закона от 28.12.2009 № 381-ФЗ.\n"
            "Освобождение по пп. 16.1 п. 3 ст. 149 НК; п. 2 ст. 1468 Гражданского кодекса.\n"
            "Не основание для расторжения (п. 7 ст. 1 235 ГК).\n"
            "Штраф по п. 1 ст. 20.25 КоАП РФ.\n"
            "Не соответствует пункту 1 части 1 статьи 57 ФЗ-248 (в редакции Закона № 540-ФЗ)."
        )
        assert ("248-ФЗ ст. 57 ч. 1", "п. 8.6") in m and not any(k.startswith("540-ФЗ") for k, _ in m), m
        assert ("КоАП РФ ст. 20.25 ч. 1", "п. 8.6") in m, m
        assert ("ГК РФ ст. 1235 п. 7", "п. 8.6") in m and not any(k.startswith("ГК РФ ст. 1 ") for k, _ in m), m
        assert ("ГК РФ ст. 431.2", "п. 6.1") in m, m
        assert ("38-ФЗ ст. 24 ч. 8", "п. 6.1") in m, m
        assert ("381-ФЗ ст. 9 ч. 4", "п. 8.6") in m, m
        assert ("НК РФ ст. 149 п. 3 пп. 16.1", "п. 8.6") in m, m
        assert ("ГК РФ ст. 1468 п. 2", "п. 8.6") in m, m
        assert validate_links({"norm_links": [{"norm": "ст. 9", "status": "verified"}]}) and \
            not validate_links({"norm_links": [{"norm": "381-ФЗ ст. 9 ч. 4", "role": "limit",
                                                "status": "verified", "checked": "2026-11-01"}]})
        card = sroot / "cards" / "contracts" / "dogovor-romashka.md"
        card.write_text(card.read_text(encoding="utf-8").replace(
            "language: ru\n", 'language: ru\nnorm_links:\n  - norm: "381-ФЗ ст. 9 ч. 4"\n    clause: "п. 8.6"\n'
            "    role: limit\n    status: verified\n    checked: 2026-11-01\n"), encoding="utf-8")
        (sroot / "originals" / "contracts" / "dogovor-romashka.md").write_text(
            "8.6. Предел по ч. 4 ст. 9 Федерального закона № 381-ФЗ.\n6.1. Заверения по ст. 431.2 ГК РФ.\n",
            encoding="utf-8")
        added = backfill(sroot, today="2026-11-01")
        meta = card_meta(card.read_text(encoding="utf-8"))
        norms = [(l["norm"], l.get("clause"), l["status"]) for l in meta["norm_links"]]
        assert ("381-ФЗ ст. 9 ч. 4", "п. 8.6", "verified") in norms and len(norms) == 2, norms  # сверенное не задвоено
        assert ("ГК РФ ст. 431.2", "п. 6.1", "unverified") in norms, norms
        assert meta["tags"] == ["x"] and added == {"contracts/dogovor-romashka": 1}, (meta, added)
        path, problems = build_norms_index(sroot)
        nidx = path.read_text(encoding="utf-8")
        assert "## 381-ФЗ ст. 9" in nidx and "| 381-ФЗ ст. 9 ч. 4 | [[dogovor-romashka]] | п. 8.6 | ограничение | сверено |" in nidx, nidx
        assert "| ГК РФ ст. 431.2 | [[dogovor-romashka]] | п. 6.1 | справочно | не сверено |" in nidx, nidx
        assert not problems, problems
        ok += 1

    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Промоушен документа из workflow/ в образец профиля.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("promote")
    p.add_argument("file")
    p.add_argument("--kind", default="sample", choices=("sample", "clause"))
    p.add_argument("--profile", default="sample", choices=("sample", "full", "analytic"))
    p.add_argument("--category", default=None, choices=(None, *CATEGORIES))
    p.add_argument("--slug", default=None)
    sub.add_parser("selftest")
    sub.add_parser("index", help="пересобрать INDEX.md и NORMS-INDEX.md по карточкам образцов")
    bf = sub.add_parser("norms-backfill", help="дописать в карточки упоминания норм из текста (status: unverified)")
    bf.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return selftest()
    if args.cmd in ("index", "norms-backfill"):
        from tools.profile.profile_lib import profile_root
        from tools.sample_intake.norm_links import backfill, build_norms_index
        sroot = Path(profile_root()).resolve() / "knowledge" / "document-samples"
        if args.cmd == "norms-backfill":
            added = backfill(sroot, dry_run=args.dry_run)
            print(f"{'Будет дописано' if args.dry_run else 'Дописано'}: {sum(added.values())} связей в {len(added)} карточек")
            if args.dry_run:
                return 0
        print(f"Индекс собран: {build_index()}")
        path, problems = build_norms_index(sroot)
        print(f"Указатель по нормам: {path}")
        for card, bad in problems.items():
            for b in bad:
                print(f"  ФОРМАТ {card}: {b}")
        return 1 if problems else 0
    try:
        res = promote(args.file, kind=args.kind, profile=args.profile,
                      category=args.category, slug=args.slug)
    except IntakeError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1
    if res["ambiguous"]:
        print(f"НЕОДНОЗНАЧНАЯ КАТЕГОРИЯ — уточнить у юриста. Кандидаты: {res['candidates']}")
        print(f"Обезличенный текст: {res['anon_source']}")
        print(f"Предложенный slug: {res['slug']}")
        return 0
    print(f"OK ({res['kind']}): категория={res['category']} slug={res['slug']}")
    if res["original_path"]:
        print(f"Оригинал размещён: {res['original_path']}")
    print(f"Далее — агент пишет карточку: {res['card_path_hint']} (status: candidate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
