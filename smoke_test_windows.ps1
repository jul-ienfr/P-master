param(
    [string]$VmName,
    [int]$LaunchWaitSec = 8,
    [switch]$SkipPortable,
    [switch]$SkipSource,
    [switch]$KeepProcesses
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $repoRoot "smoke-test-logs"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportPath = Join-Path $logDir "smoke-test-$timestamp.txt"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Set-Content -LiteralPath $reportPath -Value "Smoke test report - $timestamp`r`n" -Encoding ascii

$results = New-Object System.Collections.Generic.List[object]
$spawnedProcesses = New-Object System.Collections.Generic.List[System.Diagnostics.Process]
$ownedServerProcess = $null
$configBackups = @{}

function Add-Result {
    param(
        [string]$Step,
        [string]$Status,
        [string]$Detail
    )

    $entry = [pscustomobject]@{
        Step = $Step
        Status = $Status
        Detail = $Detail
    }
    $results.Add($entry) | Out-Null

    $line = "[{0}] {1} - {2}" -f $Status, $Step, $Detail
    Write-Host $line
    Add-Content -LiteralPath $reportPath -Value $line -Encoding ascii
}

function Get-CommandPath {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    return $null
}

function Backup-File {
    param([string]$Path)

    if ((Test-Path -LiteralPath $Path) -and -not $configBackups.ContainsKey($Path)) {
        $configBackups[$Path] = Get-Content -LiteralPath $Path -Raw
    }
}

function Restore-Files {
    foreach ($path in $configBackups.Keys) {
        Set-Content -LiteralPath $path -Value $configBackups[$path] -Encoding ascii
    }
}

function Set-ControlValue {
    param(
        [string]$Path,
        [string]$Value
    )

    Backup-File -Path $Path

    $content = Get-Content -LiteralPath $Path -Raw
    if ($content -match '(?m)^control\s*=') {
        $updated = [regex]::Replace($content, '(?m)^control\s*=.*$', "control = $Value")
    }
    else {
        $updated = $content.TrimEnd("`r", "`n") + "`r`ncontrol = $Value`r`n"
    }

    Set-Content -LiteralPath $Path -Value $updated -Encoding ascii
}

function Wait-ForHealth {
    param([int]$TimeoutSec = 20)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8765/health" -UseBasicParsing -TimeoutSec 2
            if ($response.Content -match "gto_server OK") {
                return $true
            }
        }
        catch {
        }

        Start-Sleep -Milliseconds 500
    }

    return $false
}

function Start-GtoServer {
    if (Wait-ForHealth -TimeoutSec 2) {
        Add-Result -Step "GTO server" -Status "PASS" -Detail "already running on http://127.0.0.1:8765"
        return $null
    }

    $serverExe = Join-Path $repoRoot "gto_server\target\release\gto_server.exe"
    $portableServerExe = Join-Path $repoRoot "portable\PokerMaster-portable\gto_server.exe"
    $stdout = Join-Path $logDir "gto-server-$timestamp.stdout.log"
    $stderr = Join-Path $logDir "gto-server-$timestamp.stderr.log"

    if (Test-Path -LiteralPath $serverExe) {
        $process = Start-Process -FilePath $serverExe -WorkingDirectory (Split-Path -Parent $serverExe) -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if (Wait-ForHealth -TimeoutSec 20) {
            Add-Result -Step "GTO server" -Status "PASS" -Detail "started from gto_server\\target\\release\\gto_server.exe"
            return $process
        }
        Add-Result -Step "GTO server" -Status "FAIL" -Detail "release server executable started but health check failed"
        return $process
    }

    if (Test-Path -LiteralPath $portableServerExe) {
        $process = Start-Process -FilePath $portableServerExe -WorkingDirectory (Split-Path -Parent $portableServerExe) -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if (Wait-ForHealth -TimeoutSec 20) {
            Add-Result -Step "GTO server" -Status "PASS" -Detail "started from portable\\PokerMaster-portable\\gto_server.exe"
            return $process
        }
        Add-Result -Step "GTO server" -Status "FAIL" -Detail "portable server executable started but health check failed"
        return $process
    }

    $cargoPath = Get-CommandPath -Name "cargo"
    if ($cargoPath) {
        $manifestPath = Join-Path $repoRoot "gto_server\Cargo.toml"
        $process = Start-Process -FilePath $cargoPath -ArgumentList @("run", "--release", "--manifest-path", $manifestPath) -WorkingDirectory $repoRoot -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if (Wait-ForHealth -TimeoutSec 60) {
            Add-Result -Step "GTO server" -Status "PASS" -Detail "started through cargo run --release"
            return $process
        }
        Add-Result -Step "GTO server" -Status "FAIL" -Detail "cargo run started but health check failed"
        return $process
    }

    Add-Result -Step "GTO server" -Status "FAIL" -Detail "no release exe, no portable exe, and cargo not found"
    return $null
}

function Start-SmokeProcess {
    param(
        [string]$Step,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    $stdout = Join-Path $logDir ("{0}-{1}.stdout.log" -f ($Step -replace '[^A-Za-z0-9_-]', '_'), $timestamp)
    $stderr = Join-Path $logDir ("{0}-{1}.stderr.log" -f ($Step -replace '[^A-Za-z0-9_-]', '_'), $timestamp)

    if ($ArgumentList -and $ArgumentList.Count -gt 0) {
        $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    }
    else {
        $process = Start-Process -FilePath $FilePath -WorkingDirectory $WorkingDirectory -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    }
    $spawnedProcesses.Add($process) | Out-Null

    Start-Sleep -Seconds $LaunchWaitSec
    $process.Refresh()

    if ($process.HasExited) {
        Add-Result -Step $Step -Status "FAIL" -Detail ("process exited quickly with code {0}. Logs: {1}" -f $process.ExitCode, $stderr)
        return $false
    }

    Add-Result -Step $Step -Status "PASS" -Detail ("process stayed alive for {0}s" -f $LaunchWaitSec)
    return $true
}

function Stop-OwnedProcesses {
    if ($KeepProcesses) {
        return
    }

    foreach ($process in $spawnedProcesses) {
        try {
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction Stop
            }
        }
        catch {
        }
    }

    if ($ownedServerProcess) {
        try {
            if (-not $ownedServerProcess.HasExited) {
                Stop-Process -Id $ownedServerProcess.Id -Force -ErrorAction Stop
            }
        }
        catch {
        }
    }
}

try {
    Add-Content -LiteralPath $reportPath -Value ("Repo root: {0}" -f $repoRoot) -Encoding ascii

    $pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Add-Result -Step "Python env" -Status "FAIL" -Detail "missing .venv\\Scripts\\python.exe"
        throw "Python environment not found."
    }

    $pythonVersion = (& $pythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    if ($pythonVersion.StartsWith("3.12")) {
        Add-Result -Step "Python env" -Status "WARN" -Detail "venv uses Python $pythonVersion; README recommends 3.11"
    }
    else {
        Add-Result -Step "Python env" -Status "PASS" -Detail "venv uses Python $pythonVersion"
    }

    $dependencyCheck = & $pythonExe -c "import PyQt6, pandas, numpy, requests, rapidocr, onnxruntime; print('ok')" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Result -Step "Python deps" -Status "PASS" -Detail "PyQt6/pandas/numpy/requests/rapidocr/onnxruntime import successfully"
    }
    else {
        Add-Result -Step "Python deps" -Status "FAIL" -Detail ("dependency import failed: {0}" -f ($dependencyCheck | Out-String).Trim())
    }

    $ownedServerProcess = Start-GtoServer

    if (-not $SkipPortable) {
        $portableExe = Join-Path $repoRoot "portable\PokerMaster-portable\main.exe"
        $portableConfig = Join-Path $repoRoot "portable\PokerMaster-portable\config.ini"

        if ((Test-Path -LiteralPath $portableExe) -and (Test-Path -LiteralPath $portableConfig)) {
            Set-ControlValue -Path $portableConfig -Value "Direct mouse control"
            [void](Start-SmokeProcess -Step "Portable direct" -FilePath $portableExe -ArgumentList @() -WorkingDirectory (Split-Path -Parent $portableExe))
        }
        else {
            Add-Result -Step "Portable direct" -Status "FAIL" -Detail "portable bundle is missing main.exe or config.ini"
        }
    }
    else {
        Add-Result -Step "Portable direct" -Status "SKIP" -Detail "skipped by parameter"
    }

    $sourceConfig = Join-Path $repoRoot "poker\config.ini"
    if (-not $SkipSource) {
        if (Test-Path -LiteralPath $sourceConfig) {
            Set-ControlValue -Path $sourceConfig -Value "Direct mouse control"
            [void](Start-SmokeProcess -Step "Source direct" -FilePath $pythonExe -ArgumentList @("-m", "poker.main") -WorkingDirectory $repoRoot)
        }
        else {
            Add-Result -Step "Source direct" -Status "FAIL" -Detail "missing poker\\config.ini"
        }
    }
    else {
        Add-Result -Step "Source direct" -Status "SKIP" -Detail "skipped by parameter"
    }

    $vboxManage = Get-CommandPath -Name "VBoxManage"
    if (-not $vboxManage) {
        $defaultVBoxManage = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
        if (Test-Path -LiteralPath $defaultVBoxManage) {
            $vboxManage = $defaultVBoxManage
        }
    }

    if (-not $vboxManage) {
        Add-Result -Step "VirtualBox" -Status "SKIP" -Detail "VBoxManage not found; VBox smoke test skipped"
    }
    else {
        $vmLines = @(& $vboxManage list vms 2>$null)
        $availableVmNames = @()
        foreach ($line in $vmLines) {
            if ($line -match '^"(.+)"\s+\{.+\}$') {
                $availableVmNames += $matches[1]
            }
        }

        if (-not $VmName) {
            if ($availableVmNames.Count -eq 1) {
                $VmName = $availableVmNames[0]
                Add-Result -Step "VirtualBox" -Status "PASS" -Detail "auto-selected VM '$VmName'"
            }
            elseif ($availableVmNames.Count -eq 0) {
                Add-Result -Step "VirtualBox" -Status "SKIP" -Detail "VirtualBox installed but no VM is registered"
            }
            else {
                Add-Result -Step "VirtualBox" -Status "SKIP" -Detail ("multiple VMs found: {0}. Rerun with -VmName <name>" -f ($availableVmNames -join ", "))
            }
        }

        if ($VmName) {
            $virtualboxImport = & $pythonExe -c "import virtualbox; print('ok')" 2>&1
            if ($LASTEXITCODE -ne 0) {
                Add-Result -Step "VirtualBox Python binding" -Status "FAIL" -Detail "python module 'virtualbox' is missing from .venv"
            }
            elseif ($SkipSource) {
                Add-Result -Step "VirtualBox source launch" -Status "SKIP" -Detail "source launch skipped by parameter"
            }
            else {
                Set-ControlValue -Path $sourceConfig -Value $VmName
                [void](Start-SmokeProcess -Step "Source VirtualBox" -FilePath $pythonExe -ArgumentList @("-m", "poker.main") -WorkingDirectory $repoRoot)
            }
        }
    }
}
finally {
    Restore-Files
    Stop-OwnedProcesses

    Add-Content -LiteralPath $reportPath -Value "" -Encoding ascii
    Add-Content -LiteralPath $reportPath -Value "Summary" -Encoding ascii
    Add-Content -LiteralPath $reportPath -Value "-------" -Encoding ascii
    foreach ($entry in $results) {
        Add-Content -LiteralPath $reportPath -Value ("[{0}] {1} - {2}" -f $entry.Status, $entry.Step, $entry.Detail) -Encoding ascii
    }

    Write-Host ""
    Write-Host "Report written to $reportPath"
}

$hasFailure = $false
foreach ($entry in $results) {
    if ($entry.Status -eq "FAIL") {
        $hasFailure = $true
        break
    }
}

if ($hasFailure) {
    exit 1
}

exit 0
