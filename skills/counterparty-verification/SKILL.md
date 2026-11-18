---
name: counterparty-verification
description: "Проводит комплексную due-diligence проверку юрлица по официальным реестрам и формирует досье. Для быстрой карточки ЕГРЮЛ использовать counterparty-check."
---

# Counterparty Verification

## Паттерн

`sequential + domain-intelligence + multi-source` с **country-router** (определяет юрисдикцию и подключает нужный адаптер) и **low-freedom скриптами** для детерминированной механики (папка досье, парсинг DaData, сборка DOCX). Юридическое суждение (risk assessment, синтез доказательств, взвешивание под параметры сделки) остаётся за моделью — SKILL.md здесь только оркестрирует, существо разнесено по `references/` и `countries/`.

## Границы vs `counterparty-check`

Лёгкий `skills/counterparty-check/SKILL.md` — один вызов DaData и карточка ЕГРЮЛ/ЕГРИП для подстановки реквизитов в уже готовящийся документ (договор, письмо, претензия, ответ госоргану); вызывается автоматически из `contract-intake`, `contract-drafter`, `contract-review`, `amendment-drafter`, `procedural-document-drafter`, `counterparty-letter`, `gov-response`. Он не создаёт отдельного досье и не проверяет суды/банкротство/ФССП/санкции/лицензии по существу — только подсказывает юристу, что это осталось проверить.

`counterparty-verification` — самостоятельная комплексная due-diligence: отдельное досье с доказательной базой (`workflow/_counterparty/…`), многоисточниковая проверка (реестр, полномочия, финансы, суды, банкротство, ФССП, санкции, лицензии), risk assessment с учётом параметров конкретной сделки и итоговый DOCX «Лист проверки контрагента». Запускать по прямому запросу юриста либо по принятой task-card из `workflow/_counterparty/_inbox/`. Использовать, когда нужно решение «работать/не работать с контрагентом на этих условиях», а не просто актуальная шапка реквизитов. RU-регистровый шаг переиспользует `mcp__legal-overlay__dadata_party`; точки вызова `counterparty-check` из других skill-ов не меняются.

## Workflow

Fault-tolerant: недоступность одного источника не останавливает весь процесс — непройденный пункт отражается явно (`MANUAL CHECK REQUIRED` / маркер), а не молчаливо пропускается. **Обязательные выходы каждой проверки:** полученное доказательство (выписка/скриншот/выгрузка/PDF) **сохраняется файлом** в соответствующую подпапку досье (`01_Реестр`…`09_Прочее`), а извлечённые сведения сводятся в машиночитаемую `card.json` (`tools/counterparty_verification/card.py`) — не только упоминаются в тексте.

1. **INTAKE** — от юриста: наименование контрагента, страна (если известна), идентификатор, параметры сделки (сумма, аванс, отсрочка, длительность, обеспечение, критичность). Обязательный минимум и полный чек-лист — `skills/counterparty-verification/references/methodology.md`, раздел 1.
2. **IDENTIFICATION** — однозначно идентифицировать контрагента и определить страну регистрации; при неоднозначном множественном совпадении дальше не продолжать до уточнения. `skills/counterparty-verification/references/methodology.md`, раздел 2.
3. **CREATE CASE FOLDER** — создать/продолжить досье через `tools/counterparty_verification/case_folder.py` (`create_case`); версионирование `_02`/`_03` при повторной самостоятельной проверке в тот же день, существующее досье не перезаписывается. Канонический корень — `workflow/_counterparty/` **основного** чекаута; env `CV_DOSSIER_DIR` оставлен для совместимости. `find_dossier_root` распознаёт прежние русские имена как алиасы и не создаёт параллельный корень. Полученные исходные документы сразу разложить по подпапкам (`01_Реестр`…`09_Прочее`), не оставлять в корне досье.
4. **COUNTRY ROUTER** — по стране из шага 2 загрузить нужный `skills/counterparty-verification/countries/<CC>.md` — см. «Country router» ниже.
5. **REGISTRY** — проверка по официальному реестру страны регистрации; для РФ — `mcp__legal-overlay__dadata_party` → `tools/counterparty_verification/registry_extract.py` (`extract`, red-flag флаги как вход для модели, не готовый вердикт), для остальных стран — по загруженному country-адаптеру. Материалы — в подпапку досье `01_Реестр/`.
6. **AUTHORITY** — проверка полномочий подписанта (ЕИО / доверенность) по 12-пунктовому sub-workflow `skills/counterparty-verification/references/authority-check.md`. Материалы — в `02_Полномочия/`.
7. **FINANCIAL** — открытые финансовые показатели контрагента (для РФ — из карточки реестра плюс доп. проверка при необходимости). Материалы — в `03_Финансы/`.
8. **LITIGATION** — судебные споры (для РФ — КАД, горизонт ≥3 года и отдельно динамика за 6–12 мес.); большое число дел само по себе не автоматический негатив. Материалы — в `04_Суды/`.
9. **INSOLVENCY / FEDRESURS** — банкротные и предбанкротные сигналы (ЕФРСБ/Федресурс, КАД). Материалы — в `05_Банкротство_Федресурс/`.
10. **ENFORCEMENT** — исполнительные производства (ФССП); CAPTCHA/защиту не обходить → `MANUAL CHECK REQUIRED` в итоговый лист. Материалы — в `06_Исполнительные_производства/`.
11. **REGULATORY / LICENSES** — контекстно по предмету сделки: нужна ли лицензия/спецразрешение и действует ли она. Материалы — в `08_Лицензии_Регуляторика/`.
12. **SANCTIONS** — проверка по минимум OFAC / EU / UK / RU-перечням независимо от страны контрагента; `POTENTIAL MATCH` → `MANUAL REVIEW`, вывод не делается по совпадению названия. `skills/counterparty-verification/references/sanctions-check.md`. Материалы — в `07_Санкции/`.
13. **TRANSACTION RISK** — параметры сделки (сумма, аванс, отсрочка, длительность, обеспечение, критичность для бизнеса) масштабируют вес уже собранных фактов; 100 тыс. ₽ ≠ 100 млн ₽.
14. **DOCUMENT REQUEST** — точечный список недостающих документов с объяснимой целью запроса каждого, не «максимальный пакет по умолчанию». `skills/counterparty-verification/references/methodology.md`, раздел 6.
15. **RISK ASSESSMENT** — итоговый вердикт по совокупности обстоятельств (не арифметика баллов): `GREEN` / `YELLOW` / `RED` / `MANUAL CHECK REQUIRED` / `N/A` по строкам таблицы. `skills/counterparty-verification/references/risk-rules.md`.
16. **DOCX REPORT + CARD** — сборка «Лист проверки контрагента» через `tools/counterparty_verification/report_docx.py` (`build_report`); структура разделов и evidence-first mapping — `skills/counterparty-verification/references/report-rules.md`. **Наряду с DOCX** собрать машиночитаемую `card.json` (`tools/counterparty_verification/card.py`, `build_card`) и вести `case-context.md` — единый информационный слой дела.
17. **SAVE CASE + RECHECK/COMPARE** — сохранить досье по структуре; если для этого контрагента уже есть более раннее досье — предложить сравнение, само старое досье не менять. См. «RECHECK / COMPARE» ниже.

## Country router

Страна определяется на шаге IDENTIFICATION и задаёт, какой адаптер грузится дальше — сам основной workflow при этом не меняется:

| Страна | Файл |
|---|---|
| Россия (глубокий адаптер, единственный в первой версии) | `skills/counterparty-verification/countries/RU.md` |
| Китай (стаб) | `skills/counterparty-verification/countries/CN.md` |
| США (стаб) | `skills/counterparty-verification/countries/US.md` |
| ЕС (стаб) | `skills/counterparty-verification/countries/EU.md` |
| Республика Корея (стаб) | `skills/counterparty-verification/countries/KR.md` |
| Любая другая юрисдикция | `skills/counterparty-verification/countries/OTHER.md` (generic-протокол) |

Расширяемость: новая регулярная юрисдикция — это новый файл `countries/<CC>.md` в том же формате (Официальные реестры → Что извлечь → Специфические red flags → Границы/ограничения); ядро `SKILL.md` не трогается. Коммерческий агрегатор не заменяет доступный официальный источник страны.

## Скрипты

- `tools/counterparty_verification/case_folder.py` — `create_case(name, date=None, base=None, continue_same=False)`: санитизация имени, версионирование `_02`/`_03`, скаффолд подпапок досье; не перезаписывает существующее. `find_dossier_root(workflow_dir)` переиспользует `_counterparty` и прежние русские алиасы; override имени — env `CV_DOSSIER_DIR`.
- `tools/counterparty_verification/registry_extract.py` — `extract(dadata_response)`: сырой ответ DaData Suggest Party → нормализованная карточка реестра + детерминированные red-flag флаги (вход для модели, финальный вердикт — не здесь).
- `tools/counterparty_verification/report_docx.py` — `build_report(case_data, out_path)`: программная сборка DOCX «Лист проверки» (python-docx, `eastAsia` для кириллицы) + `extract_docx_text` для обратной верификации после сборки.
- `tools/counterparty_verification/card.py` — `build_card(data, out_path)`: валидация и запись машиночитаемой `card.json` (единый информационный слой дела); `validate(data)` возвращает список проблем контракта.

Контракт данных дела, отчёта и карточки — `tools/counterparty_verification/schema.md`. Досье — в `workflow/_counterparty/`; в worktree-сессии писать по абсолютному пути в **основную** `workflow/`, не в копию worktree.

## Принципы

1. Не продолжать до **однозначной идентификации** контрагента (несколько похожих совпадений → уточнить у юриста). Недостающие для **оценки** вводные (роль в сделке, сумма, исключительность лицензии и т. п.) — **спросить у юриста, а не подменять флажками-догадками** в отчёте.
2. **«Не найдено» ≠ «риска нет».** Технически непроведённая/недоступная проверка **и собственные недоработки** идут в раздел «Ограничения проверки», **НЕ** в «Выявленные риски» (риски — только про контрагента: его статус, финансы, суды, банкротство, санкции и т. п.).
3. **Источник сначала реально пробуется; защиту (CAPTCHA и т. п.) не обходить.** В отчёте фиксируется **фактическая** причина незавершённости (инструмент недоступен / CAPTCHA / сайт не отвечает / платный доступ), а не предполагаемая — статус `MANUAL CHECK REQUIRED`.
4. Не называть контрагента «надёжным» или «годным к подписанию» — только уровень допустимости (`GREEN`/`YELLOW`/`RED`) и обоснование; решение о работе с контрагентом — за юристом и бизнесом.
5. **Evidence-first.** Каждый существенный вывод связан с источником, а полученное доказательство **сохраняется файлом** (выписка/скриншот/выгрузка/PDF) в подпапку досье (`01_Реестр`…`09_Прочее`), не только упоминается. Извлечённые сведения сводятся в машиночитаемую `card.json` (`tools/counterparty_verification/card.py`). В рабочем анализе — `FACT`/`ANALYSIS`/`RISK`/`RECOMMENDATION` (`skills/counterparty-verification/references/methodology.md`).
6. **Параметры сделки масштабируют вердикт.** Один и тот же факт весит по-разному при сумме 100 тыс. ₽ и 100 млн ₽, при полной предоплате и постоплате.
7. **Старое досье не перезаписывать; не выдумывать сведения; называть документы точно** (лист записи ЕГРЮЛ о конкретном событии ≠ выписка из ЕГРЮЛ). Повторная проверка — новое досье или явный `_02`/`_03`; отсутствующие данные — маркеры неполноты из `references/citation-rules.md`, а не правдоподобная догадка.

## RECHECK / COMPARE

Если у контрагента уже есть более раннее досье в корне, который вернул `find_dossier_root`, — на шаге SAVE CASE предложить юристу режим сравнения, а не создавать параллельное досье без связи со старым. Старые русские имена корня остаются алиасами поиска. Сверяются: смена директора/участников/адреса, пометки недостоверности, банкротные сообщения, судебная нагрузка, исполнительные производства, финансовые показатели, санкционный статус и лицензии. Старое досье не изменяется.

## Финал

По завершении — короткий итог юристу: вердикт (`GREEN`/`YELLOW`/`RED`/с оговоркой `MANUAL CHECK REQUIRED` по части пунктов), число выявленных рисков, число документов к дозапросу, путь к DOCX «Лист проверки» в досье. Результат — черновик due diligence; финальное решение о заключении/продолжении сделки с контрагентом — за юристом и бизнесом (см. принцип 4).

## Связанные файлы

Skill-local references:
- `skills/counterparty-verification/references/methodology.md` — INTAKE, идентификация, evidence-first, иерархия источников, fault tolerance.
- `skills/counterparty-verification/references/risk-rules.md` — вердикты `GREEN`/`YELLOW`/`RED`/`MANUAL`/`N/A`, взвешивание под сделку, анти-паттерны.
- `skills/counterparty-verification/references/authority-check.md` — 12-пунктовый sub-workflow проверки полномочий подписанта.
- `skills/counterparty-verification/references/sanctions-check.md` — санкционные перечни, `POTENTIAL MATCH` → `MANUAL REVIEW`.
- `skills/counterparty-verification/references/report-rules.md` — структура DOCX «Лист проверки» и evidence-first mapping.

Country-адаптеры:
- `skills/counterparty-verification/countries/RU.md`
- `skills/counterparty-verification/countries/CN.md`
- `skills/counterparty-verification/countries/US.md`
- `skills/counterparty-verification/countries/EU.md`
- `skills/counterparty-verification/countries/KR.md`
- `skills/counterparty-verification/countries/OTHER.md`

Общие references проекта:
- `references/docx-generation.md` — принцип программной сборки .docx, техника кириллицы.
- `references/risk-scale.md` — общая шкала рисков проекта.
- `references/citation-rules.md` — реестр маркеров неполноты.
- `references/web-research-tools.md` — веб-инструменты для источников за пределами локальных баз.
- `references/confidentiality-rules.md` — что можно/нельзя передавать во внешние сервисы (DaData и др.).
- `references/dadata-mcp-setup.md` — прямое локальное подключение DaData через единый Overlay (`mcp__legal-overlay__dadata_party`).

Смежный skill:
- `skills/counterparty-check/SKILL.md` — лёгкая карточка ЕГРЮЛ/ЕГРИП для подстановки реквизитов (см. «Границы» выше).
