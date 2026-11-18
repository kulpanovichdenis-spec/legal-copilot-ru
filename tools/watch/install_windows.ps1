param(
    [switch]$Install,
    [string]$TaskName = "Legal Copilot Unified Watcher"
)

$ErrorActionPreference = "Stop"
$candidateRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$gitCommonDir = (& git -C $candidateRoot rev-parse --path-format=absolute --git-common-dir).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gitCommonDir) {
    throw "Cannot resolve the main legal-copilot checkout through git."
}
$dataRoot = Split-Path $gitCommonDir -Parent
if (-not (Test-Path -LiteralPath (Join-Path $dataRoot "AGENTS.md"))) {
    throw "Resolved data root is not a legal-copilot checkout: $dataRoot"
}
# Код — всегда из основного checkout (того же, что data root), а не из папки,
# откуда запущен установщик. Иначе, будучи установлен из worktree, фоновый
# watcher навсегда остаётся на коде этой ветки и не получает правок main
# (найдено 2026-10-02: задача работала из .claude/worktrees/codex-unified-channel-watcher,
# исправления анонимайзера и категорий образцов до неё не доходили).
$codeRoot = $dataRoot
if ($candidateRoot -ne $dataRoot) {
    Write-Host "Installer runs from a worktree ($candidateRoot); code root is the main checkout: $dataRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $codeRoot "tools\watch\cli.py"))) {
    throw "tools/watch is missing from the code root: $codeRoot"
}

$python = (& python -c "import sys; print(sys.executable)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $python) {
    throw "Cannot resolve the Python executable."
}
$pythonw = Join-Path (Split-Path $python -Parent) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw)) {
    $pythonw = $python
}
$watcherArgs = "-m tools.watch.cli --daemon --root `"$dataRoot`""

Write-Host "Task: $TaskName"
Write-Host "Executable: $pythonw"
Write-Host "Code working directory: $codeRoot"
Write-Host "Data root: $dataRoot"
Write-Host "Arguments: $watcherArgs"

if (-not $Install) {
    Write-Host "Preview only. Re-run with -Install after reviewing these values."
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument $watcherArgs `
    -WorkingDirectory $codeRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "One local legal-copilot intake watcher; no LLM or network." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Milliseconds 750
$installedTask = Get-ScheduledTask -TaskName $TaskName
if ($installedTask.State -ne "Running") {
    throw "Scheduled task was registered but did not start: $($installedTask.State)"
}

Write-Host "Installed and started: $TaskName"
Write-Host "State: $($installedTask.State)"
