# agent-browser — локальная справка

Локальная копия документации `agent-browser` для офлайн-доступа и фиксации поведения конкретной версии. Дублирует `agent-browser --help` и `agent-browser skills get core --full`.

**Зафиксированная версия**: agent-browser 0.27.1
**Дата выгрузки**: 2026-06-02
**Источник**: `agent-browser --help` + `agent-browser skills get core --full` + `agent-browser skills`
**GitHub**: https://github.com/vercel-labs/agent-browser
**Лицензия исходных материалов**: Apache License 2.0; Copyright 2025 Vercel Inc. См. [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) и [`licenses/agent-browser-APACHE-2.0.txt`](../licenses/agent-browser-APACHE-2.0.txt).

## Когда обновлять этот файл

После обновления `agent-browser` (`npm update -g agent-browser` или `cargo install agent-browser`) — перегенерировать:

```powershell
$nodeDir = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.16.0-win-x64"
$env:PATH = "$nodeDir;$env:PATH"
$ver = agent-browser --version
# Затем заменить references/agent-browser-cli.md, обновить версию в шапке
# и сохранить уведомление об изменениях и атрибуцию Apache-2.0
```

При расхождении версии в шапке и фактической — приоритет у фактической; этот файл актуализировать.

## Связь с проектом

- `references/trademark-search-automation.md` — где и зачем agent-browser используется в нашем skill `trademark-search`.
- `skills/trademark-search/SKILL.md` — алгоритм работы, ссылки на конкретные команды отсюда.

---

Полный дамп команд (разделы 1–3) — `references/agent-browser-cli.md`. Открывать его, когда нужна команда. После обновления `agent-browser` перегенерировать этот дамп и версию в шапке.
