[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Output "=== $Label ==="
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

# Developer checks (linter, evals, unit tests) exist only in the maintainer's
# repository; a public install does not ship them, so those steps are skipped.
function Invoke-IfPresent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    if (Test-Path $Path) {
        Invoke-Checked $Label $Command
    } else {
        Write-Output "=== $Label === (skipped: $Path not present)"
    }
}

Invoke-Checked "Codex skill discovery" { powershell -ExecutionPolicy Bypass -File tools/setup_codex_skills.ps1 }
Invoke-Checked "Codex configuration" { python tools/codex_config_check.py }
Invoke-Checked "Python syntax" { python -m compileall -q tools }
Invoke-IfPresent "tools/skill_lint/lint_skills.py" "Skill linter selftest" { python tools/skill_lint/lint_skills.py selftest }
Invoke-IfPresent "tools/skill_lint/lint_skills.py" "Skill lint" { python tools/skill_lint/lint_skills.py }
Invoke-IfPresent "tools/skill_eval/run.py" "Skill eval selftest" { python tools/skill_eval/run.py selftest }
Invoke-IfPresent "tests/skill-evals" "Skill evals (auto gate)" { python tools/skill_eval/run.py tests/skill-evals/ --auto-only }
$hasUnitTests = @(Get-ChildItem -Path tools -Recurse -Filter "test_*.py" -ErrorAction SilentlyContinue).Count -gt 0
if ($hasUnitTests) {
    Invoke-Checked "Python tests" { python -m pytest tools -q }
} else {
    Write-Output "=== Python tests === (skipped: no unit tests)"
}
Invoke-IfPresent "tools/norm_verification_policy.py" "Norm verification policy" { python tools/norm_verification_policy.py check }
Invoke-IfPresent "tools/cross-ref-checker.py" "Cross references" { python tools/cross-ref-checker.py }
Invoke-Checked "Whitespace check" { cmd.exe /d /c "git diff --check 2>nul" }

Write-Output "PASS: legal-copilot verification completed"
