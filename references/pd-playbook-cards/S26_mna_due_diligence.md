# S26 — M&A, due diligence и virtual data room

<!-- norm-verification-policy:v1 -->
> **Проверка нормы.** Этот файл — навигация и методика, а не источник права. Перед использованием нормы как правового основания вызвать `route_norm_verification(jurisdiction="RU", probe=true)`, открыть полный текст только по маршруту с `usable_now: true` и проверить редакцию, статус, pinpoint и provenance. Если пригодного маршрута нет — поставить `[ПРОВЕРИТЬ НОРМУ]`.

Карточка плейбука по персональным данным (152-ФЗ). Индекс, алгоритм и правило подгрузки — `references/personal-data-playbook.md`. Подгружать только карточки сработавших сценариев, не весь набор. Общий контроль G01–G15 (`references/pd-playbook-cards/_general-layer.md`) применяется всегда, если карточка не задаёт более специального правила. Нормы и статусы доверия — `references/pd-playbook-cards/_source-registry.md`; **перед финальным выводом применить capability-маршрут из блока «Проверка нормы» выше** (CLAUDE.md «Рабочий цикл»; срез права пакета — 12.09.2026). Результат — черновик для юриста, сохранять в `workflow/`.

**Риск сценария**: Высокий · **Cross-links**: S02, S16, S18, S21, S22, S23

**Назначение:** минимизировать передачу ПД потенциальному покупателю и не считать M&A самостоятельным безусловным исключением из 152-ФЗ.

## 1. Business triggers

- vendor due diligence
- VDR
- передача списка ключевых сотрудников/клиентов
- management interviews
- post-closing migration

## 2. Processing activities

- отбор документов
- redaction/anonymization
- доступ VDR
- Q&A
- передача покупателю
- удаление доступа отклоненных bidders

## 3. Subjects / data

**Субъекты**
- работники/менеджмент
- клиенты
- контрагенты-физлица/представители
- истцы/ответчики и др., чьи данные есть в документах

**Типичные данные**
- HR/compensation
- контакты
- договорные данные
- судебные/комплаенс сведения
- иногда special data — обычно следует исключать/редактировать

## 4. Purpose model

- оценка сделки
- подготовка/исполнение сделки
- post-closing integration

**Правило:** одна техническая система или один бизнес-процесс могут включать несколько самостоятельных целей. Каждая цель получает собственные `legal basis / dataset / recipients / retention`.

## 5. Нормативная карта

| Source ID | Роль | Что проверять |
|---|---|---|
| `NORM-002` | core | минимизация и совместимость |
| `NORM-003` | core | основание |
| `NORM-005` | conditional | special data |
| `NORM-008` | conditional | foreign bidder/VDR |
| `NORM-012` | conditional | localization |

Общий слой G01–G15 из `_general-layer.md` применяется всегда, если карточка прямо не устанавливает более специальное правило.

## 6. Decision tree

1. Определить, какие факты покупателю действительно нужны, и можно ли дать агрегат/редактированную копию.
2. Разделить стадии: teaser → DD → confirmatory DD → signing/closing → integration.
3. Для каждого уровня доступа определить legal basis и recipients.
4. Использовать anonymization/redaction/clean team для лишних идентификаторов.
5. Проверить VDR provider через S16 и foreign bidders через S22/S23.
6. После сделки/выхода bidder закрыть доступ и получить deletion confirmation.

## 7. MUST controls

- staged disclosure
- минимизация документов
- access log VDR
- special data exclusion unless strictly justified
- cleanup after bidder exits

## 8. Recommended controls

- redaction protocol и clean team для HR/competition-sensitive data
- data room index с отметкой PD-risk

## 9. Evidence / документы

- DD data-sharing memo
- VDR access list/log
- redaction rules
- NDA/DPA where applicable
- deletion certificate

## 10. Red flags

- полная HR-папка всем bidders
- medical/disciplinary files без необходимости
- иностранный VDR без S22/S23
- сохранение копий отклоненным инвестором

## 11. Regulator / expert layer

- Специальная экспертная позиция для этой карточки не требуется; приоритет первичным источникам.

**Правило веса:** экспертный материал используется только как аналитический ориентир. Формулировки консультантов не воспроизводятся и не превращаются в `MUST` без подтверждения первичным источником.

## 12. Uncertainty / границы вывода

- Основание зависит от структуры сделки и стадии; карточка не создает универсального «M&A legitimate interest».

## 13. Cross-links

- `S02`
- `S16`
- `S18`
- `S21`
- `S22`
- `S23`

## 14. Источники

**Нормы (сверка — по `_source-registry.md`; verification — по capability-маршруту выше):**
- `NORM-002` — 152-ФЗ ст. 5: Принципы обработки персональных данных
- `NORM-003` — 152-ФЗ ст. 6: Условия обработки персональных данных
- `NORM-005` — 152-ФЗ ст. 10: Специальные категории персональных данных
- `NORM-008` — 152-ФЗ ст. 12: Трансграничная передача персональных данных
- `NORM-012` — 152-ФЗ ст. 18: Обязанности при сборе; локализация
