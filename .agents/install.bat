@echo off
setlocal enabledelayedexpansion

:: ── Paths ────────────────────────────────────────────────────────────────────
set "AGENTS_DIR=%~dp0"
:: Remove trailing backslash
if "%AGENTS_DIR:~-1%"=="\" set "AGENTS_DIR=%AGENTS_DIR:~0,-1%"
for %%A in ("%AGENTS_DIR%\..") do set "PROJECT_ROOT=%%~fA"

set "PLAN_SKILL=%AGENTS_DIR%\plan-mode\SKILL.md"
set "REVIEW_SKILL=%AGENTS_DIR%\review-mode\SKILL.md"
set "IMPL_SKILL=%AGENTS_DIR%\implement-mode\SKILL.md"
set "PATCHED=%AGENTS_DIR%\.system_prompt_patched.md"
set "ANTGRAV_WRAPPED=%AGENTS_DIR%\.system_prompt_antigravity.md"

:: ── Patch skill paths ────────────────────────────────────────────────────────
echo Patching skill paths...
set "PLAN_FWD=%PLAN_SKILL:\=/%"
set "REVIEW_FWD=%REVIEW_SKILL:\=/%"
set "IMPL_FWD=%IMPL_SKILL:\=/%"

powershell -NoProfile -Command ^
  "(Get-Content '%AGENTS_DIR%\SYSTEM_PROMPT.md' -Raw)" ^
  " -replace [regex]::Escape('.agents/plan-mode/SKILL.md'), '%PLAN_FWD%'" ^
  " -replace [regex]::Escape('.agents/review-mode/SKILL.md'), '%REVIEW_FWD%'" ^
  " -replace [regex]::Escape('.agents/implement-mode/SKILL.md'), '%IMPL_FWD%'" ^
  " | Set-Content '%PATCHED%' -NoNewline"

echo [OK] Skill paths resolved
echo.

:: ── Helper macro — call :deploy src dst ──────────────────────────────────────
goto :main

:deploy
  set "SRC=%~1"
  set "DST=%~2"
  for %%D in ("%DST%\..") do mkdir "%%~fD" 2>nul
  if exist "%DST%" (
    move /Y "%DST%" "%DST%.bak" >nul
    echo    backed up: %DST%.bak
  )
  copy /Y "%SRC%" "%DST%" >nul
  echo    [OK] %DST%
goto :eof

:main

:: ── Claude Code ───────────────────────────────────────────────────────────────
echo -- Claude Code
call :deploy "%PATCHED%" "%PROJECT_ROOT%\CLAUDE.md"

:: ── Cline ─────────────────────────────────────────────────────────────────────
echo.
echo -- Cline
call :deploy "%PATCHED%" "%PROJECT_ROOT%\.cline\rules\agent-skills.md"

:: ── Kilocode ──────────────────────────────────────────────────────────────────
echo.
echo -- Kilocode
call :deploy "%PATCHED%" "%PROJECT_ROOT%\.kilo\rules\agent-skills.md"

set "KILO_JSON=%PROJECT_ROOT%\kilo.jsonc"
if not exist "%KILO_JSON%" (
  echo { "instructions": [".kilo/rules/agent-skills.md"] } > "%KILO_JSON%"
  echo    [OK] created kilo.jsonc
) else (
  findstr /C:"agent-skills.md" "%KILO_JSON%" >nul 2>&1
  if !errorlevel!==0 (
    echo    [OK] kilo.jsonc already references agent-skills.md
  ) else (
    powershell -NoProfile -Command ^
      "$c = Get-Content '%KILO_JSON%' -Raw;" ^
      "if ($c -match '\"instructions\"') {" ^
      "  $c = $c -replace '\"instructions\"\s*:\s*\[', '\"instructions\": [\".kilo/rules/agent-skills.md\", ';" ^
      "} else {" ^
      "  $c = $c -replace '}\s*$', ', \"instructions\": [\".kilo/rules/agent-skills.md\"]}';" ^
      "}" ^
      "Set-Content '%KILO_JSON%' $c -NoNewline"
    echo    [OK] updated kilo.jsonc
  )
)

:: ── Antigravity ───────────────────────────────────────────────────────────────
echo.
echo -- Antigravity
(
  echo ---
  echo trigger: always_on
  echo ---
  echo.
  type "%PATCHED%"
) > "%ANTGRAV_WRAPPED%"

call :deploy "%ANTGRAV_WRAPPED%" "%PROJECT_ROOT%\.agent\rules\agent-skills.md"

:: ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo All done.
echo Re-run this file after editing SYSTEM_PROMPT.md
echo.
pause
