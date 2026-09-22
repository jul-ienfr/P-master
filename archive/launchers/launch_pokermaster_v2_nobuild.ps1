$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $repoRoot "launch_pokermaster_v2.ps1"

Write-Host "Lancement Rapide (Sans Build)..." -ForegroundColor Cyan
& $launcher -NoBuild @args
