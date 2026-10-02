@echo off
rem ============================================================
rem  XXT Homework Helper - Restart the UI
rem
rem  WHY THIS EXISTS
rem    Double-clicking the desktop icon does NOT restart the backend.
rem    src\app.py checks the port first: if a service is already
rem    listening it only brings the OLD window back (see server.py,
rem    _already_running). So after the server code changes you must
rem    stop the old process first -- that is what this script does.
rem
rem  SAFETY
rem    It only kills the process when http://127.0.0.1:17321/api/state
rem    answers with "phase", i.e. it really is this program.
rem    If some other program holds the port, nothing is killed.
rem
rem  !! KEEP THIS FILE PURE ASCII !!
rem    cmd.exe mis-parses a .bat that mixes "chcp 65001" with
rem    non-ASCII text: bytes get eaten at line starts and lines
rem    break apart. Verified 2026-10-02 with an isolated test.
rem    Put any Chinese text in the README, not in here.
rem ============================================================
setlocal
cd /d "%~dp0"

echo.
echo   XXT Homework Helper - restart UI
echo   --------------------------------------------------------

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "$ours=$false;" ^
  "try{" ^
  "  $r=Invoke-WebRequest 'http://127.0.0.1:17321/api/state' -UseBasicParsing -TimeoutSec 3;" ^
  "  if($r.StatusCode -eq 200 -and $r.Content.Contains('phase')){$ours=$true}" ^
  "}catch{};" ^
  "if(-not $ours){" ^
  "  Write-Host '    No service of this program on port 17321 - nothing to stop.';" ^
  "  exit 0" ^
  "};" ^
  "Write-Host '    Confirmed it is this program. Stopping the old service...';" ^
  "$lines=netstat -ano | Select-String ':17321' | Select-String 'LISTENING';" ^
  "$pids=$lines | ForEach-Object {($_.Line.Trim() -split '\s+')[-1]} | Sort-Object -Unique;" ^
  "foreach($id in $pids){Write-Host ('      stop PID ' + $id); Stop-Process -Id $id -Force};" ^
  "Write-Host '    Old service stopped. Waiting for the port to be released...';" ^
  "Start-Sleep -Seconds 2"

echo   Starting the new window ...
call "find_python.bat"
if errorlevel 1 exit /b 1
start "" "%XXT_PYTHONW%" "src\app.py"
echo   Done - the window should appear in a second.
echo.
echo   If no window appears, run the console launcher in this folder
echo   (the one that keeps a black console open) to see the error.
echo   Log file: data\app.log
timeout /t 4 >nul
exit /b 0
