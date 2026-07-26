@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%install.ps1"

if not exist "%SCRIPT%" (
    echo ERROR: install.ps1 not found at %SCRIPT%
    pause
    exit /b 1
)

set "PS="
if exist "%SYSTEMROOT%\System32\WindowsPowerShell\v1.0\powershell.exe" (
    set "PS=%SYSTEMROOT%\System32\WindowsPowerShell\v1.0\powershell.exe"
    goto run
)
where pwsh.exe >nul 2>&1
if not errorlevel 1 (
    set "PS=pwsh.exe"
    goto run
)
echo ERROR: PowerShell not found.
pause
exit /b 1

:run
"%PS%" -ExecutionPolicy Bypass -File "%SCRIPT%" %*

echo.
pause
