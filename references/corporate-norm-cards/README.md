# Карточки-указатели норм ООО

Слой 1 модуля «Corporate Governance»: навигация по нормам, на которые опираются правила устава. Методика — `references/corporate-governance-method.md`, раздел 6.

Карточка `llc/<тема>.md` отвечает на вопросы «какие статьи регулируют тему, что в них искать, какого типа норма, как быстро она меняется и когда её открывали живым маршрутом». Текста нормы карточка не содержит и правовым основанием не является. Перед использованием нормы вызывается `route_norm_verification(jurisdiction="RU", probe=true)` и полный текст открывается по маршруту с `usable_now: true`.

## Формат

Frontmatter (ТЗ §4.1): `rule_id` (`LLC.<ТЕМА>`), `jurisdiction: RU`, `entity_type: LLC`, `topic`, `legal_state_at`, `verified_at`, `primary_source` (список актов), `primary_source_url` (список ссылок на официальный текст), `article_or_clause` (список статей), `rule_type` (`mandatory | default | optional | prohibition | exception`), `amendment_risk` (`low | medium | high | unknown`), `verification_required: true`.

Тело: блок проверки нормы, раздел «Что искать в тексте нормы» (вопросы к тексту), раздел «Как заполнить карточку».

## Жизненный цикл

1. Скелет: статьи, даты и `rule_type` пусты, `amendment_risk: unknown`.
2. Заполнение при первом сопоставлении правила с законом: статьи заносятся только после открытия текста живым маршрутом, вместе с `primary_source_url`, `rule_type`, `legal_state_at` и `verified_at`.
3. Пересмотр при каждом Legal Freshness Check: расхождение с живым текстом обновляет карточку и фиксируется результатом `changed` в правиле.

Проверка карточек: `python tools/corporate_governance/governance.py validate-cards` (16 тем таксономии, заполненная карточка обязана нести даты, тип нормы и ссылку на официальный текст, цитаты закона в карточке запрещены).
