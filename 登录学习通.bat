@echo off
rem Log in to Chaoxing once (first run, or when the session expires).
cd /d "%~dp0"
call "find_python.bat"
if errorlevel 1 exit /b 1
"%XXT_PYTHON%" "src\main.py" login %*
echo.
pause
