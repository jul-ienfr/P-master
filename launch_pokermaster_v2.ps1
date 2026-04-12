param(
    [switch]$Detached,
    [switch]$BuildDebug,
    [switch]$BuildRelease,
    [switch]$NoBuild,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$wslExe = Join-Path $env:SystemRoot "System32\wsl.exe"
$logPath = Join-Path $repoRoot "launch_pokermaster_v2.log"

if (-not (Test-Path -LiteralPath $wslExe)) {
    throw "wsl.exe not found at $wslExe"
}

function Convert-WindowsPathToWsl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WindowsPath
    )

    $fullPath = [System.IO.Path]::GetFullPath($WindowsPath)
    if ($fullPath -notmatch '^(?<drive>[A-Za-z]):\\(?<rest>.*)$') {
        throw "Unable to convert Windows path to WSL path: $fullPath"
    }

    $drive = $matches['drive'].ToLowerInvariant()
    $rest = $matches['rest'] -replace '\\', '/'

    if ([string]::IsNullOrWhiteSpace($rest)) {
        return "/mnt/$drive"
    }

    return "/mnt/$drive/$rest"
}

$wslRoot = Convert-WindowsPathToWsl -WindowsPath $repoRoot

if (-not $wslRoot) {
    throw "Unable to resolve the project path inside WSL."
}

$wslLogPath = Convert-WindowsPathToWsl -WindowsPath $logPath

if (-not $wslLogPath) {
    throw "Unable to resolve the log path inside WSL."
}

$wslCommand = "cd `"$wslRoot`" && /bin/bash ./launch_pokermaster_v2.sh"

if ($BuildRelease) {
    $wslCommand += " --build-release"
}
elseif ($BuildDebug) {
    $wslCommand += " --build-debug"
}

if ($NoBuild) {
    $wslCommand += " --no-build"
}

foreach ($arg in $AppArgs) {
    $escaped = $arg.Replace("'", "'`"'`"'")
    $wslCommand += " '$escaped'"
}

$wslLoggedCommand = "$wslCommand >> '$wslLogPath' 2>&1"

function Write-NewLogContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [ref]$Position
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $fileStream = $null
    $reader = $null

    try {
        $fileStream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        [void]$fileStream.Seek($Position.Value, [System.IO.SeekOrigin]::Begin)
        $reader = New-Object System.IO.StreamReader($fileStream, [System.Text.Encoding]::UTF8, $true, 1024, $true)
        $content = $reader.ReadToEnd()
        $Position.Value = $fileStream.Position

        if (-not [string]::IsNullOrEmpty($content)) {
            $normalized = $content -replace "`0", ""
            $lines = $normalized -split "\r?\n"
            foreach ($line in $lines) {
                if (-not [string]::IsNullOrWhiteSpace($line)) {
                    Write-Host $line
                }
            }
        }
    }
    finally {
        if ($reader) {
            $reader.Dispose()
        }
        if ($fileStream) {
            $fileStream.Dispose()
        }
    }
}

if ($Detached) {
    "[$([DateTime]::Now.ToString('u'))] Launching PokerMaster V2 in background..." | Set-Content -LiteralPath $logPath -Encoding utf8
    Start-Process -FilePath $wslExe -WorkingDirectory $repoRoot -ArgumentList @("/bin/bash", "-lc", $wslLoggedCommand) | Out-Null
    exit 0
}

try {
    "[$([DateTime]::Now.ToString('u'))] Launching PokerMaster V2..." | Set-Content -LiteralPath $logPath -Encoding utf8
    Write-Host "Launching PokerMaster V2..."
    Write-Host "Log: $logPath"
    Write-Host "Build output will stream below. The first rebuild can take a few minutes."
    $process = Start-Process -FilePath $wslExe -WorkingDirectory $repoRoot -ArgumentList @("/bin/bash", "-lc", $wslLoggedCommand) -PassThru
    $logPosition = 0L

    while (-not $process.HasExited) {
        Write-NewLogContent -Path $logPath -Position ([ref]$logPosition)
        Start-Sleep -Milliseconds 250
        $process.Refresh()
    }

    Write-NewLogContent -Path $logPath -Position ([ref]$logPosition)
    exit $process.ExitCode
}
catch {
    $_ | Out-File -LiteralPath $logPath -Append -Encoding utf8
    Write-Host ""
    Write-Host "Launch failed. Log: $logPath" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
