param(
    [string]$BaseUrl = "http://127.0.0.1:8005"
)

$ErrorActionPreference = "Stop"

function Wait-RuntimeApi {
    param(
        [string]$Url,
        [int]$Attempts = 20,
        [int]$DelayMs = 500
    )

    for ($i = 0; $i -lt $Attempts; $i++) {
        try {
            $null = Invoke-RestMethod -Uri "$Url/runtime-snapshot" -Method Get
            return $true
        }
        catch {
            Start-Sleep -Milliseconds $DelayMs
        }
    }

    return $false
}

function Wait-ShadowModeApplied {
    param(
        [string]$Url,
        [int]$Attempts = 20,
        [int]$DelayMs = 500
    )

    for ($i = 0; $i -lt $Attempts; $i++) {
        try {
            $snapshot = Invoke-RestMethod -Uri "$Url/runtime-snapshot" -Method Get
            if ($snapshot.operator.status -eq "shadow") {
                return $snapshot
            }
        }
        catch {
        }
        Start-Sleep -Milliseconds $DelayMs
    }

    return $null
}

if (-not (Wait-RuntimeApi -Url $BaseUrl)) {
    throw "API runtime PokerMaster indisponible sur $BaseUrl"
}

$body = @{
    operator = @{
        shadow_mode_enabled = $true
        assisted_mode_enabled = $false
        observation_mode_enabled = $false
        manual_override_enabled = $false
        paused = $false
    }
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod `
    -Uri "$BaseUrl/bot-cockpit/operator" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body

$appliedSnapshot = Wait-ShadowModeApplied -Url $BaseUrl
if ($null -eq $appliedSnapshot) {
    throw "La commande a ete envoyee, mais le bot n'est pas passe en mode shadow a temps. Verifie runtime-snapshot et operator.status."
}

$appliedSnapshot | ConvertTo-Json -Depth 10
