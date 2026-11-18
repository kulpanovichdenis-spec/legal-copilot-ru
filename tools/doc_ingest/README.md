# tools/doc_ingest — слой подготовки документов

Назначение — единый стандартный вход для всех skill-ов: «любой документ → нормализованный Markdown + метаданные».

## Архитектура

| Backend | Когда | Файл | Статус |
|---|---|---|---|
| **markitdown** | «Лёгкие» документы: нативный `.docx`/`.xlsx`/`.pptx`/`.html`/`.csv`, PDF с текстовым слоем | `markitdown_runner.py` | ✅ 9.1 готов |
| **striprtf** | `.rtf` и «`.doc`», который на деле RTF; кодовая страница из `\ansicpg` / `\fcharset204` | `rtf_runner.py` | ✅ |
| **olefile-doc** | Word 97–2003 `.doc` (OLE): текст по piece table, офлайн, без Word COM | `doc_runner.py` | ✅ |
| **docling MCP** | «Сложные» PDF: сканы, многоколоночные судебные акты, контракты с штампами, сложный layout | (через `.mcp.json`) | ✅ 9.2 setup-guide готов; активация юристом по `references/docling-mcp-setup.md` |
| **auto-router** | Авто-выбор по типу, размеру, наличию текстового слоя в PDF | `router.py` | ✅ 9.3 готов |

## Установка

```powershell
# Один раз на машину
pip install 'markitdown[all]'
```

Если pip ставит в user-site, а Python не видит (наблюдалось на Python 3.14 + pythoncore distribution), установить в системный site:

```powershell
pip install 'markitdown[all]' --target 'C:\Users\<USER>\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages' --upgrade
```

## Использование

### CLI — лёгкий backend (markitdown)

```powershell
# В stdout
python tools/doc_ingest/markitdown_runner.py "Договор поставки.docx"

# В файл
python tools/doc_ingest/markitdown_runner.py "Договор поставки.docx" -o output.md

# С метаданными
python tools/doc_ingest/markitdown_runner.py "Договор.docx" -o out.md --json-meta meta.json
```

### CLI — auto-router (рекомендуется)

Выбирает backend по эвристике (тип файла, размер, наличие текстового слоя в PDF):

```powershell
# Сначала посмотреть рекомендацию (без конверсии)
python -m tools.doc_ingest.router "Договор.pdf" --recommend

# Полная конверсия с auto-выбором
python -m tools.doc_ingest.router "Договор.pdf" -o output.md

# С метаданными в stderr
python -m tools.doc_ingest.router "Договор.pdf" -o output.md --json-meta -
```

Router возвращает `exit code 3`, если рекомендован docling — это сигнал caller-скрипту, что нужен Claude Code сеанс с docling MCP.

### Python API

```python
from tools.doc_ingest.markitdown_runner import convert

result = convert("Договор поставки.docx")
print(result["markdown"])           # str
print(result["metadata"])            # dict
```

### Формат выхода

```json
{
  "markdown": "...",
  "metadata": {
    "source": "Договор поставки.docx",
    "source_path": "C:\\...\\Договор поставки.docx",
    "extension": ".docx",
    "size_bytes": 45678,
    "backend": "markitdown",
    "backend_version": "0.0.2",
    "duration_sec": 0.32,
    "char_count": 6789,
    "line_count": 234
  }
}
```

## Поддерживаемые форматы (markitdown backend)

- Office: `.docx`, `.xlsx`, `.xls`, `.pptx`, `.ppt`;
- Web: `.html`, `.htm`;
- Data: `.csv`, `.json`, `.xml`, `.txt`, `.md`;
- Документы: `.pdf` (с текстовым слоем), `.epub`;

`.rtf` markitdown 0.0.2 отдаёт сырой разметкой, `.doc` не читает вовсе (`UnsupportedFormatException`). Router направляет их на `striprtf` и `olefile-doc` по сигнатуре файла.
- Изображения: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tiff` (без OCR — нужен `markitdown-ocr` отдельно);
- Архивы: `.zip` (итерируется по содержимому).

## Ограничения markitdown backend

- **Сканированные PDF** — нет OCR из коробки (нужен LLM-vision через `markitdown-ocr` или docling);
- **Сложные таблицы** — markitdown упрощает структуру; для договоров со спецификациями использовать docling;
- **Многоколоночный текст** — порядок чтения может быть нарушен (типично для PDF судебных актов);
- **Формулы и сноски** — упрощаются или теряются.

При попадании на такой документ — переходить на docling MCP (см. 9.2).

## Сканер недоверенного ввода

`router.convert()` после конвертации вызывает `untrusted_scan.scan()` и дописывает находки в `metadata.warnings` как `[ВОЗМОЖНАЯ ВСТРОЕННАЯ ИНСТРУКЦИЯ: вид — «фрагмент» (место)]`: скрытый текст `.docx` (`w:vanish`, белый шрифт без заливки, кегль < 2 пт), невидимые символы, фразы-команды агенту на русском и английском. Сбой сканера ингестию не роняет. Отдельный запуск: `python -m tools.doc_ingest.untrusted_scan FILE`. Правило — `references/untrusted-input.md`.

## Конфиденциальность

- markitdown работает **локально** — ничего никуда не отправляет;
- ⚠️ опциональный `markitdown-ocr` использует LLM Vision (cloud) — для чувствительных документов **НЕ ИСПОЛЬЗОВАТЬ**;
- Подробнее — `references/document-ingestion.md` (создаётся в этапе 9.4).

## Связанные файлы

- `references/document-ingestion.md` — общий протокол (будет создан в 9.4);
- `tools/doc_ingest/router.py` — auto-роутер (будет создан в 9.3).
