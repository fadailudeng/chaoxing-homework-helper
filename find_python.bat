@echo off
rem ============================================================
rem  Shared helper: locate a Python interpreter.
rem
rem  Other .bat files call this. Do not run it directly.
rem
rem  LOOKUP ORDER
rem    1. %XXT_PYTHON% / %XXT_PYTHONW% if you already set them
rem    2. the "py" launcher (ships with python.org installs)
rem    3. "python" on PATH (skipping the Microsoft Store stub,
rem       which prints a "not found" notice and silently fails)
rem
rem  Why not hardcode a path: an absolute interpreter path only
rem  works on the machine it was written on. This is explicit
rem  about which Python it found so a failure is easy to read.
rem
rem  !! KEEP THIS FILE PURE ASCII !!  (cmd.exe breaks on a
rem  .bat that mixes "chcp 65001" with non-ASCII bytes)
rem ============================================================

if defined XXT_PYTHON goto :have_py
if defined XXT_PYTHONW goto :have_pyw

rem 0) Explicit escape hatch: point XXT_VENV at a virtualenv folder and
rem    we use that interpreter, no probing at all. Handy when your env is
rem    somewhere none of the guesses below would look.
if defined XXT_VENV (
  if exist "%XXT_VENV%\Scripts\python.exe" set "XXT_PY=%XXT_VENV%\Scripts\python.exe"
  if not defined XXT_PY if exist "%XXT_VENV%\python.exe" set "XXT_PY=%XXT_VENV%\python.exe"
  if not defined XXT_PY if exist "%XXT_VENV%" if not "%XXT_VENV%"=="" (
    rem maybe they pointed straight at the exe
    if exist "%XXT_VENV%" set "XXT_PY=%XXT_VENV%"
  )
  if defined XXT_PY if not exist "%XXT_PY%" set "XXT_PY="
)

rem 1) A previously remembered interpreter (written by the "remember"
rem    branch at the bottom). Kept in a git-ignored file so an absolute
rem    local path never lands in the repo.
set "XXT_PY="
set "XXT_PYFILE=%~dp0.pyfound"
if exist "%XXT_PYFILE%" (
  set /p XXT_PY=<"%XXT_PYFILE%"
  if not exist "%XXT_PY%" set "XXT_PY="
)

rem 2) Common places. These are *candidates*, not requirements -- a
rem    missing entry is skipped silently. Nothing machine-specific is
rem    hardcoded here (no absolute user paths), so this file is safe to
rem    publish as-is. Add your own below if your Python lives somewhere
rem    unusual; or just set XXT_PYTHON before launching.
if not defined XXT_PY (
  for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python312\python.exe"
  ) do (
    if not defined XXT_PY if exist %%p (
      %%p -c "import playwright" >nul 2>nul && set "XXT_PY=%%~p"
    )
  )
)

rem 2b) Interpreter inside a virtualenv / Conda env. Users keep these all
rem     over the place, so we look in the parent folders that are most
rem     likely: a "python" or "venvs" folder under the user profile, a
rem     .workbuddy/venv layout, and the Conda roots. Still no absolute
rem     user-specific path is written down.
rem
rem     Also: if you keep your venv somewhere else, just set XXT_VENV to
rem     its folder and this probe will use it directly.
if not defined XXT_PY (
  for %%r in ("%USERPROFILE%\.venv" "%USERPROFILE%\venv" "%USERPROFILE%\venvs"
              "%USERPROFILE%\python" "%USERPROFILE%\Documents\venvs"
              "%USERPROFILE%\.workbuddy\binaries\python\envs"
              "%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3"
              "%LOCALAPPDATA%\miniconda3" "%LOCALAPPDATA%\anaconda3"
              "C:\ProgramData\miniconda3" "C:\ProgramData\anaconda3") do (
    if not defined XXT_PY if exist %%r (
      rem a venv used directly as this very folder
      if not defined XXT_PY if exist "%%~r\Scripts\python.exe" (
        "%%~r\Scripts\python.exe" -c "import playwright" >nul 2>nul && set "XXT_PY=%%~r\Scripts\python.exe"
      )
      if not defined XXT_PY if exist "%%~r\python.exe" (
        "%%~r\python.exe" -c "import playwright" >nul 2>nul && set "XXT_PY=%%~r\python.exe"
      )
      rem ...or a folder containing many envs ("default", "myenv", ...)
      for /d %%e in ("%%~r\*") do (
        if not defined XXT_PY if exist "%%~e\Scripts\python.exe" (
          "%%~e\Scripts\python.exe" -c "import playwright" >nul 2>nul && set "XXT_PY=%%~e\Scripts\python.exe"
        )
        if not defined XXT_PY if exist "%%~e\python.exe" (
          "%%~e\python.exe" -c "import playwright" >nul 2>nul && set "XXT_PY=%%~e\python.exe"
        )
      )
    )
  )
)

rem 3) Last resort: whatever "py"/"python" resolves to on PATH. Same
rem    import check -- this is what stops us from picking a bare Python
rem    that has no packages installed and producing a confusing crash
rem    several steps later.
if not defined XXT_PY (
  for %%c in (py python) do (
    if not defined XXT_PY (
      where %%c >nul 2>nul && (
        %%c -c "import playwright" >nul 2>nul && set "XXT_PY=%%c"
      )
    )
  )
)

if not defined XXT_PY (
  echo.
  echo   [X] Could not find a Python that has the dependencies installed.
  echo.
  echo   Install them first:
  echo.
  echo       python -m pip install playwright
  echo       python -m playwright install chromium
  echo.
  echo   ...or point XXT_PYTHON at the interpreter that has them:
  echo.
  echo       set XXT_PYTHON=C:\path\to\python.exe
  echo.
  pause
  exit /b 1
)

rem Remember the absolute path for next time, so the probe only runs once.
for /f "delims=" %%i in ('%XXT_PY% -c "import sys;print(sys.executable)" 2^>nul') do (
  >"%XXT_PYFILE%" echo %%i
)

rem Resolve pythonw.exe next to the interpreter we found (same folder).
set "XXT_PYW="
for /f "delims=" %%i in ('%XXT_PY% -c "import sys,os;p=sys.executable;print(os.path.join(os.path.dirname(p),'pythonw.exe'))" 2^>nul') do set "XXT_PYW=%%i"
if not exist "%XXT_PYW%" set "XXT_PYW=%XXT_PY%"

set "XXT_PYTHON=%XXT_PY%"
set "XXT_PYTHONW=%XXT_PYW%"
exit /b 0

:have_py
if defined XXT_PYTHONW exit /b 0
set "XXT_PYTHONW=%XXT_PYTHON%"
exit /b 0

:have_pyw
if defined XXT_PYTHON exit /b 0
set "XXT_PYTHON=%XXT_PYTHONW%"
exit /b 0
