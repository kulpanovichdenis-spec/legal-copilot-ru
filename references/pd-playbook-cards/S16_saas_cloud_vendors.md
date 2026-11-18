# S16 — SaaS, cloud, CRM, hosting и IT-support

<!-- norm-verification-policy:v1 -->
> **Проверка нормы.** Этот файл — навигация и методика, а не источник права. Перед использованием нормы как правового основания вызвать `route_norm_verification(jurisdiction="RU", probe=true)`, открыть полный текст только по маршруту с `usable_now: true` и проверить редакцию, статус, pinpoint и provenance. Если пригодного маршрута нет — поставить `[ПРОВЕРИТЬ НОРМУ]`.

Карточка плейбука по персональным данным (152-ФЗ). Индекс, алгоритм и правило подгрузки — `references/personal-data-playbook.md`. Подгружать только карточки сработавших сценариев, не весь набор. Общий контроль G01–G15 (`references/pd-playbook-cards/_general-layer.md`) применяется всегда, если карточка не задаёт более специального правила. Нормы и статусы доверия — `references/pd-playbook-cards/_source-registry.md`; **перед финальным выводом применить capability-маршрут из блока «Проверка нормы» выше** (CLAUDE.md «Рабочий цикл»; срез права пакета — 12.09.2026). Результат — черновик для юриста, сохранять в `workflow/`.

**Риск сценария**: Высокий · критическая зона · **Cross-links**: S17, S22, S23, S25, S29

**Назначение:** начать vendor analysis с фактической роли поставщика, затем проверить поручение, безопасность, локализацию и трансграничность.

## 1. Business triggers

- облачная CRM/HRM
- SaaS
- hosting
- техническая поддержка с доступом к production
- email/collaboration platform
- AI SaaS

## 2. Processing activities

- хранение
- техническая обработка
- доступ поддержки
- резервное копирование
- telemetry/logging
- собственная аналитика провайдера

## 3. Subjects / data

**Субъекты**
- зависят от системы: работники, клиенты, кандидаты, HCP и др.

**Типичные данные**
- business dataset
- учетные записи
- логи/telemetry
- backup
- support tickets

## 4. Purpose model

- основная цель компании
- оказание облачной услуги
- security/support
- собственные цели провайдера — если есть

**Правило:** одна техническая система или один бизнес-процесс могут включать несколько самостоятельных целей. Каждая цель получает собственные `legal basis / dataset / recipients / retention`.

## 5. Нормативная карта

| Source ID | Роль | Что проверять |
|---|---|---|
| `NORM-003` | core | поручение обработки и роли |
| `NORM-014` | core | безопасность |
| `NORM-012` | conditional | локализация |
| `NORM-008` | conditional | cross-border |
| `NORM-017` | core | отражение процессов в уведомлении |

Общий слой G01–G15 из `_general-layer.md` применяется всегда, если карточка прямо не устанавливает более специальное правило.

## 6. Decision tree

1. Описать фактические операции провайдера, включая логи/telemetry/support.
2. Определить роль по каждой цели: processor, independent operator или mixed.
3. Если processor — проверить обязательные элементы поручения ч.3 ст.6.
4. Проверить subprocessor chain и locations.
5. Провести S22 localization test отдельно от S23 cross-border test.
6. Проверить incident SLA, deletion/return и exit.
7. Если provider использует данные для model training/собственной analytics — квалифицировать отдельную цель и, при AI, S29.

## 7. MUST controls

- vendor role memo
- договор/поручение с обязательными условиями, когда применимо
- security requirements и подтверждение мер
- перечень subprocessors/locations
- incident escalation, позволяющий оператору соблюсти 24 часа
- deletion/return on termination

## 8. Recommended controls

- единый vendor questionnaire и re-assessment при существенном изменении услуги
- запрет на secondary use без отдельного согласования

## 9. Evidence / документы

- DPA/processing clause
- vendor assessment
- subprocessor list
- data flow/location map
- security evidence
- exit certificate

## 10. Red flags

- NDA вместо поручения
- неизвестно, где размещены production/backups
- поставщик свободно использует данные для своих целей, но назван процессором
- SLA об инциденте 72 часа или «в разумный срок»
- невозможность удалить данные после выхода

## 11. Regulator / expert layer

- Б-152 и Privacy Advocates используются как источники идей для role/vendor assessment; чек-лист сформирован независимо.

**Правило веса:** экспертный материал используется только как аналитический ориентир. Формулировки консультантов не воспроизводятся и не превращаются в `MUST` без подтверждения первичным источником.

## 12. Uncertainty / границы вывода

- Название роли в договоре не решает вопрос; квалификация строится по фактическому определению целей и операций.

## 13. Cross-links

- `S17`
- `S22`
- `S23`
- `S25`
- `S29`

## 14. Источники

**Нормы (сверка — по `_source-registry.md`; verification — по capability-маршруту выше):**
- `NORM-003` — 152-ФЗ ст. 6: Условия обработки персональных данных
- `NORM-014` — 152-ФЗ ст. 19: Безопасность персональных данных
- `NORM-012` — 152-ФЗ ст. 18: Обязанности при сборе; локализация
- `NORM-008` — 152-ФЗ ст. 12: Трансграничная передача персональных данных
- `NORM-017` — 152-ФЗ ст. 22: Уведомление Роскомнадзора

**Экспертный / регуляторный ориентир (навигация, не источник права; текст не воспроизводится, вес — по `_source-policy.md`):**
- `EXP-B152-002` — Б-152: Передача ПД третьим лицам — https://b-152.ru/peredacha-pdn-tretim-licam-yuridicheskie-osnovaniya
- `EXP-PA-002` — Privacy Advocates: Checklist третьих лиц — https://wiki.privacy-advocates.ru/chek-list_treti_lica
