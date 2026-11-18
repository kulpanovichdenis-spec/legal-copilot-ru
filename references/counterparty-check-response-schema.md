# Counterparty Check — Word TaskPane JSON Response Schema

Формальный контракт результата Word-Add-in-Copilot. В этом режиме используется только DaData; текст открытого документа может локально использоваться только для извлечения выбранного ИНН/ОГРН и не участвует в сверке.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "identifier",
    "source",
    "lookupStatus",
    "company",
    "summary",
    "lawyerNote"
  ],
  "properties": {
    "identifier": {
      "type": "string",
      "pattern": "^(?:[0-9]{10}|[0-9]{12}|[0-9]{13}|[0-9]{15})$"
    },
    "source": {
      "type": "string",
      "enum": ["DaData"]
    },
    "lookupStatus": {
      "type": "string",
      "enum": ["найдено", "не найдено", "недоступно"]
    },
    "company": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "fullName",
        "shortName",
        "inn",
        "kpp",
        "ogrn",
        "status",
        "legalAddress",
        "management"
      ],
      "properties": {
        "fullName": { "type": "string", "maxLength": 1000 },
        "shortName": { "type": "string", "maxLength": 500 },
        "inn": { "type": "string", "maxLength": 12 },
        "kpp": { "type": "string", "maxLength": 9 },
        "ogrn": { "type": "string", "maxLength": 15 },
        "status": { "type": "string", "maxLength": 100 },
        "legalAddress": { "type": "string", "maxLength": 2000 },
        "management": { "type": "string", "maxLength": 1000 }
      }
    },
    "summary": { "type": "string", "maxLength": 2000 },
    "lawyerNote": { "type": "string", "maxLength": 2000 }
  }
}
```

## Инварианты

- `source` всегда равен `DaData`; другие реестры в этом режиме не используются.
- В DaData передаётся только `identifier`. Текст документа не передаётся в DaData.
- Если DaData недоступна или запись не найдена, реквизиты не выдумываются: `lookupStatus` отражает причину, поля `company` остаются пустыми.
- Сверка с договором не выполняется; в результате показывается только нормализованная карточка DaData.
