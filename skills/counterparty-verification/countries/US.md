# США (US) — адаптер проверки контрагента (стаб)

Назначение: тонкий country-адаптер для контрагента, зарегистрированного в США, выбираемый country-router'ом `SKILL.md` (`skills/counterparty-verification/SKILL.md`, шаг COUNTRY ROUTER). **Глубокая автоматизация для этой юрисдикции не реализована** (§30 ТЗ — первая версия skill'а покрывает глубоко только РФ, `skills/counterparty-verification/countries/RU.md`). Проверка по этому адаптеру — ручная, по указанным официальным источникам.

Общая методология, risk-engine и оформление отчёта — не здесь: `skills/counterparty-verification/references/methodology.md`, `skills/counterparty-verification/references/risk-rules.md`, `skills/counterparty-verification/references/report-rules.md`. Санкционная проверка — `skills/counterparty-verification/references/sanctions-check.md` (для США там же уже покрыт OFAC SDN — основной перечень).

## 1. Официальные реестры

Реестр юридических лиц в США — не единый федеральный, а по штатам (**State of Incorporation**). Первый шаг — определить, в каком штате контрагент инкорпорирован (обычно указывается в реквизитах контрагента/договоре; при отсутствии данных — не предполагать штат по адресу ведения деятельности, это разные вещи).

| Источник | Даёт | Ограничение |
|---|---|---|
| **Secretary of State / Division of Corporations конкретного штата** (например, Delaware — Division of Corporations, `corp.delaware.gov`; California — `bizfileonline.sos.ca.gov`; иные штаты — свой портал) | официальный статус регистрации, дата инкорпорации, registered agent, иногда — учредительные документы | портал и формат — свои у каждого штата; точный URL для конкретного штата сверять на момент проверки, не считать один штат образцом для всех |
| **SEC EDGAR** (`https://www.sec.gov/edgar`) | для публичных компаний (эмитентов, раскрывающих информацию SEC) — финансовая отчётность (10-K/10-Q), существенные события (8-K), состав руководства | применимо только к компаниям, раскрывающим информацию SEC; не универсальный аналог ЕГРЮЛ — частная компания в EDGAR может отсутствовать, это не признак проблемы |
| **SAM.gov Exclusions** (`https://sam.gov/content/exclusions`) | список лиц, исключённых из права на федеральные контракты/гранты США — аналог российского РНП по значимости при сделках, связанных с государственными контрактами США | применимо контекстно — если сделка/контрагент связаны с федеральными контрактами США |

## 2. Что извлечь

- юридическое наименование по документам штата инкорпорации (может отличаться от торгового наименования/DBA — «doing business as»);
- State of Incorporation и registration number по этому штату;
- статус (active / in good standing / dissolved / administratively dissolved / withdrawn);
- registered agent (адрес для официальной корреспонденции в штате);
- для публичных компаний — CIK (Central Index Key) в EDGAR, последние поданные формы;
- для сделок с федеральным правительством США — статус по SAM.gov Exclusions.

## 3. Специфические red flags

- статус, отличный от `active`/`good standing` (dissolved, administratively dissolved за неуплату сборов/непредставление annual report, withdrawn);
- несовпадение юридического наименования по State of Incorporation с наименованием, под которым контрагент фактически представлен в договоре (может означать использование DBA без раскрытия юридического лица — требует уточнения, не автоматически риск);
- присутствие в SAM.gov Exclusions (контекстно, для сделок, связанных с федеральными контрактами США);
- для публичных компаний — существенные события в поданных 8-K (например, delisting, going concern doubt, смена аудитора) — оцениваются по содержанию, не по факту подачи формы как таковому.

Red flag не равнозначен автоматическому отказу — оценивается по `skills/counterparty-verification/references/methodology.md` и `skills/counterparty-verification/references/risk-rules.md`.

## 4. Границы / ограничения

- **Глубокая автоматизация не реализована.** Определение State of Incorporation, обращение к порталу конкретного штата и извлечение статуса — ручной шаг агента (навигация + структурирование), не детерминированный скрипт, аналогичный `tools/counterparty_verification/registry_extract.py` для РФ.
- **Нет единого федерального реестра ЮЛ.** Если State of Incorporation не установлен из документов сделки — это фиксируется как ограничение проверки; поиск «по всем штатам подряд» не выполняется без основания.
- **EDGAR покрывает не всех.** Отсутствие контрагента в EDGAR — не признак недобросовестности, если контрагент не является публичной компанией/эмитентом; это ограничение применимости источника, а не находка.
- Судебная практика (federal/state court records), банкротство (US Bankruptcy Court, PACER), UCC-обременения — в этой версии skill'а не автоматизированы; PACER и часть судебных систем требуют платного доступа — при недоступности это отмечается как ограничение, а не как «дел не найдено».
- Санкционная проверка — по `skills/counterparty-verification/references/sanctions-check.md` (для контрагента из США остаётся актуальным полный минимальный набор перечней раздела 1 того файла, не только SAM.gov Exclusions).
- Все ограничения — в раздел «Ограничения проверки» итогового DOCX (`skills/counterparty-verification/references/report-rules.md`).

## Связанные файлы

- `skills/counterparty-verification/SKILL.md` — оркестрация, country-router.
- `skills/counterparty-verification/references/methodology.md` — evidence-first, fault tolerance.
- `skills/counterparty-verification/references/risk-rules.md` — вердикт по совокупности.
- `skills/counterparty-verification/references/sanctions-check.md` — санкционная проверка (OFAC SDN и др.).
- `skills/counterparty-verification/references/report-rules.md` — раздел «Ограничения проверки».
- `references/web-research-tools.md` — общий слой веб-инструментов для навигации по иностранным источникам.
