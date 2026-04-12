$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$specPath = Join-Path $repoRoot "poker\main.spec"
$portableRoot = Join-Path $repoRoot "portable"
$buildDir = Join-Path $portableRoot "build"
$distDir = Join-Path $portableRoot "dist"
$bundleDir = Join-Path $portableRoot "PokerMaster-portable"
$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--distpath", $distDir,
    "--workpath", $buildDir,
    $specPath
)

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Missing virtual environment Python at $pythonExe"
}

if (-not (Test-Path -LiteralPath $specPath)) {
    throw "Missing PyInstaller spec at $specPath"
}

& $pythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $pythonExe -m pip install "pyinstaller==5.13.0"
}

& $pythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pkg_resources') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $pythonExe -m pip install "setuptools<81"
}

if (Test-Path -LiteralPath $buildDir) {
    Remove-Item -LiteralPath $buildDir -Recurse -Force
}

if (Test-Path -LiteralPath $distDir) {
    Remove-Item -LiteralPath $distDir -Recurse -Force
}

if (Test-Path -LiteralPath $bundleDir) {
    Remove-Item -LiteralPath $bundleDir -Recurse -Force
}

& $pythonExe @pyInstallerArgs

$generatedDir = Join-Path $distDir "main"
if (-not (Test-Path -LiteralPath $generatedDir)) {
    throw "Expected PyInstaller output folder not found: $generatedDir"
}

New-Item -ItemType Directory -Path $bundleDir | Out-Null
Copy-Item -Path (Join-Path $generatedDir "*") -Destination $bundleDir -Recurse -Force

Copy-Item -LiteralPath (Join-Path $repoRoot "start_direct.ps1") -Destination $bundleDir -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "start_vbox.ps1") -Destination $bundleDir -Force

if (Test-Path -LiteralPath (Join-Path $repoRoot "PORTABLE.md")) {
    Copy-Item -LiteralPath (Join-Path $repoRoot "PORTABLE.md") -Destination (Join-Path $bundleDir "README-PORTABLE.md") -Force
}

Write-Host ""
Write-Host "Portable bundle ready:" $bundleDir
Write-Host "Run direct mode with:" (Join-Path $bundleDir "start_direct.ps1")
Write-Host "Run VirtualBox mode with:" (Join-Path $bundleDir "start_vbox.ps1")
