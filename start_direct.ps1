$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$portableExe = Join-Path $repoRoot "main.exe"
$sourceConfigPath = Join-Path $repoRoot "poker\config.ini"
$portableConfigPath = Join-Path $repoRoot "config.ini"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $portableExe) {
    $configPath = $portableConfigPath
}
else {
    $configPath = $sourceConfigPath
}

if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Config file not found: $configPath"
}

$configLines = Get-Content -LiteralPath $configPath
$updatedLines = $configLines | ForEach-Object {
    if ($_ -match '^control\s*=') {
        'control = Direct mouse control'
    }
    else {
        $_
    }
}

Set-Content -LiteralPath $configPath -Value $updatedLines -Encoding ascii

if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = "python"
}

if (Test-Path -LiteralPath $portableExe) {
    & $portableExe
}
else {
    Push-Location $repoRoot
    try {
        & $pythonExe -m poker.main
    }
    finally {
        Pop-Location
    }
}
