param(
    [string]$SessionsRoot = "$env:USERPROFILE\.codex\sessions",
    [string]$HistoryPath = "$env:USERPROFILE\.codex\history.jsonl",
    [string]$SessionIndexPath = "$env:USERPROFILE\.codex\session_index.jsonl",
    [string]$ReportsRoot = "$env:USERPROFILE\.codex\reports",
    [string]$OutputDir = "$env:USERPROFILE\.codex\reports",
    [int]$Limit = 50,
    [datetime]$Since,
    [datetime]$Until
)

$ErrorActionPreference = 'Stop'

function Read-Jsonl {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path -Encoding UTF8 -ErrorAction Stop | ForEach-Object {
        if ([string]::IsNullOrWhiteSpace($_)) { return }
        try { $_ | ConvertFrom-Json } catch { $null }
    } | Where-Object { $null -ne $_ }
}

function Get-TextFromContent {
    param($Content)
    $parts = New-Object System.Collections.Generic.List[string]
    if ($Content -is [string]) { return $Content }
    foreach ($chunk in @($Content)) {
        if ($null -eq $chunk) { continue }
        if ($chunk -is [string]) { $parts.Add($chunk) | Out-Null; continue }
        foreach ($key in @('text','output_text','message')) {
            if ($chunk.PSObject.Properties.Name -contains $key -and -not [string]::IsNullOrWhiteSpace([string]$chunk.$key)) {
                $parts.Add([string]$chunk.$key) | Out-Null
            }
        }
    }
    return ($parts -join "`n")
}

function Normalize-Message {
    param($Obj)
    $payload = $Obj.payload
    if ($null -eq $payload) { return $null }
    $ptype = [string]$payload.type

    if ($ptype -eq 'user_message' -and $payload.message) {
        return [pscustomobject]@{ Role='user'; Text=[string]$payload.message }
    }
    if ($ptype -eq 'agent_message' -and $payload.message) {
        return [pscustomobject]@{ Role='assistant'; Text=[string]$payload.message }
    }
    if ($Obj.type -eq 'response_item' -and $ptype -eq 'message') {
        $role = [string]$payload.role
        if ($role -in @('user','assistant')) {
            $text = Get-TextFromContent $payload.content
            if (-not [string]::IsNullOrWhiteSpace($text)) {
                return [pscustomobject]@{ Role=$role; Text=$text }
            }
        }
    }
    if ($Obj.type -eq 'event_msg' -and $ptype -eq 'user_message') {
        $text = [string]$payload.message
        if (-not [string]::IsNullOrWhiteSpace($text)) {
            return [pscustomobject]@{ Role='user'; Text=$text }
        }
    }
    if ($Obj.type -eq 'event_msg' -and $ptype -eq 'agent_message') {
        $text = [string]$payload.message
        if (-not [string]::IsNullOrWhiteSpace($text)) {
            return [pscustomobject]@{ Role='assistant'; Text=$text }
        }
    }
    return $null
}

function Get-FirstTimestamp {
    param([string]$Path)
    foreach ($obj in Read-Jsonl $Path) {
        if ($obj.timestamp) {
            try { return [datetime]$obj.timestamp } catch { return $null }
        }
    }
    return $null
}

function Escape-MdCell {
    param([string]$Text)
    if ($null -eq $Text) { return '' }
    return (($Text -replace '\|','/' -replace "`r?`n", ' ').Trim())
}
function Test-NoiseMessage {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $true }
    $patterns = @(
        '^# AGENTS\.md instructions',
        '<task> Run a stop-gate review',
        'Only review the work from the previous Claude turn',
        '--- project-doc ---',
        '^<environment_context>',
        '^<turn_aborted>'
    )
    foreach ($pattern in $patterns) {
        if ($Text -match $pattern) { return $true }
    }
    return $false
}

function Top-Lines {
    param($Counter, [int]$N = 8)
    $items = $Counter.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First $N
    if (-not $items) { return @('- none') }
    return $items | ForEach-Object { "- $($_.Key): $($_.Value)" }
}

$sessionsPath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $SessionsRoot).Path)
$sessionFiles = Get-ChildItem -LiteralPath $sessionsPath -Recurse -Filter '*.jsonl' | Sort-Object LastWriteTime

if ($PSBoundParameters.ContainsKey('Since')) {
    $sessionFiles = $sessionFiles | Where-Object { $_.LastWriteTime -ge $Since }
}
if ($PSBoundParameters.ContainsKey('Until')) {
    $end = $Until.Date.AddDays(1)
    $sessionFiles = $sessionFiles | Where-Object { $_.LastWriteTime -lt $end }
}
if ($Limit -gt 0) {
    $sessionFiles = @($sessionFiles | Select-Object -Last $Limit)
}

$toolCounts = @{}
$commandCounts = @{}
$keywordCounts = @{}
$errorCounts = @{}
$workThemes = @{}
$userMessages = 0
$assistantMessages = 0
$totalEvents = 0
$firstSeen = $null
$lastSeen = $null
$sessions = New-Object System.Collections.Generic.List[object]
$sampleUserRequests = New-Object System.Collections.Generic.List[string]
$sampleSeen = @{}

$themeRules = @(
    @{Name='Codex environment / config'; Pattern='codex|mcp|plugin|skill|RTK|AGENTS|config|auth|env-audit|insights'},
    @{Name='Documentation / Markdown'; Pattern='문서|보고서|정리|Markdown|md|블로그|초안|시사점|요약'},
    @{Name='Automation / scheduled work'; Pattern='자동화|automation|scheduler|scheduled|Task Scheduler|정기|백업'},
    @{Name='Connector / external app work'; Pattern='Notion|Google Drive|Gmail|GitHub|Obsidian|connector|OAuth|401|403'},
    @{Name='Korean public-sector docs'; Pattern='공문|계획|교육청|민원|연수|보고|HWPX|한글'},
    @{Name='Coding / implementation'; Pattern='코드|구현|테스트|빌드|lint|pytest|npm|python|TypeScript|수정'}
)

foreach ($file in $sessionFiles) {
    $sessionUser = 0
    $sessionAssistant = 0
    $sessionTools = 0
    $sessionErrors = 0
    $sessionFirst = $null
    $sessionLast = $null
    $sessionText = New-Object System.Collections.Generic.List[string]

    foreach ($obj in Read-Jsonl $file.FullName) {
        $totalEvents++
        $ts = $null
        if ($obj.timestamp) { try { $ts = [datetime]$obj.timestamp } catch {} }
        if ($ts) {
            if ($null -eq $sessionFirst -or $ts -lt $sessionFirst) { $sessionFirst = $ts }
            if ($null -eq $sessionLast -or $ts -gt $sessionLast) { $sessionLast = $ts }
            if ($null -eq $firstSeen -or $ts -lt $firstSeen) { $firstSeen = $ts }
            if ($null -eq $lastSeen -or $ts -gt $lastSeen) { $lastSeen = $ts }
        }

        $msg = Normalize-Message $obj
        if ($msg) {
            $isNoise = Test-NoiseMessage $msg.Text
            if ($msg.Role -eq 'user') {
                $userMessages++; $sessionUser++
                $clean = ($msg.Text -replace "`r?`n", ' ').Trim()
                if (-not $isNoise -and $clean.Length -gt 0 -and $sampleUserRequests.Count -lt 12) {
                    if ($clean.Length -gt 160) { $clean = $clean.Substring(0,160) + '...' }
                    $key = $clean.ToLowerInvariant()
                    if (-not $sampleSeen.ContainsKey($key)) {
                        $sampleSeen[$key] = $true
                        $sampleUserRequests.Add($clean) | Out-Null
                    }
                }
            } elseif ($msg.Role -eq 'assistant') {
                $assistantMessages++; $sessionAssistant++
            }
            if (-not $isNoise) { $sessionText.Add($msg.Text) | Out-Null }
        }

        $payload = $obj.payload
        if ($payload) {
            if ($obj.type -eq 'response_item' -and $payload.type -eq 'function_call') {
                $name = [string]$payload.name
                if ([string]::IsNullOrWhiteSpace($name)) { $name = 'unknown_tool' }
                $toolCounts[$name] = 1 + [int]$toolCounts[$name]
                $sessionTools++
                $args = [string]$payload.arguments
                if ($args -match '"command"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"') {
                    $cmd = $matches[1] -replace '\\','\'
                    $head = ($cmd.Trim() -split '\s+')[0]
                    if (-not [string]::IsNullOrWhiteSpace($head)) { $commandCounts[$head] = 1 + [int]$commandCounts[$head] }
                }
            }
            if ($obj.type -eq 'response_item' -and $payload.type -eq 'function_call_output') {
                $output = [string]$payload.output
                if ($output -match 'Exit code:\s*([1-9]\d*)') { $errorCounts['nonzero exit'] = 1 + [int]$errorCounts['nonzero exit']; $sessionErrors++ }
                foreach ($pat in @('401','403','OAuth','permission','denied','not found','Cannot find path','failed','error','Exception','timed out','sandbox')) {
                    if ($output -match [regex]::Escape($pat)) { $errorCounts[$pat] = 1 + [int]$errorCounts[$pat] }
                }
            }
        }
    }

    $joined = ($sessionText -join "`n")
    foreach ($rule in $themeRules) {
        if ($joined -match $rule.Pattern) { $workThemes[$rule.Name] = 1 + [int]$workThemes[$rule.Name] }
    }
    foreach ($kw in @('Notion','Google Drive','GitHub','Obsidian','MCP','plugin','skill','HWPX','PowerShell','Python','Markdown','Notion','auth','OAuth','한글','공문','보고서','자동화')) {
        $count = ([regex]::Matches($joined, [regex]::Escape($kw), 'IgnoreCase')).Count
        if ($count -gt 0) { $keywordCounts[$kw] = [int]$keywordCounts[$kw] + $count }
    }

    $sessions.Add([pscustomobject]@{
        File = $file.FullName
        Name = $file.BaseName
        First = $sessionFirst
        Last = $sessionLast
        UserMessages = $sessionUser
        AssistantMessages = $sessionAssistant
        ToolCalls = $sessionTools
        ErrorSignals = $sessionErrors
        LastWriteTime = $file.LastWriteTime
    }) | Out-Null
}

$historyCount = 0
if (Test-Path -LiteralPath $HistoryPath) { $historyCount = @(Read-Jsonl $HistoryPath).Count }
$sessionIndexCount = 0
if (Test-Path -LiteralPath $SessionIndexPath) { $sessionIndexCount = @(Read-Jsonl $SessionIndexPath).Count }
$recentEnvReports = @()
if (Test-Path -LiteralPath $ReportsRoot) {
    $recentEnvReports = Get-ChildItem -LiteralPath $ReportsRoot -Filter 'codex-env-audit-*.md' | Sort-Object LastWriteTime -Descending | Select-Object -First 3
}

New-Item -ItemType Directory -Force -Path $OutputDir -ErrorAction Stop | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outFile = Join-Path $OutputDir "codex-insights-$stamp.md"

$period = if ($firstSeen -and $lastSeen) { "$($firstSeen.ToString('yyyy-MM-dd HH:mm')) ~ $($lastSeen.ToString('yyyy-MM-dd HH:mm'))" } else { 'unknown' }
$days = if ($firstSeen -and $lastSeen) { [math]::Max(1, [math]::Ceiling(($lastSeen - $firstSeen).TotalDays)) } else { 1 }
$totalMessages = $userMessages + $assistantMessages
$msgPerDay = [math]::Round($totalMessages / $days, 1)
$avgTools = if ($sessions.Count -gt 0) { [math]::Round((($sessions | Measure-Object ToolCalls -Sum).Sum) / $sessions.Count, 1) } else { 0 }
$errorTotal = if ($errorCounts.Count -gt 0) { ($errorCounts.GetEnumerator() | Measure-Object Value -Sum).Sum } else { 0 }

$recommendations = New-Object System.Collections.Generic.List[object]
if ($errorCounts.ContainsKey('401') -or $errorCounts.ContainsKey('403') -or $errorCounts.ContainsKey('OAuth') -or $errorCounts.ContainsKey('permission')) {
    $recommendations.Add([pscustomobject]@{
        Action='Connector/auth preflight before connector-heavy work'
        When='Notion, Google Drive, GitHub, Obsidian, Gmail, Excel, MCP work; 401/403/OAuth/permission signals'
        Command='powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-env-audit\scripts\Invoke-CodexEnvAudit.ps1"'
        Why='Fail fast on auth/permission gaps before investing in the main task.'
    }) | Out-Null
}
if ($commandCounts.ContainsKey('powershell') -or $keywordCounts.ContainsKey('한글')) {
    $recommendations.Add([pscustomobject]@{
        Action='Use Windows/Korean-safe file handling'
        When='Korean filenames, Korean content, Notion/database Korean property names, Windows path work'
        Command='Use PowerShell with -LiteralPath and quoted absolute paths; for Python reads set $env:PYTHONUTF8=''1'' first.'
        Why='Reduce quoting, encoding, and path interpretation failures.'
    }) | Out-Null
}
if ($workThemes.ContainsKey('Documentation / Markdown')) {
    $recommendations.Add([pscustomobject]@{
        Action='Promote repeated Markdown/Notion/Obsidian workflows into skills or scripts'
        When='The same document, report, closeout, conversion, or logging flow appears more than twice'
        Command='Ask: "Create a small Codex skill/script for this repeated workflow, with dry-run and verification."'
        Why='Turn repeated manual prompting into a reusable workflow with predictable output.'
    }) | Out-Null
}
if ($avgTools -gt 8) {
    $recommendations.Add([pscustomobject]@{
        Action='Replace long probing sequences with one structured audit'
        When='Many Get-Content/Get-ChildItem/Select-String calls are used just to learn current state'
        Command='powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 30 -OutputDir <writable-path>'
        Why='Keeps exploration bounded and makes repeated checks comparable over time.'
    }) | Out-Null
}
if ($recommendations.Count -eq 0) {
    $recommendations.Add([pscustomobject]@{
        Action='Maintain current closeout and verification routine'
        When='No dominant friction pattern appears in the sample'
        Command='Use codex-closeout-routine at session end and keep verification evidence in the final response.'
        Why='Preserves continuity without adding unnecessary process.'
    }) | Out-Null
}

$inefficientSignals = New-Object System.Collections.Generic.List[object]
if ($avgTools -gt 8 -or ([int]$toolCounts['shell_command']) -gt 50) {
    $inefficientSignals.Add([pscustomobject]@{
        Signal='Long probing sequence'
        Evidence="Average tool calls/session: $avgTools; shell_command: $([int]$toolCounts['shell_command'])"
        Impact='More chances for quoting, path, and state-drift errors.'
        BetterAction='Use one audit script or parallel read-only inspections before editing.'
    }) | Out-Null
}
if ($errorCounts.ContainsKey('nonzero exit') -or $errorCounts.ContainsKey('failed') -or $errorCounts.ContainsKey('Exception')) {
    $inefficientSignals.Add([pscustomobject]@{
        Signal='Repeated failing commands'
        Evidence="nonzero exit: $([int]$errorCounts['nonzero exit']); failed: $([int]$errorCounts['failed']); Exception: $([int]$errorCounts['Exception'])"
        Impact='Debug loops can grow before the real cause is isolated.'
        BetterAction='Name 2-3 likely causes, test the cheapest one first, then change approach.'
    }) | Out-Null
}
if ($errorCounts.ContainsKey('401') -or $errorCounts.ContainsKey('403') -or $errorCounts.ContainsKey('OAuth') -or $errorCounts.ContainsKey('permission')) {
    $inefficientSignals.Add([pscustomobject]@{
        Signal='Auth/permission work started too late'
        Evidence="401: $([int]$errorCounts['401']); 403: $([int]$errorCounts['403']); OAuth: $([int]$errorCounts['OAuth']); permission: $([int]$errorCounts['permission'])"
        Impact='Connector-dependent tasks can stall midstream.'
        BetterAction='Run env audit and a minimal connector read/write smoke test before the main task.'
    }) | Out-Null
}
if ($errorCounts.ContainsKey('Cannot find path') -or $keywordCounts.ContainsKey('한글') -or $commandCounts.ContainsKey('powershell')) {
    $inefficientSignals.Add([pscustomobject]@{
        Signal='Windows/Korean path fragility'
        Evidence="Cannot find path: $([int]$errorCounts['Cannot find path']); 한글 keyword: $([int]$keywordCounts['한글']); powershell commands: $([int]$commandCounts['powershell'])"
        Impact='A valid task can fail because the shell misreads the path or encoding.'
        BetterAction='Use quoted absolute paths, -LiteralPath, UTF-8 mode, and post-edit Korean string verification.'
    }) | Out-Null
}
if ($inefficientSignals.Count -eq 0) {
    $inefficientSignals.Add([pscustomobject]@{
        Signal='No dominant inefficient command pattern detected'
        Evidence='Current sample does not show a strong repeated failure mode.'
        Impact='No immediate workflow correction needed.'
        BetterAction='Keep monitoring with codex-insights after larger work blocks.'
    }) | Out-Null
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('# Codex Insights Report') | Out-Null
$lines.Add('') | Out-Null
$lines.Add("- Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')") | Out-Null
$lines.Add("- Scope: $($sessions.Count) session files") | Out-Null
$lines.Add("- Period: $period") | Out-Null
$lines.Add("- History entries: $historyCount") | Out-Null
$lines.Add("- Session index entries: $sessionIndexCount") | Out-Null
$lines.Add('') | Out-Null
$lines.Add('## At A Glance') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('| Metric | Value |') | Out-Null
$lines.Add('|---|---:|') | Out-Null
$lines.Add("| Messages analyzed | $totalMessages |") | Out-Null
$lines.Add("| User messages | $userMessages |") | Out-Null
$lines.Add("| Assistant messages | $assistantMessages |") | Out-Null
$lines.Add("| Events scanned | $totalEvents |") | Out-Null
$lines.Add("| Average messages/day in sample | $msgPerDay |") | Out-Null
$lines.Add("| Average tool calls/session | $avgTools |") | Out-Null
$lines.Add("| Error/friction signals | $errorTotal |") | Out-Null
$lines.Add('') | Out-Null
$lines.Add('## Work Themes') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('| Theme | Count |') | Out-Null
$lines.Add('|---|---:|') | Out-Null
foreach ($item in ($workThemes.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 8)) { $lines.Add("| $((Escape-MdCell ([string]$item.Key))) | $($item.Value) |") | Out-Null }
if ($workThemes.Count -eq 0) { $lines.Add('| none | 0 |') | Out-Null }
$lines.Add('') | Out-Null
$lines.Add('## Tool Usage') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('| Tool | Count |') | Out-Null
$lines.Add('|---|---:|') | Out-Null
foreach ($item in ($toolCounts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 10)) { $lines.Add("| ``$((Escape-MdCell ([string]$item.Key)))`` | $($item.Value) |") | Out-Null }
if ($toolCounts.Count -eq 0) { $lines.Add('| none | 0 |') | Out-Null }
$lines.Add('') | Out-Null
$lines.Add('## Command Heads') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('| Command head | Count |') | Out-Null
$lines.Add('|---|---:|') | Out-Null
foreach ($item in ($commandCounts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 10)) { $lines.Add("| ``$((Escape-MdCell ([string]$item.Key)))`` | $($item.Value) |") | Out-Null }
if ($commandCounts.Count -eq 0) { $lines.Add('| none | 0 |') | Out-Null }
$lines.Add('') | Out-Null
$lines.Add('## Friction Signals') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('| Signal | Count |') | Out-Null
$lines.Add('|---|---:|') | Out-Null
foreach ($item in ($errorCounts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 10)) { $lines.Add("| ``$((Escape-MdCell ([string]$item.Key)))`` | $($item.Value) |") | Out-Null }
if ($errorCounts.Count -eq 0) { $lines.Add('| none | 0 |') | Out-Null }
$lines.Add('') | Out-Null
$lines.Add('## Recurring Keywords') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('| Keyword | Count |') | Out-Null
$lines.Add('|---|---:|') | Out-Null
foreach ($item in ($keywordCounts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 12)) { $lines.Add("| ``$((Escape-MdCell ([string]$item.Key)))`` | $($item.Value) |") | Out-Null }
if ($keywordCounts.Count -eq 0) { $lines.Add('| none | 0 |') | Out-Null }
$lines.Add('') | Out-Null
$lines.Add('## Recommendations With Commands') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('| Recommendation | When to use | Command / Prompt | Expected effect |') | Out-Null
$lines.Add('|---|---|---|---|') | Out-Null
foreach ($rec in $recommendations) { $lines.Add("| $((Escape-MdCell ([string]$rec.Action))) | $((Escape-MdCell ([string]$rec.When))) | ``$((Escape-MdCell ([string]$rec.Command)))`` | $((Escape-MdCell ([string]$rec.Why))) |") | Out-Null }
$lines.Add('') | Out-Null
$lines.Add('## Inefficient Or Disruptive Signals') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('| Signal | Evidence | Why it matters | Better next action |') | Out-Null
$lines.Add('|---|---|---|---|') | Out-Null
foreach ($sig in $inefficientSignals) { $lines.Add("| $((Escape-MdCell ([string]$sig.Signal))) | $((Escape-MdCell ([string]$sig.Evidence))) | $((Escape-MdCell ([string]$sig.Impact))) | $((Escape-MdCell ([string]$sig.BetterAction))) |") | Out-Null }
$lines.Add('') | Out-Null
$lines.Add('## Environment Audit References') | Out-Null
$lines.Add('') | Out-Null
if ($recentEnvReports.Count -eq 0) { $lines.Add('- No recent codex-env-audit reports found.') | Out-Null } else { foreach ($report in $recentEnvReports) { $lines.Add("- $($report.FullName) ($($report.LastWriteTime.ToString('yyyy-MM-dd HH:mm')))") | Out-Null } }
$lines.Add('') | Out-Null
$lines.Add('## Notes') | Out-Null
$lines.Add('') | Out-Null
$lines.Add('- Counts are directional because Codex session schemas may evolve.') | Out-Null
$lines.Add('- Connector OAuth validity is not proven unless a connector tool was explicitly tested in the analyzed sessions.') | Out-Null
$lines.Add('- System/developer prompts are intentionally excluded from qualitative interpretation.') | Out-Null

try {
    [System.IO.File]::WriteAllLines($outFile, $lines, [System.Text.Encoding]::UTF8)
} catch {
    throw "Failed to write Codex insights report to '$outFile'. If running in workspace-write sandbox, approve access to .codex or pass -OutputDir to a writable workspace path. Original error: $($_.Exception.Message)"
}
Write-Output $outFile
