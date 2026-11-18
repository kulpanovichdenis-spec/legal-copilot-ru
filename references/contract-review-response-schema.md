# Contract Review — Word TaskPane JSON Response Schema

Формальный контракт ответа для действия Word «Разобрать документ целиком» — адаптер `skills/word-contract-review/SKILL.md`. Чат-проверка (`skills/contract-review/SKILL.md`) этой схемой не пользуется.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "summary",
    "overallRecommendation",
    "findings",
    "businessQuestions",
    "lawyerNote"
  ],
  "properties": {
    "summary": {
      "type": "string",
      "minLength": 1,
      "maxLength": 3000,
      "description": "Краткий вывод по договору и его ключевым экономическим параметрам"
    },
    "overallRecommendation": {
      "type": "string",
      "enum": [
        "подписать",
        "подписать после правок",
        "не подписывать без существенных правок",
        "требуется решение юриста"
      ]
    },
    "findings": {
      "type": "array",
      "maxItems": 100,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "id",
          "clauseReference",
          "sourceText",
          "clauseType",
          "riskLevel",
          "issue",
          "recommendation",
          "proposedWording",
          "counterpartyComment",
          "lawyerNote"
        ],
        "properties": {
          "id": {
            "type": "string",
            "pattern": "^R[1-9][0-9]*$",
            "maxLength": 10
          },
          "clauseReference": {
            "type": "string",
            "maxLength": 100,
            "description": "Номер пункта или краткое описание места; пусто для отсутствующего условия"
          },
          "sourceText": {
            "type": "string",
            "maxLength": 250,
            "description": "Дословный короткий уникальный непрерывный фрагмент исходного договора для поиска в Word; пусто, если условие отсутствует"
          },
          "clauseType": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100
          },
          "riskLevel": {
            "type": "string",
            "enum": [
              "блокирующий",
              "высокий",
              "средний",
              "низкий",
              "вопрос-бизнесу"
            ]
          },
          "issue": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1000
          },
          "recommendation": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1000
          },
          "proposedWording": {
            "type": "string",
            "maxLength": 5000,
            "description": "Готовая редакция для применения юристом; пусто, если корректная редакция невозможна"
          },
          "counterpartyComment": {
            "type": "string",
            "maxLength": 1500
          },
          "lawyerNote": {
            "type": "string",
            "maxLength": 1500
          }
        }
      }
    },
    "businessQuestions": {
      "type": "array",
      "maxItems": 30,
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 500
      }
    },
    "lawyerNote": {
      "type": "string",
      "maxLength": 3000
    }
  }
}
```

## Инварианты

- `sourceText` — короткий уникальный фрагмент длиной не более 250 символов, скопированный из входного текста дословно, без многоточий и нормализации. Лимит оставляет запас относительно ограничения Word Search API в 255 символов.
- Один риск — один элемент `findings`; нумерация `R1`, `R2`, … уникальна в пределах ответа.
- Для отсутствующего условия `sourceText` и `clauseReference` могут быть пустыми; замечание остаётся в панели, но автоматическая замена недоступна.
- `proposedWording` не содержит маркеров и представляет готовый черновик редакции. При нехватке данных поле остаётся пустым, а неопределённость фиксируется в `lawyerNote`.
- Никакого текста вне JSON и никаких markdown-обёрток.
