# Data contract — counterparty_verification

## Досье и именование (case_folder.py)

- Корень: `workflow/_counterparty/`; в worktree — основной чекаут по абсолютному пути. Override для совместимости — env **`CV_DOSSIER_DIR`**, актуальное значение — `dossier_subdir()`.
- **Переиспользование существующего корня.** `find_dossier_root(workflow_dir)` находит канонический `_counterparty` и прежние русские алиасы (`! проверка контрагента`, `Проверка контрагентов`), поэтому `_default_base()`/`create_case(base=None)` не создают параллельное досье и RECHECK/COMPARE видит прежние проверки.
- Имя досье: `YYYY.MM.DD_<sanitize(name)>` (ОПФ входит в name, напр. `2026.08.28_Ромашка_ООО`).
- `sanitize_name`: кавычки/скобки `«»""()` → пробел; запрещённые ФС `<>:"/\|?*` → пробел; пробелы → `_`; схлопывание `_`, обрезка хвостовых `_`/`.`.
- Версионирование: та же дата, самостоятельная проверка → суффикс `_02`, `_03`; продолжение той же (`continue_same=True`) → существующее досье, `created=False`. Старое досье никогда не перезаписывается.
- `create_case(...) -> dict`: `name, folder, base, root, subfolders{registry,authority,financial,litigation,insolvency,enforcement,sanctions,regulatory,other}, report_docx, created` (`base` — использованный корень досье).
- Подпапки создаются лениво (`ensure_subfolder`), когда появляется материал; не обязательны заранее.
- Имена файлов: `file_name(name,date,doc_type,ext)` → `YYYY.MM.DD_<name>_<doc_type>.<ext>`.

## Карточка реестра (registry_extract.py)

- Вход: ответ DaData Suggest Party (`suggestions[0].data`), как отдаёт `mcp__legal-overlay__dadata_party`.
- Выход: `{status, markers, card, flags}`.
  - `status`: `found` | `not_found` (`[DADATA НЕ НАЙДЕНО]`) | `unavailable` (`[DADATA НЕДОСТУПНА]`).
  - `card`: full_name, short_name, inn, kpp, ogrn, opf, status, registration_date, age_days, address, management_name, management_post, capital, okved, okved_count, branch_count, msp_category.
  - `flags`: только **объективные** — `status_*` (ликвидация/банкротство/реорганизация, red), `young_company` (<365 дн., yellow), `min_capital` (≤10000 руб., yellow).
- Флаги — вход для модели, не финальный вердикт. Недостоверность адреса/ЕИО/участников, массовость — **не** извлекаются автоматически (DaData не отдаёт надёжно); проверяются моделью по ЕГРЮЛ-выписке (authority-check.md) и помечаются вручную.

## case_data для DOCX (report_docx.py)

```json
{
  "contragent": {"name": "...", "ids": "ИНН.../ОГРН...", "country": "РФ"},
  "check_date": "ДД.ММ.ГГГГ",
  "transaction": ["строки параметров сделки"],
  "verdict": "green|yellow|red",
  "checks": [{"name": "Правоспособность", "result": "...", "risk": "green|yellow|red|manual|na"}],
  "risks": ["..."], "requests": ["..."], "recommendations": ["..."],
  "limitations": ["..."], "sources": ["название — URL — дата — файл"]
}
```

- `verdict` строго `green|yellow|red` (иначе ReportError); формулировка «надёжен» запрещена.
- `risk` в строках таблицы → эмодзи 🟢/🟡/🔴/⚪(manual)/N/A.
- Каждая строка `sources` — название, URL, дата, сохранённый файл (evidence-first).

## Машиночитаемая карточка `card.json` (card.py)

Единый машиночитаемый слой дела — сохраняется в корень досье как `card.json` (обязательный выход наряду с DOCX). Собирается через `build_card(data, out_path)`; при невалидности — `CardError`.

- Обязательные верхнеуровневые ключи: `schema`, `check_date`, `jurisdiction`, `identity`, `verdict`.
- `identity` — наименование (`full_name`|`short_name`|`name`) И хотя бы один идентификатор (`inn`|`ogrn`|`reg_number`).
- `verdict` — строка `green|yellow|red` ЛИБО объект с полем `level` из того же набора (доп. поля свободны: `risk`, `summary`).
- Остальной состав (identity-детали, address, eio, participants, financials, checks, authority_thresholds, transaction, sources) — свободная структура: `card.py` валидирует контракт, не диктует полный набор. `validate(data) -> list[str]` возвращает список проблем (пусто = валидна).
- Рядом ведётся `case-context.md` (человекочитаемый контекст с YAML-frontmatter, по `templates/agent-notes/case-context-template.md`).
