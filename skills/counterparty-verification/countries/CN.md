# Китай (CN) — адаптер проверки контрагента (стаб)

Назначение: тонкий country-адаптер для контрагента, зарегистрированного в КНР, выбираемый country-router'ом `SKILL.md` (`skills/counterparty-verification/SKILL.md`, шаг COUNTRY ROUTER). **Глубокая автоматизация для этой юрисдикции не реализована** (§30 ТЗ — первая версия skill'а покрывает глубоко только РФ, `skills/counterparty-verification/countries/RU.md`). Проверка по этому адаптеру — ручная, по указанным официальным источникам; агент выполняет навигацию и структурирование, а не автоматизированный парсинг реестра.

Общая методология (evidence-first, FACT/ANALYSIS/RISK/RECOMMENDATION), risk-engine и оформление отчёта — не здесь: `skills/counterparty-verification/references/methodology.md`, `skills/counterparty-verification/references/risk-rules.md`, `skills/counterparty-verification/references/report-rules.md`. Санкционная проверка — `skills/counterparty-verification/references/sanctions-check.md` (применяется независимо от страны регистрации).

## 1. Официальные реестры

| Источник | Даёт | Ограничение |
|---|---|---|
| **National Enterprise Credit Information Publicity System (GSXT)**, 国家企业信用信息公示系统 | официальная регистрационная карточка китайского юридического лица | интерфейс на китайском языке; официальный URL (обычно вида `gsxt.gov.cn`, точный адрес и структура портала меняются) — сверять непосредственно перед использованием, не полагаться на когда-то сохранённую ссылку |
| Региональные / отраслевые реестры (провинциальные Administration for Market Regulation) | дополнительные региональные сведения | доступность и формат различаются по провинциям |

## 2. Что извлечь

Из GSXT (или официального перевода/выписки, если контрагент предоставил её сам):

- юридическое наименование на китайском языке (chinese legal name) и, если есть, официальное английское наименование;
- Unified Social Credit Code (统一社会信用代码) — основной идентификатор, аналог ОГРН+ИНН по значимости для идентификации;
- статус регистрации (действующая / приостановлена / аннулирована / исключена);
- legal representative (法定代表人) — аналог ЕИО для целей проверки полномочий подписанта (`skills/counterparty-verification/references/authority-check.md` применяется по существу, но подтверждающие документы — китайские);
- registered address (юридический адрес);
- отметки об abnormal operations (异常经营) — включение в список предприятий с отклонениями в ведении деятельности;
- отметки о serious illegal/dishonest conduct (严重违法失信) — аналог «недобросовестности», близкий по смыслу к российским red-flag-статусам.

## 3. Специфические red flags

- статус, отличный от действующего (приостановлена/аннулирована/исключена);
- отметка abnormal operations;
- отметка serious illegal/dishonest (严重违法失信名单) — рассматривать как существенный сигнал, требующий отдельного внимания при оценке риска;
- несовпадение legal representative по GSXT с лицом, фактически подписывающим договор со стороны контрагента (аналог российского пункта 2 в `skills/counterparty-verification/references/authority-check.md`).

Red flag не равнозначен автоматическому отказу — оценивается по методологии `skills/counterparty-verification/references/methodology.md` и risk-engine `skills/counterparty-verification/references/risk-rules.md`, как и для РФ.

## 4. Границы / ограничения

- **Глубокая автоматизация не реализована.** Проверка ведётся вручную по GSXT и (при наличии) официальному переводу выписки; агент не выполняет автоматизированный парсинг китайского реестра, аналогичный `tools/counterparty_verification/registry_extract.py` для РФ.
- **Языковой барьер.** Источники — на китайском языке; перевод ключевых полей (наименование, статус, legal representative) должен быть либо официальным (нотариальный/сертифицированный перевод, предоставленный контрагентом), либо явно помечен как рабочий перевод агента, требующий сверки юристом.
- **Доступность.** Отдельные функции GSXT (детальная история изменений, полные учредительные документы) могут требовать регистрации на портале или быть доступны только на китайском интерфейсе без экспорта на английский — при недоступности конкретного раздела это отмечается как ограничение, а не как «сведений нет».
- Судебная практика, банкротство, исполнительные производства по контрагенту из КНР — в этой версии skill'а не автоматизированы; при необходимости — отдельный ручной запрос юриста, отражается как ограничение проверки.
- Санкционная проверка (OFAC/EU/UK/применимые российские перечни) выполняется по `skills/counterparty-verification/references/sanctions-check.md` независимо от того, что глубокая автоматизация реестра для КНР отсутствует.
- Все перечисленные ограничения фиксируются в разделе «Ограничения проверки» итогового DOCX (`skills/counterparty-verification/references/report-rules.md`), а не опускаются молча.

## Связанные файлы

- `skills/counterparty-verification/SKILL.md` — оркестрация, country-router.
- `skills/counterparty-verification/references/methodology.md` — evidence-first, fault tolerance.
- `skills/counterparty-verification/references/risk-rules.md` — вердикт по совокупности.
- `skills/counterparty-verification/references/authority-check.md` — методология проверки полномочий (по существу применима, документы — китайские).
- `skills/counterparty-verification/references/sanctions-check.md` — санкционная проверка.
- `skills/counterparty-verification/references/report-rules.md` — раздел «Ограничения проверки».
- `references/web-research-tools.md` — общий слой веб-инструментов (agent-browser/Tavily/WebFetch) для навигации по иностранным источникам.
