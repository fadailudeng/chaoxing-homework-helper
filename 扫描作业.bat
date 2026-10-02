@echo off
rem Scan every course's homework and render the dashboard (command line mode,
rem no GUI). Useful for debugging, or when you want the scrolling log.
cd /d "%~dp0"
call "find_python.bat"
if errorlevel 1 exit /b 1
"%XXT_PYTHON%" "src\main.py" run %*
echo.
pause
