@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0run_mcp.py" connect
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 "%~dp0run_mcp.py" connect
  ) else (
    python "%~dp0run_mcp.py" connect
  )
)
if errorlevel 1 pause
endlocal
