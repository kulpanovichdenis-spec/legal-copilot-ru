# Слой знаний в профиле (profile/knowledge/)

Персональный слой переиспользуемого знания в overlay `profile/`. Контент в
`.gitignore` (конфиденциально, едет с профилем через `tools/profile/portable.py`),
в git — только скелет. Связь со скиллами — по соглашению: базовый skill читает
фиксированный путь в `profile/`.

## Домены

- `profile/knowledge/products/`  — свойства/состав/показания/регистрация продуктов.
  Потребитель: `skills/fas-ad-practice-search` (свойства продукта для анализа рекламы).
- `profile/knowledge/corporate/` — корпоративные документы конкретного лица
  (устав, доверенности, полномочия подписантов, ЕИО, структура). Потребитель:
  `skills/charter-review` (правила компании из устава, подпапка `entities/`)
  и будущие корпоративные skills.
- `profile/knowledge/ip/` — внутренний реестр товарных знаков (выгрузка xlsx → каталог HTML + индекс для агента).
  Свой цикл без карточек: `tools/ip_registry`, правила — `references/ip-registry-layer.md`. Потребитель: `skills/ip-registry`.
- `profile/knowledge/brand/` — фирменный стиль компании (бланки писем). Свой цикл без карточек:
  `tools/brand_kit` (`scan` → `brand.yaml`), правила — `references/brand-letterhead.md`. Потребители:
  `skills/counterparty-letter`, `skills/gov-response`.
- `profile/knowledge/case-studies/` — обезличенные карточки споров. Правила —
  `references/case-knowledge-layer.md`. Навигатор собирается `build-index`.

Каждый домен: `_inbox/` (сюда кладут исходники) · `cards/` (карточки) ·
`originals/` (исходники после разбора).

## Жизненный цикл карточки

`_inbox/` → проход `tools/knowledge_ingest/intake.py` (класс A) пишет ЧЕРНОВИК в
`cards/` со `status: needs_enrichment`, оригинал → `originals/` → агент по
`skills/knowledge-intake` (класс B) структурирует факты и ставит `status: enriched`
→ юрист подтверждает и ставит `verification: verified`.

Статус живёт **только во frontmatter**; карточка не переезжает между папками.
`candidates/ verified/ superseded/` — отдельный общий knowledge-слой roadmap, с
доменами не смешивается.

## Схема карточки (cards/<slug>.md)

```yaml
---
type: product            # product | corporate
name: "<основное наименование>"
aliases: ["<синоним>", "<бренд>", "<торговое наименование>"]
reg_number: "<РУ/СГР | ОГРН/ИНН>"   # или null
source_files: ["originals/<файл>"]
verification: candidate  # candidate | verified (verified — только юрист)
status: needs_enrichment # needs_enrichment | enriched
ingest_backend: <backend>
updated: <YYYY-MM-DD>
---
```

Тело: факты, у каждого — ссылка на первоисточник (файл + место/пункт). Где данных
нет — маркер по `references/citation-rules.md` (`[ПРОВЕРИТЬ ХАРАКТЕРИСТИКИ]` для
физ./тех. параметров, `[ПРОВЕРИТЬ ИСТОЧНИК]` / `[ПРОВЕРИТЬ ФАКТ]`), а не догадка.
Необязательно — `<slug>.notes.md` рядом: пометки юриста (внутренний контекст, не
факт-источник).

## Как skill потребляет карточки

1. Найти карточку домена в `cards/` через Grep/Glob по frontmatter (`name`/`aliases`).
2. Брать факты только из карточки со `status: enriched`. `needs_enrichment` —
   предложить собрать через `skills/knowledge-intake`. Карточки нет, но в `_inbox/`
   есть файлы — то же. Нет данных — маркер, не выдумывать.
3. Карточка — навигация к первоисточнику в `originals/`, **не самостоятельное
   правовое основание**. Правовой вывод проверяется обычным циклом (CLAUDE.md).

## Корпоративный домен: профиль компании (entities/)

Поверх карточек документов домен `corporate/` ведёт профиль компании в `profile/knowledge/corporate/entities/<slug>/`: `sources.yaml` (реестр документов и редакций), `rules.yaml` (правила из устава со страницей, пунктом и дословной цитатой), `profile.yaml` (классификация компании, участники, органы, назначения, допущения), `audit.jsonl` (append-only аудит) и `_work/` (страницы PNG и OCR-текст, регенерируемые). Карточка в `cards/` по-прежнему отвечает на вопрос «что за документ», а правила и профиль — «что из него следует» и «каково состояние компании». Записи в `entities/` ведёт `tools/corporate_governance/governance.py` по `skills/charter-review/SKILL.md`; статус `verified` ставится командой `confirm` только по решению юриста (`--by` называет подтвердившего). Методика — `references/corporate-governance-method.md`. Содержимое `entities/` в `.gitignore`, в git идёт только скелет (`.gitkeep`).

## Границы

- Слой не трогает `relink.py`/`INDEX.md` (INDEX индексирует skills/overrides/templates).
- Единый локальный watcher без LLM следит за `_inbox/` доменов `products`,
  `corporate` и `compliance`, создаёт только draft-карточку и task-card. Смысловое
  обогащение остаётся отдельным запуском `knowledge-intake`; его можно выполнить on-demand.
- Материалы клиента — без cloud-OCR (`references/document-ingestion.md`).
