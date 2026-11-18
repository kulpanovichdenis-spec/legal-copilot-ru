# Docling MCP — подключение «тяжёлого» backend для ингестии документов

Файл — инструкция по подключению `docling-mcp` к Claude Code как опциональный «тяжёлый» backend Направления 9. Поверх — общий протокол `references/document-ingestion.md` (создаётся в 9.4).

## Когда нужен docling MCP

Когда markitdown (`tools/doc_ingest/markitdown_runner.py`) не справляется или даёт плохой результат:

- сканированные PDF (нет текстового слоя, нужен OCR);
- многоколоночные PDF — судебные акты, постановления, предписания;
- PDF с критически важными таблицами (спецификации, реестры товаров, расчёты);
- сложный layout — формулы, footnotes, врезки;
- документы со штампами / печатями (для OCR).

Если документ простой (нативный `.docx`, текстовый PDF) — **остаёмся на markitdown**. Это быстрее, не требует моделей и работает без интернета.

## Когда docling MCP **не нужен**

- если работа идёт в **Cowork** — MCP-сервер docling не доступен в браузерной среде, надо переключиться на Claude Code;
- если документ хорошо парсится markitdown — нет смысла гонять тяжёлый backend;
- если документ содержит коммерческую тайну / реальные ПД, а юрист не уверен в локальном режиме docling — лучше markitdown + ручная проверка.

## Что такое docling MCP

`docling-mcp` ([github.com/docling-project/docling-mcp](https://github.com/docling-project/docling-mcp)) — обёртка вокруг docling (IBM Research) с протоколом MCP. Запускается локально, общается с Claude Code через stdio.

Два режима:

| Режим | Когда | Установка | Размер | Конфиденциальность |
|---|---|---|---|---|
| **local** (рекомендуем) | Чувствительные документы; есть диск/CPU | `pip install docling-mcp[local]` | ~500 МБ + модели (`~1–2 ГБ` после первого запуска) | ✅ полностью офлайн |
| **remote** | Большие объёмы, нет ресурсов локально | `pip install docling-mcp` + `DOCLING_SERVICE_URL` | ~50 МБ | ⚠️ документ уходит на удалённый Docling Serve |

**Для юридической работы → только `local` режим.** Никакого `remote` без отдельного решения юриста.

## Установка (один раз на машину)

### Шаг 1. Установить uv (менеджер Python-пакетов от astral.sh)

```powershell
# Через winget (рекомендуется):
winget install --id=astral-sh.uv -e

# Альтернатива через pip:
pip install uv

# Проверка:
uv --version
uvx --version
```

После установки **перезапустить PowerShell**, чтобы PATH подхватил `uvx`.

### Шаг 2. Запустить docling-mcp один раз (скачает зависимости и модели)

```powershell
# Установка через uvx — он сам подтянет docling-mcp[local]
uvx --from "docling-mcp[local]" docling-mcp-server --help
```

При первом запуске:
- скачается `docling-mcp[local]` (~500 МБ зависимостей);
- при первом реальном конверте — скачаются модели layout-анализа и OCR (~1–2 ГБ);
- всё кэшируется в `~/.cache/uv/` и `~/.cache/docling/` (или эквивалент в `%LOCALAPPDATA%`).

⚠️ **Это надолго на первом запуске** — минимум 5–15 минут на хорошем интернете. Лучше прогнать вечером.

### Шаг 3. Добавить запись в `.mcp.json`

Открыть в корне проекта `.mcp.json` и **добавить блок `docling`** к существующему `mcpServers`. FAS отдельно сюда не добавлять: в `legal-copilot` он доступен через единый локальный Legal Overlay.

```json
{
  "mcpServers": {
    "docling": {
      "command": "uvx",
      "args": [
        "--from=docling-mcp[local]",
        "docling-mcp-server",
        "--transport",
        "stdio"
      ],
      "env": {
        "DOCLING_CONVERSION_MODE": "local"
      }
    }
  }
}
```

### Шаг 4. Перезапустить Claude Code

Закрыть текущую сессию (`/exit` или закрыть терминал) и открыть новую. В новой сессии:

```
/mcp
```

Должна показать `docling — connected`.

### Шаг 5. Smoke-тест

В сессии Claude Code:
> Сконвертируй с помощью docling MCP файл `path/to/scanned-court-order.pdf` в Markdown.

Ожидаемое поведение: docling-mcp возвращает структурированный DoclingDocument JSON или Markdown с распознанным текстом и таблицами.

## Готовые экспортируемые инструменты docling MCP

- **convert**: PDF / DOCX / PPTX → DoclingDocument JSON, Markdown, HTML;
- **generate**: создание документа в нескольких форматах;
- **RAG (Milvus)**: загрузка и поиск (нам не понадобится — RAG делаем сами в Направлении 10).

## Переменные окружения

| Переменная | Что | Значение для нас |
|---|---|---|
| `DOCLING_CONVERSION_MODE` | `local` или `remote` | **`local`** |
| `DOCLING_FALLBACK_TO_LOCAL` | если remote недоступен — на local | не используем |
| `DOCLING_SERVICE_URL` | URL Docling Serve (для remote) | не используем |
| `DOCLING_SERVICE_API_KEY` | ключ удалённого сервиса | не используем |

## Конфиденциальность

- ✅ В `local` режиме всё происходит на машине юриста — данные никуда не уходят;
- ✅ Кэш моделей в `~/.cache/docling/` — не содержит документов клиента;
- ⚠️ Если включишь `remote` режим без разрешения юриста — это нарушение конфиденциальности;
- ⚠️ Если в `.mcp.json` подключишь чужой удалённый docling-server — то же самое.

## Известные проблемы

- **Python 3.14 user-site не виден** (на машине юриста) — uv использует свой собственный изолированный Python для пакетов, обходит проблему;
- **First-run timeout** — Claude Code может разорвать MCP-сессию при первом запуске из-за загрузки моделей. Решение: сначала прогнать `uvx --from docling-mcp[local] docling-mcp-server --help` вручную (Шаг 2 выше);
- **Большой кэш моделей** — следить за диском (`~/.cache/`).

## План Б — если docling MCP не работает

1. Установить `docling` напрямую через pip без MCP: `pip install docling`;
2. Использовать через Python API в обёртке `tools/doc_ingest/docling_runner.py` (если потребуется — добавим в 9.3 как fallback);
3. Альтернативно — `markitdown-ocr` (LLM Vision), но это **cloud** — нельзя для чувствительных документов.

## Связанные файлы

- `tools/doc_ingest/README.md` — лёгкий backend (markitdown);
- `tools/doc_ingest/router.py` — auto-роутер (будет создан в 9.3);
- `references/document-ingestion.md` — общий протокол (будет создан в 9.4);
- `.mcp.json` — место регистрации;

## Источники

- docling-mcp: <https://github.com/docling-project/docling-mcp>
- docling: <https://github.com/docling-project/docling>
- uv: <https://docs.astral.sh/uv/>
