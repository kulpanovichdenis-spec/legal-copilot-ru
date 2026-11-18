# Проверка редлайна: (1) счёт исправлений и комментариев по авторам прямо из XML; (2) итоговый текст —
# все исправления принимаются во временной копии, абзацы выгружаются с номером списка (ListString).
# Сам файл не меняется. Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File tools/docx_redline/verify.ps1 `
#   -Docx <редлайн.docx> [-TextOut <итоговый_текст.txt>]
# Правило применения — references/docx-generation.md, «Редлайн»; описание — tools/docx_redline/README.md.
param([string]$Docx, [string]$TextOut)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) } catch {}
$docFull = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Docx)
if (-not (Test-Path -LiteralPath $docFull)) { throw "Нет файла: $docFull" }

Add-Type -AssemblyName System.IO.Compression.FileSystem
function Read-ZipPart($zipArc, [string]$partName) {
  $entry = $zipArc.GetEntry($partName)
  if (-not $entry) { return '' }
  $sr = New-Object IO.StreamReader($entry.Open(), [Text.Encoding]::UTF8)
  try { $sr.ReadToEnd() } finally { $sr.Dispose() }
}

$zipArc = [IO.Compression.ZipFile]::OpenRead($docFull)
try {
  $bodyXml = (Read-ZipPart $zipArc 'word/document.xml')
  $commentsXml = (Read-ZipPart $zipArc 'word/comments.xml')
} finally { $zipArc.Dispose() }

$stats = [ordered]@{}
foreach ($tagName in 'ins', 'del', 'moveFrom', 'moveTo') {
  $stats[$tagName] = ([regex]::Matches($bodyXml, "<w:$tagName[ >]")).Count
}
$stats['comments'] = ([regex]::Matches($commentsXml, '<w:comment[ >]')).Count
Write-Output ("xml: w:ins={0} w:del={1} w:moveFrom={2} w:moveTo={3} comments={4}" -f $stats.ins, $stats.del, $stats.moveFrom, $stats.moveTo, $stats.comments)

$byAuthor = @{}
foreach ($m in [regex]::Matches($bodyXml, '<w:(ins|del|moveFrom|moveTo)\s[^>]*?w:author="([^"]*)"')) {
  $key = $m.Groups[2].Value + ' / ' + $m.Groups[1].Value
  $byAuthor[$key] = 1 + [int]$byAuthor[$key]
}
foreach ($m in [regex]::Matches($commentsXml, '<w:comment\s[^>]*?w:author="([^"]*)"')) {
  $key = $m.Groups[1].Value + ' / comment'
  $byAuthor[$key] = 1 + [int]$byAuthor[$key]
}
foreach ($key in ($byAuthor.Keys | Sort-Object)) { Write-Output ("author: {0} = {1}" -f $key, $byAuthor[$key]) }

# Итоговый текст: принять всё во временной копии.
$tmpCopy = Join-Path ([IO.Path]::GetTempPath()) ("redline-verify-" + [guid]::NewGuid().ToString('N') + '.docx')
Copy-Item -LiteralPath $docFull -Destination $tmpCopy
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$textLines = New-Object System.Collections.Generic.List[string]
try {
  $d = $word.Documents.Open($tmpCopy, $false, $false, $false)
  $d.TrackRevisions = $false
  $d.Revisions.AcceptAll()
  $n = 0
  foreach ($para in $d.Paragraphs) {
    $n++
    $ls = $para.Range.ListFormat.ListString
    $prefix = if ($ls) { "[$ls] " } else { '' }
    $textLines.Add(("{0}`t{1}{2}" -f $n, $prefix, $para.Range.Text.TrimEnd([char]13, [char]7)))
  }
  $d.Close([ref]0)
} finally {
  $word.Quit()
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
  Remove-Item -LiteralPath $tmpCopy -Force -ErrorAction SilentlyContinue
}
Write-Output '--- final text (all revisions accepted) ---'
$textLines
if ($TextOut) {
  $txtFull = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($TextOut)
  [IO.File]::WriteAllLines($txtFull, $textLines, (New-Object Text.UTF8Encoding($true)))
}
