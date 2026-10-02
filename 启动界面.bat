@echo off
rem Open the GUI. The desktop shortcut uses pythonw (no console window);
rem this .bat keeps the console so you can read any error.
rem Chinese notes live in README.md -- keep this file pure ASCII.
cd /d "%~dp0"
call "find_python.bat"
if errorlevel 1 exit /b 1
"%XXT_PYTHON%" "src\app.py" %*
echo.
pause
