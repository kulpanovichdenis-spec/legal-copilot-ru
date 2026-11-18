# S29 — AI, LLM, RAG и AI SaaS

<!-- norm-verification-policy:v1 -->
> **Проверка нормы.** Этот файл — навигация и методика, а не источник права. Перед использованием нормы как правового основания вызвать `route_norm_verification(jurisdiction="RU", probe=true)`, открыть полный текст только по маршруту с `usable_now: true` и проверить редакцию, статус, pinpoint и provenance. Если пригодного маршрута нет — поставить `[ПРОВЕРИТЬ НОРМУ]`.

Карточка плейбука по персональным данным (152-ФЗ). Индекс, алгоритм и правило подгрузки — `references/personal-data-playbook.md`. Подгружать только карточки сработавших сценариев, не весь набор. Общий контроль G01–G15 (`references/pd-playbook-cards/_general-layer.md`) применяется всегда, если карточка не задаёт более специального правила. Нормы и статусы доверия — `references/pd-playbook-cards/_source-registry.md`; **перед финальным выводом применить capability-маршрут из блока «Проверка нормы» выше** (CLAUDE.md «Рабочий цикл»; срез права пакета — 12.09.2026). Результат — черновик для юриста, сохранять в `workflow/`.

**Риск сценария**: Высокий · критическая зона · **Cross-links**: S07, S08, S12, S15, S16, S21, S22, S23, S25, S28

**Назначение:** квалифицировать AI как набор обычных processing activities по 152-ФЗ, а затем добавить специальный слой 243-ФЗ и AI-specific controls.

## 1. Business triggers

- public generative AI
- enterprise LLM/API
- локальная модель
- RAG/vector DB
- fine-tuning/training
- AI call analytics
- AI recruitment/scoring
- health/pharma AI
- agentic AI с доступом к корпоративным системам

## 2. Processing activities

- prompt/input
- retrieval/RAG
- inference
- logging/telemetry
- vendor processing
- training/fine-tuning
- profiling/decision
- output storage
- human review

## 3. Subjects / data

**Субъекты**
- зависят от use case: работники, клиенты, кандидаты, HCP, пациенты и др.

**Типичные данные**
- prompt/files
- извлеченные chunks
- embeddings/vector entries
- logs
- outputs
- training examples
- special/biometric data при соответствующем use case

## 4. Purpose model

- основная бизнес-задача
- RAG/inference
- quality/security logging
- training/improvement — отдельная цель
- автоматизированное решение — отдельная функция

**Правило:** одна техническая система или один бизнес-процесс могут включать несколько самостоятельных целей. Каждая цель получает собственные `legal basis / dataset / recipients / retention`.

## 5. Нормативная карта

| Source ID | Роль | Что проверять |
|---|---|---|
| `NORM-002` | core | цели/совместимость/minimization |
| `NORM-003` | core | основание и vendor role |
| `NORM-005` | conditional | special data |
| `NORM-011` | conditional | automated decision |
| `NORM-012` | conditional | localization |
| `NORM-008` | conditional | cross-border |
| `NORM-014` | core | security |
| `NORM-037` | conditional | специальный AI layer с 01.09.2026 |

Общий слой G01–G15 из `_general-layer.md` применяется всегда, если карточка прямо не устанавливает более специальное правило.

## 6. Decision tree

1. Классифицировать deployment: public SaaS / enterprise SaaS / API / local; затем функции: RAG / training / decision-making.
2. Определить, есть ли ПД в prompts/files/retrieval/logs/outputs и какие категории.
3. Для каждого AI use case сформулировать самостоятельную цель и основание; факт законного хранения данных для одной цели не разрешает автоматически training для другой.
4. Определить роль provider по каждой функции: processor / independent operator / mixed; проверить, использует ли он inputs/telemetry для собственных целей или обучения.
5. Провести S22 localization и S23 cross-border для внешней инфраструктуры.
6. Для special/health data вызвать S21; для biometrics — S15.
7. Если решение исключительно автоматизировано и порождает юридические последствия либо существенно затрагивает права/интересы, применить ст.16 и обеспечить требуемые гарантии.
8. Для RAG отдельно инвентаризировать source docs, chunks, embeddings, vector DB, retrieved context и output; не считать embeddings автоматически обезличенными.
9. Для training/fine-tuning проверить совместимость новой цели, возможность минимизации/обезличивания и фактическую исполнимость deletion.
10. После privacy-test проверить, подпадает ли система/модель под 243-ФЗ; не считать 243-ФЗ заменой 152-ФЗ.
11. Учесть, что 243-ФЗ действует с 01.09.2026, а часть специальных положений — с 01.03.2027; отслеживать подзаконные акты.

## 7. MUST controls

- AI system register с owner/provider/model/deployment/use case
- data classification и approved-data policy для каждого инструмента
- vendor role/training/retention/location assessment
- localization/cross-border check
- human-review rule для high-impact decisions
- интеграция AI в incident response
- retention/deletion design для logs/RAG/training datasets
- обновление RoPA/уведомления РКН при изменении подлежащих уведомлению параметров

## 8. Recommended controls

- по умолчанию запрещать ПД/конфиденциальные данные в public AI до отдельного approval
- enterprise/API/local deployment для чувствительных use cases
- DLP/prompt gateway/pseudonymization
- AI change-management при смене модели/terms/subprocessors
- периодический red-team/privacy test
- архитектурно разделять retrieval corpus и model provider

## 9. Evidence / документы

- AI assessment record
- data-flow diagram
- provider terms/DPA
- provider-training setting evidence
- locations/subprocessors
- model/use-case version
- human-review logs
- RAG index inventory
- deletion test
- 243-FZ applicability note

## 10. Red flags

- shadow AI с HR/client/medical data
- провайдер обучается на prompts, а компания считает его чистым processor
- неизвестные data locations
- RAG/vector DB отсутствуют в inventory
- историческую CRM используют для training без новой purpose assessment
- AI автоматически отклоняет кандидата/клиента без ст.16 test
- patient case отправляется во внешний AI без S21
- невозможно объяснить/исполнить deletion по training corpus

## 11. Regulator / expert layer

- Denuo используется как источник рисков shadow/public AI и вариантов организационного контроля; это best practice, а не самостоятельный запрет закона.
- Б-152 используется как экспертный источник по data lifecycle/training; тезис о необходимости согласия для конкретного training-use case всегда перепроверяется через цель и применимое основание закона.
- VERBA используется как отраслевой источник pharma/health AI вопросов.
- Privacy Advocates используется как методологический ориентир для vendor/process mapping.

**Правило веса:** экспертный материал используется только как аналитический ориентир. Формулировки консультантов не воспроизводятся и не превращаются в `MUST` без подтверждения первичным источником.

## 12. Uncertainty / границы вывода

- 243-ФЗ — быстро развивающийся слой; отдельные нормы и подзаконка 2027 требуют P0-мониторинга.
- Граница anonymized/pseudonymized data определяется реальной возможностью идентификации в системе; удаление ФИО или embedding само по себе не решает вопрос.
- Правовая квалификация human-in-the-loop зависит от реальной, а не номинальной роли человека в решении.

## 13. Cross-links

- `S07`
- `S08`
- `S12`
- `S15`
- `S16`
- `S21`
- `S22`
- `S23`
- `S25`
- `S28`

## 14. Источники

**Нормы (сверка — по `_source-registry.md`; verification — по capability-маршруту выше):**
- `NORM-002` — 152-ФЗ ст. 5: Принципы обработки персональных данных
- `NORM-003` — 152-ФЗ ст. 6: Условия обработки персональных данных
- `NORM-005` — 152-ФЗ ст. 10: Специальные категории персональных данных
- `NORM-011` — 152-ФЗ ст. 16: Автоматизированные решения
- `NORM-012` — 152-ФЗ ст. 18: Обязанности при сборе; локализация
- `NORM-008` — 152-ФЗ ст. 12: Трансграничная передача персональных данных
- `NORM-014` — 152-ФЗ ст. 19: Безопасность персональных данных
- `NORM-037` — 243-ФЗ: Федеральный закон от 26.07.2026 №243-ФЗ об ИИ

**Экспертный / регуляторный ориентир (навигация, не источник права; текст не воспроизводится, вес — по `_source-policy.md`):**
- `EXP-DEN-001` — Denuo: Privacy Forum 2025 — https://denuo.legal/ru/insights/releases/250626/
- `EXP-B152-001` — Б-152: Типичные ошибки обработки ПД — https://b-152.ru/tipichnye-oshibki-pri-obrabotke-personalnyh-dannyh-po-152-fz
- `EXP-VERBA-001` — VERBA LEGAL: Privacy Checkpoint 2026 — https://verba.legal/news/privacy-checkpoint-itogi-2025-i-prioritety-2026-dlya-biznesa
- `EXP-PA-002` — Privacy Advocates: Checklist третьих лиц — https://wiki.privacy-advocates.ru/chek-list_treti_lica
