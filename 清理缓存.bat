@echo off
rem ============================================================
rem  XXT Homework Helper - Clean cache, then restart the UI
rem
rem  USAGE
rem    clean-cache.bat          -> safe mode (default)
rem    clean-cache.bat full     -> also delete the debugging leftovers
rem  (The UI button calls this with "safe"; the "include debugging
rem   leftovers" checkbox passes "full".)
rem
rem  WHY THIS EXISTS
rem    The UI window uses its own Edge profile: data\ui_profile.
rem    Edge downloads its own components into EVERY profile
rem    (component_crx_cache, ProvenanceData, Edge Entity Extraction ...).
rem    Measured 481 MB and it has nothing to do with this program.
rem
rem  WHAT GETS DELETED -- the list lives in src\cleanup.py (_CLEAN_TARGETS),
rem    NOT here, so there is exactly one place to review:
rem      data\ui_profile              Edge profile of the UI window
rem      debug\preview_profile        profile used by the preview tests
rem      debug\raw_html               (full mode only) raw responses
rem      debug\course_list_raw.json   (full mode only) raw course list
rem
rem  WHAT IS NEVER TOUCHED -- enforced in code by cleanup.py (_PROTECTED),
rem    checked with a fingerprint before AND after deleting:
rem      data\browser_profile     YOUR LOGIN STATE. deleting = log in again
rem      data\login_state.json    login snapshot
rem      data\homework.json       scan results
rem      data\tasks.json          fetched questions (structured)
rem      data\<tasks dir>\        the human-readable .md files
rem      data\courses_cache.json  course list cache
rem      data\selection.json      your course picker selection
rem      web\, src\, assets\      program itself
rem
rem  SAFETY
rem    It only stops the process that answers on 127.0.0.1:17321/api/state
rem    (i.e. really this program), and only closes Edge windows whose
rem    command line points at OUR ui_profile -- your normal Edge windows
rem    are left alone. Deletion itself is done by src\cleanup.py, which
rem    refuses any path outside its whitelist.
rem
rem  !! KEEP THIS FILE PURE ASCII !!
rem    cmd.exe mis-parses a .bat mixing "chcp 65001" with non-ASCII text.
rem    Verified 2026-10-02. Chinese notes belong in the README.
rem ============================================================
setlocal
cd /d "%~dp0"

set "MODE=%~1"
if /i "%MODE%"=="full" (set "OPTFLAG=--optional") else (set "OPTFLAG=")

echo.
echo   Clean browser cache   [mode: %MODE%]
echo   --------------------------------------------------------

echo   [1/5] Stopping the running UI ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "$ours=$false;" ^
  "try{" ^
  "  $r=Invoke-WebRequest 'http://127.0.0.1:17321/api/state' -UseBasicParsing -TimeoutSec 3;" ^
  "  if($r.StatusCode -eq 200 -and $r.Content.Contains('phase')){$ours=$true}" ^
  "}catch{};" ^
  "if(-not $ours){ Write-Host '        no UI is running.'; exit 0 };" ^
  "$lines=netstat -ano | Select-String ':17321' | Select-String 'LISTENING';" ^
  "$pids=$lines | ForEach-Object {($_.Line.Trim() -split '\s+')[-1]} | Sort-Object -Unique;" ^
  "foreach($id in $pids){ Write-Host ('        stop PID ' + $id); Stop-Process -Id $id -Force };" ^
  "Start-Sleep -Seconds 2"

echo   [2/5] Closing Edge windows that belong to this program only ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "$k=0;" ^
  "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" |" ^
  "  Where-Object { $_.CommandLine -like '*ui_profile*' } |" ^
  "  ForEach-Object { Write-Host ('        close msedge PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force; $k++ };" ^
  "if($k -eq 0){ Write-Host '        none found via CIM. If the app window is still open, close it by hand.' };" ^
  "Start-Sleep -Seconds 1"

call "find_python.bat"
if errorlevel 1 exit /b 1

echo   [3/5] Measuring what will be removed ...
"%XXT_PYTHON%" -X utf8 "src\cleanup_cli.py" survey %OPTFLAG%

echo   [4/5] Deleting (whitelist enforced by src\cleanup.py) ...
"%XXT_PYTHON%" -X utf8 "src\cleanup_cli.py" run %OPTFLAG%

echo   [5/5] Starting the UI again ...
start "" "%XXT_PYTHONW%" "src\app.py"
echo.
echo   Done. Login state and scan results were NOT touched.
echo   The first window may take a bit longer while Edge rebuilds its profile,
echo   and it will slowly grow again -- that is Edge, not this program.
echo.
timeout /t 6 >nul
exit /b 0
