# Безопасное обновление SQLite snapshot

`legal-copilot` читает четыре обязательные базы из одного versioned-каталога:

- `legal-ru.sqlite`;
- `legal-uz.sqlite`;
- `legal-doctrine.sqlite`;
- `legal-memory.sqlite`.

Образцы и клаузы в этот каталог не входят: их читают из `profile/knowledge/`. Файл `document-samples.sqlite` в старом snapshot не требуется и при проверке не читается.

SQLite-файлы не изменяются, не мигрируются и не пересобираются внутри Overlay. Команды ниже работают только с локальным указателем `LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR` в gitignored-файле `profile/settings/local.env`.

## Состояние и read-only preflight

Показать текущий локальный и фактически применённый путь без проверки баз:

```powershell
python -m tools.legal_overlay.snapshot_lifecycle status
```

Проверить только manifests, размеры, SHA-256, schema, обязательные таблицы, `quick_check` и foreign keys всех четырёх баз:

```powershell
python -m tools.legal_overlay.snapshot_lifecycle preflight `
  --snapshot 'C:\path\to\snapshot-v4' `
  --validation-only
```

Полный preflight дополнительно запускает одинаковый MCP smoke через фактические entrypoint Codex и Claude Desktop. Smoke требует четыре `connected` SQLite provider, наличие `sqlite_legal_ru_status`, `uzbek_legal_status`, `sqlite_legal_doctrine_status`, `sqlite_legal_memory_status` и отсутствие удалённого провайдера `server-legal-kb`. Серверный URL принудительно заменяется на недоступный loopback sentinel, поэтому скрытая серверная зависимость приводит к ошибке.

```powershell
python -m tools.legal_overlay.snapshot_lifecycle preflight `
  --snapshot 'C:\path\to\snapshot-v4'
```

## Preview и переключение

Preview выполняет полный preflight, показывает текущий и целевой каталоги, но ничего не записывает:

```powershell
python -m tools.legal_overlay.snapshot_lifecycle preview `
  --snapshot 'C:\path\to\snapshot-v4'
```

После проверки preview переключение требует отдельного подтверждающего флага:

```powershell
python -m tools.legal_overlay.snapshot_lifecycle apply `
  --snapshot 'C:\path\to\snapshot-v4' `
  --confirm-write
```

Порядок операции:

1. Строгая read-only проверка четырёх баз.
2. Автономный smoke Codex и Claude с целевым путём через process override.
3. Timestamped backup текущего `local.env`.
4. Атомарная замена только строки `LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR`; остальные локальные значения сохраняются.
5. Повторный smoke без override — оба харнеса обязаны прочитать новый путь из общего `local.env`.
6. Атомарная запись `profile/settings/snapshot-state.json` с текущим и предыдущим каталогами.

После `apply` дополнительно проверить семь контрольных doctrine-запросов, четыре status-tools и отсутствие результатов RU-поиска с `canonical_key LIKE 'legacy-wiki:doctrine_commentary--%'`. Doctrine provider должен оставаться `doctrine_only`; нормы и судебные акты из его результатов проверяются отдельно.

Если второй smoke или запись состояния падают, исходный `local.env` восстанавливается автоматически. Если переменная `LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR` уже задана в окружении процесса, `apply` отказывается писать: иначе новая строка в `local.env` была бы скрыта более приоритетным override.

## Rollback

Вернуться к последнему записанному предыдущему snapshot:

```powershell
python -m tools.legal_overlay.snapshot_lifecycle rollback --confirm-write
```

Rollback проходит те же validation и двойной harness smoke. После успешного возврата значения `current_snapshot` и `previous_snapshot` меняются местами, поэтому состояние остаётся проверяемым. Файлы `local.env`, `snapshot-state.json` и timestamped backups находятся в gitignored `profile/settings/` и не публикуются.

Физическое отключение VPS, удаление server credentials и генерация следующего snapshot не входят в этот lifecycle и требуют отдельных действий.
