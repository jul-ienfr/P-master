param(
    [string]$BaseUrl = "http://127.0.0.1:8005",
    [string]$DatasetDir = "dataset/runtime_failures",
    [string]$OutputPath = "log/shadow_mode_report.md",
    [int]$IncidentLimit = 10
)

$ErrorActionPreference = "Stop"

function Get-Json {
    param(
        [string]$Url,
        [switch]$Optional
    )

    try {
        return Invoke-RestMethod -Uri $Url -Method Get
    }
    catch {
        if ($Optional) {
            return $null
        }
        throw
    }
}

function Get-ValueAtPath {
    param(
        $Object,
        [string[]]$Path
    )

    $current = $Object
    foreach ($segment in $Path) {
        if ($null -eq $current) {
            return $null
        }
        if ($current -is [System.Collections.IDictionary]) {
            if (-not $current.Contains($segment)) {
                return $null
            }
            $current = $current[$segment]
            continue
        }
        $property = $current.PSObject.Properties[$segment]
        if ($null -eq $property) {
            return $null
        }
        $current = $property.Value
    }

    return $current
}

function Select-FirstValue {
    param(
        [object[]]$Candidates
    )

    foreach ($candidate in $Candidates) {
        if (-not (Test-ValuePresent $candidate)) {
            continue
        }
        return $candidate
    }

    return $null
}

function Test-ValuePresent {
    param($Value)

    if ($null -eq $Value) {
        return $false
    }
    if ($Value -is [string]) {
        return -not [string]::IsNullOrWhiteSpace($Value)
    }
    if ($Value -is [System.Collections.IDictionary]) {
        return $Value.Count -gt 0
    }
    if ($Value -is [System.Array]) {
        return $Value.Count -gt 0
    }
    return @($Value.PSObject.Properties).Count -gt 0
}

function Resolve-ReadinessFromJsonLines {
    param(
        [string[]]$Lines,
        [string]$SessionId = ""
    )

    for ($index = $Lines.Count - 1; $index -ge 0; $index--) {
        $line = $Lines[$index]
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        try {
            $entry = $line | ConvertFrom-Json
        }
        catch {
            continue
        }

        if (-not [string]::IsNullOrWhiteSpace($SessionId)) {
            $entrySessionId = [string](Get-ValueAtPath $entry @("session_id"))
            if ($entrySessionId -ne $SessionId) {
                continue
            }
        }

        $candidate = Select-FirstValue @(
            (Get-ValueAtPath $entry @("context", "readiness")),
            (Get-ValueAtPath $entry @("context", "runtime_readiness")),
            (Get-ValueAtPath $entry @("decision", "runtime_readiness")),
            (Get-ValueAtPath $entry @("decision", "metadata", "runtime_readiness"))
        )
        if (Test-ValuePresent $candidate) {
            return $candidate
        }
    }

    return $null
}

function Resolve-Readiness {
    param(
        $Snapshot,
        $StatusPayload,
        $IncidentsPayload,
        [string[]]$IncidentLines,
        [string]$SessionId = ""
    )

    $incidentEntries = @($IncidentsPayload.entries)
    $latestIncident = $incidentEntries | Select-Object -First 1

    return Select-FirstValue @(
        (Get-ValueAtPath $Snapshot @("readiness")),
        (Get-ValueAtPath $Snapshot @("runtime", "canonical_spot", "metadata", "runtime_readiness")),
        (Get-ValueAtPath $Snapshot @("decision", "runtime_readiness")),
        (Get-ValueAtPath $Snapshot @("decision", "metadata", "runtime_readiness")),
        (Get-ValueAtPath $StatusPayload @("runtime", "readiness")),
        (Get-ValueAtPath $StatusPayload @("runtime", "canonical_spot", "metadata", "runtime_readiness")),
        (Get-ValueAtPath $StatusPayload @("runtime", "decision", "runtime_readiness")),
        (Get-ValueAtPath $StatusPayload @("runtime", "decision", "metadata", "runtime_readiness")),
        (Get-ValueAtPath $latestIncident @("context", "readiness")),
        (Resolve-ReadinessFromJsonLines -Lines $IncidentLines -SessionId $SessionId)
    )
}

function Filter-IncidentsBySession {
    param(
        $IncidentsPayload,
        [string]$SessionId = ""
    )

    $entries = @($IncidentsPayload.entries)
    if ([string]::IsNullOrWhiteSpace($SessionId)) {
        return [pscustomobject]@{
            refreshed_at = Get-ValueAtPath $IncidentsPayload @("refreshed_at")
            entries = $entries
        }
    }

    $filteredEntries = @(
        $entries | Where-Object {
            [string](Get-ValueAtPath $_ @("session_id")) -eq $SessionId
        }
    )

    return [pscustomobject]@{
        refreshed_at = Get-ValueAtPath $IncidentsPayload @("refreshed_at")
        entries = $filteredEntries
    }
}

function Filter-IncidentLinesBySession {
    param(
        [string[]]$Lines,
        [string]$SessionId = ""
    )

    if ([string]::IsNullOrWhiteSpace($SessionId)) {
        return $Lines
    }

    $filtered = @()
    foreach ($line in $Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        try {
            $entry = $line | ConvertFrom-Json
        }
        catch {
            continue
        }
        if ([string](Get-ValueAtPath $entry @("session_id")) -eq $SessionId) {
            $filtered += $line
        }
    }
    return $filtered
}

function Resolve-GoLiveGate {
    param(
        $Snapshot,
        $StatusPayload
    )

    return Select-FirstValue @(
        (Get-ValueAtPath $Snapshot @("go_live_gate")),
        (Get-ValueAtPath $Snapshot @("operator", "go_live_gate")),
        (Get-ValueAtPath $StatusPayload @("runtime", "go_live_gate")),
        (Get-ValueAtPath $StatusPayload @("runtime", "operator", "go_live_gate"))
    )
}

function Safe-Count {
    param($Path)
    if (Test-Path $Path) {
        return (Get-ChildItem -Path $Path -File -ErrorAction SilentlyContinue | Measure-Object).Count
    }
    return 0
}

$snapshot = Get-Json "$BaseUrl/runtime-snapshot" -Optional
$statusPayload = Get-Json "$BaseUrl/api/hitl/status" -Optional
$incidents = Get-Json "$BaseUrl/runtime-history?kind=incidents&limit=$IncidentLimit" -Optional

if ($null -eq $snapshot) {
    $snapshot = [pscustomobject]@{}
}
if ($null -eq $statusPayload) {
    $statusPayload = [pscustomobject]@{}
}
if ($null -eq $incidents) {
    $incidents = [pscustomobject]@{ entries = @() }
}

$incidentFile = Join-Path $DatasetDir "incidents.jsonl"
$imagesDir = Join-Path $DatasetDir "images"
$cropsDir = Join-Path $DatasetDir "crops"

$incidentLines = @()
if (Test-Path $incidentFile) {
    $incidentLines = Get-Content $incidentFile | Select-Object -Last $IncidentLimit
}

$currentSessionId = Select-FirstValue @(
    (Get-ValueAtPath $snapshot @("runtime", "session_id")),
    (Get-ValueAtPath $snapshot @("runtime", "metrics", "latest_snapshot", "session_id")),
    (Get-ValueAtPath $snapshot @("runtime", "metrics", "session_id")),
    (Get-ValueAtPath $statusPayload @("runtime", "session_id")),
    (Get-ValueAtPath $statusPayload @("runtime", "metrics", "latest_snapshot", "session_id")),
    (Get-ValueAtPath $statusPayload @("runtime", "metrics", "session_id"))
)

$sessionIncidents = Filter-IncidentsBySession -IncidentsPayload $incidents -SessionId $currentSessionId
$sessionIncidentLines = Filter-IncidentLinesBySession -Lines $incidentLines -SessionId $currentSessionId

$readiness = Resolve-Readiness -Snapshot $snapshot -StatusPayload $statusPayload -IncidentsPayload $sessionIncidents -IncidentLines $sessionIncidentLines -SessionId $currentSessionId
$goLiveGate = Resolve-GoLiveGate -Snapshot $snapshot -StatusPayload $statusPayload
$operatorStatus = Select-FirstValue @(
    (Get-ValueAtPath $snapshot @("operator", "status")),
    (Get-ValueAtPath $statusPayload @("operator", "status")),
    (Get-ValueAtPath $statusPayload @("runtime", "operator", "status")),
    "unavailable"
)
$decisionPayload = Select-FirstValue @(
    (Get-ValueAtPath $snapshot @("decision")),
    (Get-ValueAtPath $statusPayload @("decision")),
    (Get-ValueAtPath $statusPayload @("runtime", "decision")),
    ([pscustomobject]@{})
)
$readinessState = Get-ValueAtPath $readiness @('state')
$readinessScore = Get-ValueAtPath $readiness @('score')
if (Test-ValuePresent $readiness) {
    $readinessJson = $readiness | ConvertTo-Json -Depth 10
}
else {
    $readinessState = "unavailable"
    $readinessScore = "n/a"
    $readinessJson = ([pscustomobject]@{
        status = "unavailable"
        reason = "No session-scoped readiness payload was emitted for the current clean session."
        session_id = $currentSessionId
        operator_status = $operatorStatus
        gate_reason = Select-FirstValue @(
            (Get-ValueAtPath $decisionPayload @("gate_reason")),
            (Get-ValueAtPath $decisionPayload @("gate_result", "reason")),
            (Get-ValueAtPath $decisionPayload @("execution", "reason"))
        )
        decision_source = Get-ValueAtPath $decisionPayload @("source")
        decision_street = Get-ValueAtPath $decisionPayload @("street")
    } | ConvertTo-Json -Depth 10)
}
$readinessStateText = [string](Select-FirstValue @($readinessState, "unavailable"))
$readinessScoreText = [string](Select-FirstValue @($readinessScore, "n/a"))

$report = @(
    "## Session",
    "- Date: $(Get-Date -Format s)",
    "- runtime.session_id: $currentSessionId",
    "- operator.status: $operatorStatus",
    "- go_live_gate.status: $(Get-ValueAtPath $goLiveGate @('status'))",
    "- go_live_gate.verdict: $(Get-ValueAtPath $goLiveGate @('verdict'))",
    "- readiness.state: $readinessStateText",
    "- readiness.score: $readinessScoreText",
    "",
    "## Go-Live Gate",
    '```json',
    ($goLiveGate | ConvertTo-Json -Depth 10),
    '```',
    "",
    "## Readiness",
    '```json',
    $readinessJson,
    '```',
    "",
    "## Decision",
    '```json',
    ($decisionPayload | ConvertTo-Json -Depth 10),
    '```',
    "",
    "## Dataset",
    "- incidents.jsonl present: $(Test-Path $incidentFile)",
    "- image artifacts count: $(Safe-Count $imagesDir)",
    "- crop artifacts count: $(Safe-Count $cropsDir)",
    "",
    "## Recent Incidents From API",
    '```json',
    ($sessionIncidents | ConvertTo-Json -Depth 10),
    '```',
    "",
    "## Recent Incidents JSONL",
    '```text',
    ($sessionIncidentLines -join "`n"),
    '```'
) -join "`r`n"

$parent = Split-Path -Parent $OutputPath
if ($parent -and -not (Test-Path $parent)) {
    New-Item -ItemType Directory -Path $parent | Out-Null
}

Set-Content -Path $OutputPath -Value $report -Encoding UTF8
Write-Output "Shadow mode report written to $OutputPath"
