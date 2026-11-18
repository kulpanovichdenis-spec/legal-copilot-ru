[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$skillsRoot = (Resolve-Path -LiteralPath (Join-Path $repoRoot "skills")).Path
$agentsRoot = Join-Path $repoRoot ".agents"
$linkPath = Join-Path $agentsRoot "skills"

if (-not (Test-Path -LiteralPath $agentsRoot)) {
    New-Item -ItemType Directory -Path $agentsRoot | Out-Null
}

if (Test-Path -LiteralPath $linkPath) {
    $item = Get-Item -LiteralPath $linkPath -Force
    $target = @($item.Target)[0]
    if ($item.LinkType -notin @("Junction", "SymbolicLink") -or -not $target) {
        throw "$linkPath уже существует и не является ссылкой. Удалите или переместите его вручную после проверки."
    }

    $resolvedTarget = (Resolve-Path -LiteralPath $target).Path
    if ($resolvedTarget -ne $skillsRoot) {
        throw "$linkPath указывает на $resolvedTarget, ожидалось $skillsRoot. Скрипт ничего не заменил."
    }

    Write-Output "OK: Codex skills link already points to $skillsRoot"
    exit 0
}

New-Item -ItemType Junction -Path $linkPath -Target $skillsRoot | Out-Null
Write-Output "OK: created $linkPath -> $skillsRoot"
