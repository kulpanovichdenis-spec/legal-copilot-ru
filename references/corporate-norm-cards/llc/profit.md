---
rule_id: LLC.PROFIT
jurisdiction: RU
entity_type: LLC
topic: profit
legal_state_at: 2026-08-04
verified_at: 2026-10-08
primary_source:
  - "Федеральный закон от 08.02.1998 № 14-ФЗ «Об обществах с ограниченной ответственностью»"
primary_source_url:
  - "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=102051516&fulltext=1"
article_or_clause:
  - "ст. 28"
  - "ст. 29"
  - "ст. 33 п. 2 пп. 7"
rule_type: mandatory
amendment_risk: low
verification_required: true
---
# Распределение прибыли

<!-- norm-verification-policy:v1 -->
> **Проверка нормы.** Этот файл — указатель, а не источник права. Перед использованием нормы как правового основания вызвать `route_norm_verification(jurisdiction="RU", probe=true)`, открыть полный текст только по маршруту с `usable_now: true` и проверить редакцию, статус, pinpoint и provenance. Если пригодного маршрута нет — поставить `[ПРОВЕРИТЬ НОРМУ]`.

## Что искать в тексте нормы

- Какова периодичность и какой орган принимает решение, каким большинством?
- Какие ограничения действуют на принятие решения и на выплату?
- В какие сроки выплачивается распределённая прибыль?

## Как заполнить карточку

После открытия текста нормы: занести статьи в `article_or_clause`, ссылку на официальный текст в `primary_source_url`, тип нормы в `rule_type`, дату редакции открытого текста в `legal_state_at` и дату сверки в `verified_at`. Типы: `mandatory` — уставом изменить нельзя; `default` — действует, если устав не устанавливает иное; `optional` — устав вправе установить; `prohibition` — запрет; `exception` — исключение из общего правила. Текст нормы в карточку не копируется.
