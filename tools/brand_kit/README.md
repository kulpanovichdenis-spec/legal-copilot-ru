# tools/brand_kit — письма на фирменном бланке

Разбор папки фирменного стиля в манифест и сборка письма поверх бланка
компании. Правила и схема манифеста — `references/brand-letterhead.md`.

```
python -m tools.brand_kit scan [--root DIR] [--force]   # _inbox/ → originals/, черновик brand.yaml
python -m tools.brand_kit list                          # бланки, назначение, слоты
python -m tools.brand_kit demo <blank_id> <out.docx>    # макет письма (только маркеры)
python -m pytest tools/brand_kit -q
```

- `letterhead.py` — `LetterheadDoc`: открывает бланк (.docx/.dotx) как есть, заполняет
  слоты (поля MACROBUTTON, элементы управления содержимым, абзацы-подсказки в теле и
  колонтитулах), вставляет текст письма с оформлением бланка.
- `scan.py` — детерминированный разбор без LLM: вид файла, места для заполнения,
  предложение слотов, превью из одноимённого PDF.

Данные компании (бланки, `brand.yaml`) живут в `profile/knowledge/brand/` и в git не
попадают; тесты используют синтетический бланк.
