@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "TEMP_PS=%TEMP%\stop_project_%RANDOM%.ps1"

(
  echo $root = '%ROOT%'
  echo $procs = Get-CimInstance Win32_Process ^| Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -and $_.CommandLine -like '*%ROOT%*' }
  echo if ($procs) {
  echo   Write-Host 'Stopping project processes:'
  echo   $procs ^| Select-Object ProcessId, Name, CommandLine ^| Format-Table -AutoSize ^| Out-String -Width 4096 ^| Write-Host
  echo   $procs ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  echo   Write-Host '✓ Project stopped successfully'
  echo } else {
  echo   Write-Host 'No project processes found'
  echo }
) > "%TEMP_PS%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP_PS%"

del /f /q "%TEMP_PS%" 2>nul
endlocal
