# tools/ip_registry — реестр товарных знаков

Класс A (детерминированно, без LLM). Правила слоя — `references/ip-registry-layer.md`, skill — `skills/ip-registry/SKILL.md`.

Данные — `profile/knowledge/ip/` (в `.gitignore`):
`_inbox/` → watcher (канал `knowledge_ip`) → `originals/ДАТА_имя.xlsx`, `data/events.jsonl` (журнал, главный источник),
`data/base.json` (снимок из журнала; в нём контакты поверенных), `data/marks/`, `index/*.md`, `catalog.html`,
`documents/` (принятые документы и их текст `.md`), `pending/<doc_id>.json` (карточки), `pending/<doc_id>.facts.json` (факты агента),
`changes/ДАТА.md`, `changes/ДАТА-документ-<имя>.md`, `changes/ДАТА-сверка-excel.md`, `products.yaml` (правит юрист).

    python -m tools.ip_registry migrate                  # старый data/registry.json -> журнал; копия в backups/registry.json.bak
    python -m tools.ip_registry rebuild                  # пересобрать снимок, индекс и каталог из журнала
    python -m tools.ip_registry ingest "путь\к\реестру.xlsx"   # xlsx: первичная загрузка, затем только сверка; документ: карточка в pending/
    python -m tools.ip_registry pending                  # JSON-список открытых карточек
    python -m tools.ip_registry apply-facts pending/<doc_id>.facts.json [--force-fields a,b --comment "…"]   # путь, которого нет от текущей папки, берётся от --root
    python -m tools.ip_registry set --mark ID|НОМЕР --field F --value V --comment "…"
    python -m tools.ip_registry revert EVENT_ID --comment "…"
    python -m tools.ip_registry dismiss DOC_ID --comment "…"
    python -m tools.ip_registry query --number 678302
    python -m tools.ip_registry query --product <Продукт> --country UZ
    python -m tools.ip_registry build                    # пересобрать из последней выгрузки

Ошибки печатаются как `Ошибка: …`, код выхода 2. Журнал только дописывается: публикация сверяет, что записанный журнал — начало нового («журнал изменился с момента чтения: повторите команду»), и держит блокировку `<root>/.journal.lock` («журнал занят другой командой»; старше 10 минут снимается). Снимок воспроизводится replay-ем; публикация `data/`, `index/` и `catalog.html` атомарна, откат при сбое доводится до конца. Резервная копия миграции — `backups/registry.json.bak`, вне `data/`. Excel после первичной загрузки базу не меняет, только пишет отчёт сверки. Значение из документа вносится при дословной цитате в извлечённом тексте `documents/*.md` (проверка `tools/evidence_anchor` по этому тексту точно; для скана — дословно из текста OCR, `ocr_fuzzy` не возникает) и только если оно следует из цитаты; изменение знака принимается целиком или не принимается. Если остались решения юриста, `apply-facts` печатает «Решения юриста: python -m tools.ip_registry pending».

Факты `ip_document_facts.v1` (`pending/<doc_id>.facts.json`): `document`, `doc_type`, `doc_type_quote` (заголовок документа, дословно), `doc_date`, `doc_date_quote` (место с датой документа, дословно), `office`, `marks[]` (`registration_no`, `application_no`, `mark_text`, `nice_classes`, `priority_date`, `expiry_date`, `status` — каждое `{value, quote}`; `territories[]` — `{code, status, since, quote}`), `notes`. Проверки (`fact_rules.py`): значение следует из цитаты (даты, номера, классы, текст знака; статус — по маркерам статуса; страна — код или название плюс маркер статуса страны); тип подтверждён, если `doc_type_quote` найдена в тексте и содержит маркер типа; дата — если `doc_date_quote` найдена и содержит дату. Без подтверждённого типа изменение статуса знака или страны в любую сторону и создание знака уходят юристу; без подтверждённой даты поле с датированным источником не перезаписывается. Знак ищется только среди знаков того же вида регистрации (`wipo_*` — Мадрид, `ru_*` — национальные); смена заполненного номера — решение юриста. `office` — `RU`, `WIPO` или ISO-код из `countries.yaml`, иначе null и «ведомство не распознано». `doc_id` из ввода — только `doc-ГГГГММДД-xxxxxxxx`. `set` не правит `verification`. Цитата или `notes` с e-mail или телефоном отбрасывается. Отчёт показывает цитату рядом с каждым «было → стало» (до 200 символов).

Сверки с ведомством: при `migrate` файл `<root>/verifications.yaml` переносится в журнал событиями `verification` и после этого не читается; формат файла для переноса:

    verifications:
      - registration_no: "1000896"          # по номеру регистрации (нормализуется как в поиске)
        source: WIPO Madrid Monitor
        checked: 2026-11-06
        reference: "описание источника (текст, не ссылка)"
        countries:                           # полный список стран по данным ведомства
          AM: {status: protected, since: 2010-06-07}
          AZ: {status: refused, since: 2010-06-09, note: "..."}

`status`: protected | pending | refused | lapsed | withdrawn | not_registered | unknown. Коды стран в кавычках (`"NO"`). Ошибка формата останавливает сборку, прежний каталог не меняется. Знак не найден в реестре — предупреждение. Реестровые территории остаются в `registry_territories`; в каталоге у такого знака бейдж «сверено …».

Колонки ищутся по заголовкам листа «ТЗ»; без обязательной колонки сборка останавливается, прежний каталог не трогается.
Новая страна или синоним → `countries.yaml`.
