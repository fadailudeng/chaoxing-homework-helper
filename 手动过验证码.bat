@echo off
rem Solve the image captcha by hand when Chaoxing blocks you.
rem The GUI has a button for this now; this is the command line equivalent.
cd /d "%~dp0"
call "find_python.bat"
if errorlevel 1 exit /b 1
"%XXT_PYTHON%" "src\main.py" unblock %*
echo.
pause
