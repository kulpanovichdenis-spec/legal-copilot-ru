# Точечный редлайн чужой формы по JSON-списку правок: копия исходника -> правки режимом исправлений Word.
# Исходник не меняется, чужие исправления не принимаются, форматирование вставки наследуется от заменяемого текста.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File tools/docx_redline/apply_ops.ps1 `
#   -Src <форма.docx> -Out <форма rev1 (редлайн).docx> -OpsPath <ops.json> [-Author "<имя>"] [-Initials "<инициалы>"] [-LogPath <лог>]
# Нумерация абзацев для поля p: тот же скрипт с -List (только чтение исходника).
# Формат ops.json и правила — tools/docx_redline/README.md; где применять — references/docx-generation.md, «Редлайн».
# Ловушка PowerShell: имена переменных без учёта регистра, поэтому внутри ни одна переменная не повторяет имя параметра.
param(
  [string]$Src,
  [string]$Out,
  [string]$OpsPath,
  [string]$LogPath,
  [string]$Author,
  [string]$Initials,
  [switch]$List,
  [switch]$Overwrite
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) } catch {}

function Get-FullPath([string]$pathArg) {
  $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($pathArg)
}

# Текст абзаца без знака абзаца (\r) и маркера конца ячейки (\a).
function Get-BodyText([string]$raw) {
  $raw.TrimEnd([char]13, [char]7)
}

function Find-Occurrence([string]$hay, [string]$needle, [int]$occNo) {
  $idx = -1
  for ($k = 0; $k -lt $occNo; $k++) {
    $idx = $hay.IndexOf($needle, $idx + 1, [StringComparison]::Ordinal)
    if ($idx -lt 0) { return -1 }
  }
  $idx
}

if (-not $Src) { throw 'Не задан -Src' }
$srcFull = Get-FullPath $Src
if (-not (Test-Path -LiteralPath $srcFull)) { throw "Нет файла: $srcFull" }

$logLines = New-Object System.Collections.Generic.List[string]
function Write-Log([string]$line) { $logLines.Add($line); Write-Output $line }

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$savedName = $null; $savedInitials = $null; $savedLocal = $null
$d = $null
$outFull = $null
$saved = $false
try {
  if ($List) {
    $d = $word.Documents.Open($srcFull, $false, $true, $false)
    $n = 0
    foreach ($para in $d.Paragraphs) {
      $n++
      $ls = $para.Range.ListFormat.ListString
      $prefix = if ($ls) { "[$ls] " } else { '' }
      Write-Output ("{0}`t{1}{2}" -f $n, $prefix, (Get-BodyText $para.Range.Text))
    }
    return
  }

  if (-not $Out) { throw 'Не задан -Out' }
  if (-not $OpsPath) { throw 'Не задан -OpsPath' }
  $outFull = Get-FullPath $Out
  if ($outFull -eq $srcFull) { throw '-Out совпадает с -Src: правки вносятся только в копию' }
  if ((Test-Path -LiteralPath $outFull) -and -not $Overwrite) { throw "Файл уже есть: $outFull (перезапись — ключ -Overwrite)" }
  $logFull = if ($LogPath) {
    Get-FullPath $LogPath
  } else {
    $workflow = (Get-FullPath (Join-Path $PSScriptRoot '../../workflow')).TrimEnd('\') + '\'
    if ($outFull.StartsWith($workflow, [StringComparison]::OrdinalIgnoreCase)) {
      $parts = $outFull.Substring($workflow.Length).Split('\')
    } else {
      $parts = @()
    }
    if ($parts.Count -ge 2 -and $parts[0] -notmatch '^[_.]') {
      $caseRoot = Join-Path $workflow $parts[0]
      $run = Join-Path $caseRoot ("_llm/runs/" + [Guid]::NewGuid().ToString("N") + "/logs")
      [void][IO.Directory]::CreateDirectory($run)
      Join-Path $run ([IO.Path]::GetFileNameWithoutExtension($outFull) + '.ops.log')
    } else {
      [IO.Path]::ChangeExtension($outFull, '.ops.log')
    }
  }

  $parsed = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText((Get-FullPath $OpsPath), [Text.Encoding]::UTF8))
  # @() снаружи: if-выражение разворачивает массив из одной операции в скаляр.
  $opList = @(if ($parsed -is [array]) { $parsed } else { $parsed.ops })
  if ($opList.Count -eq 0) { throw 'В ops.json нет операций' }

  Copy-Item -LiteralPath $srcFull -Destination $outFull -Force
  $d = $word.Documents.Open($outFull, $false, $false, $false)

  # Снимок абзацев до правок: все позиции считаются по исходнику.
  $paras = New-Object System.Collections.Generic.List[object]
  foreach ($para in $d.Paragraphs) {
    $r = $para.Range
    $paras.Add([pscustomobject]@{ Start = $r.Start; End = $r.End; Raw = $r.Text; Live = $r })
  }
  Write-Log ("source: {0}; paragraphs: {1}; ops: {2}" -f $srcFull, $paras.Count, $opList.Count)

  # Разбор и проверка всех операций до первой правки.
  $plan = New-Object System.Collections.Generic.List[object]
  $opNo = 0
  foreach ($op in $opList) {
    $opNo++
    $kind = [string]$op.op
    $tag = "op#$opNo ($kind, p=$($op.p))"
    $pn = [int]$op.p
    if ($pn -lt 1 -or $pn -gt $paras.Count) { throw "$tag`: нет абзаца с таким номером" }
    $pi = $paras[$pn - 1]
    $body = Get-BodyText $pi.Raw
    if ($op.anchor -and -not $body.TrimStart().StartsWith([string]$op.anchor, [StringComparison]::Ordinal)) {
      throw "$tag`: абзац начинается не с anchor. Начало абзаца: «$($body.TrimStart().Substring(0, [Math]::Min(60, $body.TrimStart().Length)))»"
    }
    $occNo = if ($op.occ) { [int]$op.occ } else { 1 }
    $newText = if ($null -ne $op.new) { [string]$op.new } else { '' }
    $s = 0; $e = 0; $expect = $null; $prio = 0
    switch ($kind) {
      { $_ -in 'replace', 'delete', 'insert_after', 'replace_tail' } {
        if (-not $op.find) { throw "$tag`: не задан find" }
        $idx = Find-Occurrence $body ([string]$op.find) $occNo
        if ($idx -lt 0) { throw "$tag`: «$($op.find)» (вхождение $occNo) в абзаце не найдено" }
        $s = $pi.Start + $idx
        if ($kind -eq 'replace_tail') {
          $e = $pi.Start + $body.Length; $expect = $body.Substring($idx)
        } else {
          $e = $s + ([string]$op.find).Length; $expect = [string]$op.find
        }
      }
      { $_ -in 'replace_para', 'comment_para' } {
        $s = $pi.Start; $e = $pi.Start + $body.Length; $expect = $body
        if ($kind -eq 'comment_para') {
          if (-not $op.c) { throw "$tag`: не задан c (текст комментария)" }
          $prio = 1
        }
      }
      'delete_para' {
        if ($pi.Raw.EndsWith([string][char]7)) { throw "$tag`: абзац в конце ячейки таблицы удалить нельзя — используйте replace_para с new = """"" }
        $s = $pi.Start; $e = $pi.End; $expect = $pi.Raw
      }
      default { throw "$tag`: неизвестный тип операции «$kind»" }
    }
    $actual = $d.Range($s, $e).Text
    if ($actual -ne $expect) { throw "$tag`: текст диапазона не совпал. Ожидалось «$expect», в документе «$actual»" }
    if ($kind -eq 'delete' -and $newText) { throw "$tag`: у delete не бывает new" }
    if ($kind -eq 'insert_after' -and -not $newText) { throw "$tag`: у insert_after пустой new" }
    $cAt = [string]$op.cat
    if ($cAt) {
      if (-not $op.c) { throw "$tag`: cat задан без c" }
      # Фраза для комментария ищется в новом тексте, а у удаления и comment_para — в исходном.
      $catHay = if ($newText -and $kind -ne 'comment_para') { $newText } else { $expect }
      if ($catHay.IndexOf($cAt, [StringComparison]::Ordinal) -lt 0) { throw "$tag`: фраза cat «$cAt» не найдена в тексте правки" }
      if ($cAt.Length -gt 255) { throw "$tag`: cat длиннее 255 знаков" }
    }
    $plan.Add([pscustomobject]@{
      No = $opNo; Tag = $tag; Kind = $kind; S = $s; E = $e; New = $newText; CAt = $cAt
      Comment = [string]$op.c; NoBold = [bool]$op.nobold; Prio = $prio; Live = $pi.Live
      Key = if ($kind -eq 'insert_after') { $e } else { $s }
    })
  }

  # Правки не должны пересекаться (комментарий к абзацу может лежать поверх правок внутри него).
  $edits = @($plan | Where-Object { $_.Kind -ne 'comment_para' } | Sort-Object Key, E)
  for ($k = 1; $k -lt $edits.Count; $k++) {
    if ($edits[$k].Key -lt $edits[$k - 1].E) { throw "$($edits[$k].Tag) пересекается с $($edits[$k - 1].Tag)" }
  }

  if ($Author) {
    $savedName = $word.UserName; $savedInitials = $word.UserInitials; $savedLocal = $word.Options.UseLocalUserInfo
    $word.Options.UseLocalUserInfo = $true
    $word.UserName = $Author
    if ($Initials) { $word.UserInitials = $Initials }
  }
  Write-Log ("author: {0}" -f $word.UserName)

  $d.TrackRevisions = $true
  $d.TrackFormatting = $false

  # С конца документа к началу: правка не сдвигает позиции ещё не применённых правок.
  $ordered = $plan | Sort-Object @{ Expression = 'Key'; Descending = $true }, @{ Expression = 'Prio'; Descending = $false }
  foreach ($it in $ordered) {
    $target = $null
    switch ($it.Kind) {
      'comment_para' {
        # Живой диапазон абзаца уже учёл правки внутри него; знак абзаца и конец ячейки в комментарий не берём.
        $target = $it.Live.Duplicate
        while ($target.End -gt $target.Start -and $target.Text -match '[\r\a]$') { $target.MoveEnd(1, -1) | Out-Null }
      }
      'delete'      { $d.Range($it.S, $it.E).Delete() | Out-Null; $target = $d.Range($it.S, $it.E) }
      'delete_para' { $d.Range($it.S, $it.E).Delete() | Out-Null; $target = $d.Range($it.S, $it.E) }
      'insert_after' {
        $d.Range($it.E, $it.E).InsertAfter($it.New)
        $target = $d.Range($it.E, $it.E + $it.New.Length)
      }
      default {
        # replace / replace_tail / replace_para: новый текст в конец старого (наследует формат), затем удаление старого.
        if ($it.New) {
          $d.Range($it.E, $it.E).InsertAfter($it.New)
          $target = $d.Range($it.E, $it.E + $it.New.Length)
        }
        $d.Range($it.S, $it.E).Delete() | Out-Null
        if (-not $it.New) { $target = $d.Range($it.S, $it.E) }
      }
    }
    if ($it.NoBold -and $it.New -and $it.Kind -ne 'comment_para') { $target.Font.Bold = 0 }
    if ($it.Comment -and $it.CAt -and $target.Text -ne $it.CAt) {
      # Комментарий точечно: только на фразу cat внутри правки, не на весь блок.
      $sub = $target.Duplicate
      $found = $sub.Find.Execute($it.CAt, $true, $false, $false, $false, $false, $true, 0)
      if (-not $found -or $sub.Start -lt $target.Start -or $sub.End -gt $target.End) { throw "$($it.Tag): фраза cat «$($it.CAt)» не найдена в документе" }
      $target = $sub
    }
    if ($it.Comment) { $d.Comments.Add($target, $it.Comment) | Out-Null }
    Write-Log ("{0}: ok [{1}..{2}]{3}" -f $it.Tag, $it.S, $it.E, $(if ($it.Comment) { ' +comment' } else { '' }))
  }

  $d.Save()
  $saved = $true
  Write-Log ("saved: {0}; revisions: {1}; comments: {2}" -f $outFull, $d.Revisions.Count, $d.Comments.Count)
}
catch {
  Write-Log ("ERROR: " + $_.Exception.Message)
  $failed = $_
}
finally {
  if ($d) { try { $d.Close([ref]0) } catch {} }
  if ($Author -and $null -ne $savedName) {
    $word.UserName = $savedName
    $word.UserInitials = $savedInitials
    $word.Options.UseLocalUserInfo = $savedLocal
  }
  $word.Quit()
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
  if (-not $List) {
    if (-not $saved -and $outFull -and (Test-Path -LiteralPath $outFull)) { Remove-Item -LiteralPath $outFull -Force }
    if ($logFull) { [IO.File]::WriteAllLines($logFull, $logLines, (New-Object Text.UTF8Encoding($true))) }
  }
}
if ($failed) { exit 1 }
