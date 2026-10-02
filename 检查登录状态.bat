@echo off
rem Only check whether the saved login session is still valid.
cd /d "%~dp0"
call "find_python.bat"
if errorlevel 1 exit /b 1
"%XXT_PYTHON%" "src\main.py" check %*
echo.
pause
