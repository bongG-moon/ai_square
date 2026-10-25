@echo off
setlocal
cd /d "%~dp0"
echo AI SQUARE now connects in your AI chat. No KEY input window opens.
echo After registering this MCP, ask: Connect AI SQUARE.
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
echo.
echo First-time MCP registration: ask your AI to register run_mcp.py in this folder.
echo "%~dp0run_mcp.py"
pause
endlocal
