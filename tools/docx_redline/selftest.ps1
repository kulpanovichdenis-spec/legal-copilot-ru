# Самопроверка apply_ops.ps1 + verify.ps1 на обезличенном примере (example/): сборка образца, редлайн, сверка
# авторов, счёта w:ins/w:del/комментариев и итогового текста. Нужны Word и python-docx.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File tools/docx_redline/selftest.ps1
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) } catch {}
$here = $PSScriptRoot
$work = Join-Path ([IO.Path]::GetTempPath()) ("redline-selftest-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$problems = New-Object System.Collections.Generic.List[string]
function Assert-That([bool]$cond, [string]$what) { if (-not $cond) { $problems.Add($what) } }
try {
  $sample = Join-Path $work 'sample.docx'
  $result = Join-Path $work 'sample rev1 (редлайн).docx'
  python (Join-Path $here 'example\make_sample.py') $sample
  if ($LASTEXITCODE -ne 0) { throw 'make_sample.py завершился с ошибкой' }
  & (Join-Path $here 'apply_ops.ps1') -Src $sample -Out $result -OpsPath (Join-Path $here 'example\ops.json') -Author 'Selftest Author' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'apply_ops.ps1 завершился с ошибкой' }
  $report = (& (Join-Path $here 'verify.ps1') -Docx $result) -join "`n"

  Assert-That ($report -match 'author: Selftest Author / ins = 7') 'ins автора != 7 (вставка с комментарием по cat делится на два w:ins)'
  Assert-That ($report -match 'author: Selftest Author / del = 6') 'del автора != 6'
  Assert-That ($report -match 'author: Selftest Author / comment = 5') 'комментариев автора != 5'
  Assert-That ($report -match 'author: Контрагент / ins = 1') 'чужое исправление потеряно'
  foreach ($must in '30 (тридцати)', 'товар надлежащего качества в порядке', 'с даты списания денежных средств',
                    '[2.] За просрочку оплаты Покупатель уплачивает неустойку в размере 0,1 %',
                    'исполнения обязательств в натуре.', 'Покупатель: [НАИМЕНОВАНИЕ ПОКУПАТЕЛЯ]', '(редакция Поставщика)') {
    Assert-That ($report.Contains($must)) "нет в итоговом тексте: $must"
  }
  # Поле cat: комментарий стоит только на фразе, а не на всей замене.
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [IO.Compression.ZipFile]::OpenRead($result)
  try { $xml = (New-Object IO.StreamReader($zip.GetEntry('word/document.xml').Open())).ReadToEnd() } finally { $zip.Dispose() }
  $spans = [regex]::Matches($xml, '<w:commentRangeStart w:id="(\d+)"/>(.*?)<w:commentRangeEnd w:id="\1"/>', 'Singleline') |
    ForEach-Object { ([regex]::Matches($_.Groups[2].Value, '<w:t[^>]*>([^<]*)</w:t>') | ForEach-Object { $_.Groups[1].Value }) -join '' }
  Assert-That ($spans -contains 'в натуре') 'комментарий с cat не сужен до фразы «в натуре»'
  foreach ($gone in '90 (девяноста)', 'в одностороннем порядке', 'с даты зачисления') {
    Assert-That (-not $report.Contains($gone)) "осталось в итоговом тексте: $gone"
  }
} finally {
  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
if ($problems.Count) { $problems | ForEach-Object { "FAIL: $_" }; exit 1 }
'selftest: PASS'
