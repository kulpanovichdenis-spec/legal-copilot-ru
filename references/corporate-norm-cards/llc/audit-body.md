---
rule_id: LLC.AUDIT_BODY
jurisdiction: RU
entity_type: LLC
topic: audit_body
legal_state_at: 2026-08-04
verified_at: 2026-10-08
primary_source:
  - "Федеральный закон от 08.02.1998 № 14-ФЗ «Об обществах с ограниченной ответственностью»"
primary_source_url:
  - "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd=102051516&fulltext=1"
article_or_clause:
  - "ст. 33 п. 2 пп. 5, 10"
  - "ст. 47"
  - "ст. 48"
rule_type: optional
amendment_risk: medium
verification_required: true
---
# Ревизионная комиссия, ревизор и аудит

<!-- norm-verification-policy:v1 -->
> **Проверка нормы.** Этот файл — указатель, а не источник права. Перед использованием нормы как правового основания вызвать `route_norm_verification(jurisdiction="RU", probe=true)`, открыть полный текст только по маршруту с `usable_now: true` и проверить редакцию, статус, pinpoint и provenance. Если пригодного маршрута нет — поставить `[ПРОВЕРИТЬ НОРМУ]`.

## Что искать в тексте нормы

- Когда образование ревизионного органа обязательно или возможно и кто его избирает?
- В каких случаях обязателен аудит?

## Как заполнить карточку

После открытия текста нормы: занести статьи в `article_or_clause`, ссылку на официальный текст в `primary_source_url`, тип нормы в `rule_type`, дату редакции открытого текста в `legal_state_at` и дату сверки в `verified_at`. Типы: `mandatory` — уставом изменить нельзя; `default` — действует, если устав не устанавливает иное; `optional` — устав вправе установить; `prohibition` — запрет; `exception` — исключение из общего правила. Текст нормы в карточку не копируется.
