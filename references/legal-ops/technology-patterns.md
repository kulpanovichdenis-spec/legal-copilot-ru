# Паттерны технологии

Выбирать сверху вниз и останавливаться на первом достаточном. При первом сокращении дать расшифровку из конца файла.

```yaml
pattern: human_only
problem_shape: редкое суждение с высоким риском
use_when: нет устойчивого правила или ошибка необратима
avoid_when: одно и то же правило применяется десятки раз без спора
inputs_needed: описание задачи и риск
controls: человек делает и подписывает
examples: позиция по спору, принятие риска
```

```yaml
pattern: template_playbook
problem_shape: разная практика при одинаковой задаче
use_when: не хватает шаблона, чек-листа или правила
avoid_when: шаблон уже есть и соблюдается
inputs_needed: лучший текущий пример и правило решения
controls: человек заполняет шаблон
examples: чек-лист согласования, playbook отклонений
```

```yaml
pattern: deterministic_rule
problem_shape: ветка определяется известным условием
use_when: правило можно записать без суждения
avoid_when: условие каждый раз «зависит от ситуации» и не записано
inputs_needed: правило и входные поля
controls: исключение уходит человеку
examples: порог суммы, обязательный согласующий по типу договора
```

```yaml
pattern: workflow
problem_shape: работа теряется между людьми
use_when: маршрут уже упрощён и его нужно вести
avoid_when: маршрут ещё содержит лишние шаги
inputs_needed: роли, статусы, срок шага
controls: человек принимает решение на развилке
examples: очередь согласования после REMOVE лишних участников
```

```yaml
pattern: data_automation
problem_shape: одни и те же поля переносятся между системами руками
use_when: поля стабильны и источник известен
avoid_when: данные грязные или смысл поля не согласован
inputs_needed: система-источник и поле
controls: сверка выборки человеком
examples: карточка договора из учётной системы
```

```yaml
pattern: api_integration
problem_shape: системы должны обмениваться без ручной выгрузки
use_when: есть API (Application Programming Interface) и владелец интеграции
avoid_when: обмен разовый
inputs_needed: контракт API и права
controls: журнал вызовов и запасной ручной путь
examples: статус договора в DMS (Document Management System)
```

```yaml
pattern: rpa
problem_shape: устойчивые клики в системе без API
use_when: интерфейс стабилен, объём большой, интеграции нет
avoid_when: экран часто меняется или задачу можно убрать
inputs_needed: запись шагов и исключения
controls: человек на сбое
examples: перенос карточки между двумя старыми системами
```

RPA — Robotic Process Automation.

```yaml
pattern: retrieval_rag
problem_shape: ответ должен опираться на свои документы
use_when: корпус знаний пригоден для поиска
avoid_when: знания только в головах и не записаны
inputs_needed: корпус, права доступа, критерий источника
controls: человек проверяет цитату
examples: поиск по своим playbook и шаблонам
```

RAG — Retrieval-Augmented Generation.

```yaml
pattern: llm_extraction
problem_shape: из документа нужно забрать поля по правилу
use_when: поля определены и есть выборка для проверки
avoid_when: от документа ждут правовое суждение
inputs_needed: схема полей и эталонная выборка
controls: сверка ошибок на выборке
examples: стороны, срок, сумма из типового договора
```

LLM — Large Language Model.

```yaml
pattern: ai_copilot
problem_shape: черновик ускоряет эксперта, решение остаётся у человека
use_when: задача повторяется, а суждение всё ещё нужно
avoid_when: достаточно шаблона или правила
inputs_needed: инструкция, источники, образец хорошего результата
controls: обязательная проверка человеком до эффекта
examples: черновик комментариев к договору
```

```yaml
pattern: agentic_workflow
problem_shape: несколько шагов черновика и инструментов подряд
use_when: шаги записаны, эффект наружу закрыт согласованием
avoid_when: неясно, какой шаг можно остановить
inputs_needed: границы инструментов и точка утверждения
controls: человек до внешнего эффекта
examples: собрать пакет вопросов бизнесу и остановиться перед отправкой
```

```yaml
pattern: autonomous_action
problem_shape: действие меняет внешний мир без человека на каждом шаге
use_when: отдельный разбор риска уже подтверждён решением
avoid_when: нет этого решения
inputs_needed: обратимость, журнал, владелец инцидента
controls: отдельный risk analysis до включения
examples: в v0.1 не предлагать как вариант по умолчанию
```

Прочие сокращения: ETL — Extract, Transform, Load; CLM — Contract Lifecycle Management; SLA — Service Level Agreement; ROI — Return on Investment; FTE — Full-Time Equivalent.

ROI и FTE считать скриптом `tools/legal_ops/ops.py`, не в уме.
