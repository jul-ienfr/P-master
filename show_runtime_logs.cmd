@echo off
setlocal
set "ROOT=%~dp0"
set "ERR_LOG=%ROOT%log\runtime_manual_stderr.log"
set "OUT_LOG=%ROOT%log\runtime_manual_stdout.log"

if not exist "%ERR_LOG%" (
  echo Waiting for %ERR_LOG%...
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$err='%ERR_LOG%'; $out='%OUT_LOG%';" ^
  "Write-Host 'Following runtime logs...';" ^
  "Write-Host ('stderr: ' + $err);" ^
  "Write-Host ('stdout: ' + $out);" ^
  "if (Test-Path $err) { Get-Content -Path $err -Wait -Tail 80 } else { while (-not (Test-Path $err)) { Start-Sleep -Milliseconds 500 }; Get-Content -Path $err -Wait -Tail 80 }"

endlocal
