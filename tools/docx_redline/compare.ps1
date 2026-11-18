# Редлайн сравнением: исходник (например, rev юриста) vs чистая новая версия -> новый .docx с исправлениями.
# Word COM, форматирование не сравнивается (нет шума), переносы блоков видны как перемещения.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File tools/docx_redline/compare.ps1 `
#   -Orig <исходник.docx> -Rev <новая_чистая.docx> -Out <редлайн.docx> -Author "<автор правок>"
# Правило применения — references/docx-generation.md, «Редлайн».
param([string]$Orig, [string]$Rev, [string]$Out, [string]$Author)
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $o = $word.Documents.Open($Orig, $false, $true)
  $r = $word.Documents.Open($Rev, $false, $true)
  # CompareDocuments(Original, Revised, Destination=new, Granularity=word, CompareFormatting=false,
  #   CaseChanges, Whitespace=false, Tables, Headers, Footnotes, Textboxes, Fields, Comments, Moves, RevisedAuthor, IgnoreWarnings)
  $res = $word.CompareDocuments($o, $r, 2, 1, $false, $true, $false, $true, $true, $true, $true, $true, $true, $true, $Author, $true)
  $res.SaveAs2($Out, 16)
  "revisions: " + $res.Revisions.Count
  "comments: " + $res.Comments.Count
  foreach ($c in $res.Comments) { " - " + $c.Author + ": " + $c.Range.Text }
  $res.Close([ref]0); $o.Close([ref]0); $r.Close([ref]0)
} finally { $word.Quit() }
