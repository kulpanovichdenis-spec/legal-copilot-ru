# Создаёт два ярлыка pre-LLM анонимизации ВНУТРИ workflow\_anonymizer\,
# а не на рабочем столе (решение юриста 2026-09-08: рабочий стол не засоряем,
# ярлыки лежат рядом с папками, которыми управляют).
#
# Запуск из корня проекта:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\pre_anonymize\install-shortcuts.ps1
#
# Скрипт идемпотентен: повторный запуск перезаписывает ярлыки, ничего не дублируя.
# Ярлыки в .gitignore (*.lnk + workflow/**), в репозиторий не уходят — поэтому
# после клона/распаковки этот шаг обязателен (SETUP.md, Шаг 9а).

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$anonDir = Join-Path $repo "workflow\_anonymizer"

# Каркас папок — на случай, если конвейер ещё ни разу не запускался.
foreach ($sub in @("_inbox", "_inbox\analytic", "_inbox\originals", "_inbox\failed", "_ready")) {
    $p = Join-Path $anonDir $sub
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

$ws = New-Object -ComObject WScript.Shell

$lnk = $ws.CreateShortcut((Join-Path $anonDir "Anonymizer Watcher.lnk"))
$lnk.TargetPath = (Join-Path $repo "tools\watch\start-watcher.bat")
$lnk.WorkingDirectory = $repo
$lnk.Description = "Единый watcher каналов legal-copilot (без LLM)"
$lnk.Save()

$lnk = $ws.CreateShortcut((Join-Path $anonDir "Anonymizer Restore.lnk"))
$lnk.TargetPath = (Join-Path $repo "tools\pre_anonymize\restore-drop.bat")
$lnk.WorkingDirectory = $repo
$lnk.Description = "Восстановление реальных данных: перетащите черновик + mapping.json"
$lnk.Save()

Write-Output "OK: ярлыки созданы в $anonDir"
Write-Output "  - Anonymizer Watcher.lnk"
Write-Output "  - Anonymizer Restore.lnk"
