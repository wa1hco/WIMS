@echo off
REM Sets PYTHON_EXE for callers (call this script). Prefer install pin, then common paths.
set "PYTHON_EXE="
if exist "%~dp0python-path.txt" (
  set /p PYTHON_EXE=<"%~dp0python-path.txt"
)
if defined PYTHON_EXE if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python313\python.exe"
if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%ProgramFiles%\Python313\python.exe"
if exist "%PYTHON_EXE%" goto :eof
set "PYTHON_EXE=%ProgramFiles%\Python312\python.exe"
if exist "%PYTHON_EXE%" goto :eof
where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_EXE=py"
  goto :eof
)
REM Last resort — may be Store stub; prefer failing clearly
set "PYTHON_EXE=python"
