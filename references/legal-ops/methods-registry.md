# Реестр методов

Не учебник. Выбрать самый простой метод, которого хватает. При первом сокращении в тексте для пользователя дать полное имя и эту расшифровку.

```yaml
method: SIPOC
full_name: Suppliers, Inputs, Process, Outputs, Customers
plain_language: кто поставляет вход, что приходит, что делается, что выходит и кто это забирает
use_when: нужно очертить границы процесса
do_not_use_when: уже нужны роли, ожидание или развилки
inputs: название процесса и один проход от старта до результата
output: граница и список входов-выходов
next: swimlane, если спор о ролях; иначе карточка процесса
source: практика описания процессов; не норма права
```

```yaml
method: swimlane
full_name: swimlane process map
plain_language: дорожки ролей, передачи и согласования
use_when: путаются handoffs и approvals
do_not_use_when: граница процесса ещё не ясна
inputs: роли и шаги As Is
output: карта передач
next: VSM, если боль в ожидании; иначе REDESIGN
source: практика описания процессов; не норма права
```

```yaml
method: VSM
full_name: Value Stream Mapping
plain_language: карта потока создания ценности — где работа ждёт, а где делается
use_when: боль в цикле, очередях, ожидании и переделках
do_not_use_when: нет даже границ процесса
inputs: шаги, время работы и время ожидания или явный UNKNOWN
output: картина потерь времени
next: REDESIGN
source: практика бережливого описания потока; не норма права
```

```yaml
method: BPMN
full_name: Business Process Model and Notation
plain_language: нотация для ветвлений, событий и интеграций
use_when: без развилок нельзя спроектировать автоматизацию
do_not_use_when: хватает SIPOC или swimlane
inputs: подтверждённые ветки и события
output: детальная схема для DESIGN
next: декомпозиция на задачи
source: стандарт нотации OMG; в v0.1 генератор схем не делается
```

```yaml
method: RACI
full_name: Responsible, Accountable, Consulted, Informed
plain_language: кто делает, кто отвечает, кого спрашивают, кого ставят в известность
use_when: неясен владелец шага
do_not_use_when: роли и так названы и не спорят
inputs: шаги и люди
output: матрица ответственности
next: убрать лишние согласования в REDESIGN
source: практика распределения ответственности; не норма права
```

```yaml
method: ADKAR
full_name: Awareness, Desire, Knowledge, Ability, Reinforcement
plain_language: знает ли человек о изменении, хочет ли, умеет ли, закрепилось ли
use_when: решение есть, а им не пользуются
do_not_use_when: процесс ещё не описан
inputs: кто пользователь и что должно измениться в его работе
output: пробел внедрения
next: implementation plan
source: практика управления изменением; не норма права
```
