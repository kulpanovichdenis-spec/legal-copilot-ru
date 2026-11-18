# Словарь данных

Поля context, строки, допущения, открытого вопроса и источника — в `tools/legal_budget/schema.md`.

Деньги в state — строки decimal. Годовую сумму пишет расчёт, не модель в ответе пользователю.

Статусы стадии: `not_started`, `in_progress`, `waiting_for_data`, `draft_complete`, `challenged`, `ready`, `not_applicable`.

Уверенность строки: `high`, `medium`, `low`.

Классификация рычага сокращения: `mandatory`, `committed`, `risk_critical`, `business_enabling`, `maintain_capability`, `deferrable`, `discretionary`.

Причина отклонения факта: `timing`, `price`, `volume`, `mix`, `scope`, `new_event`, `allocation`, `prior_estimate_error`, `unknown`. Неизвестную причину не называть timing.
