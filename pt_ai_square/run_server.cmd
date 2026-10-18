@echo off
setlocal
cd /d "%~dp0.."
set "PTAI_PYTHON=python"
if exist ".venv-square\Scripts\python.exe" set "PTAI_PYTHON=.venv-square\Scripts\python.exe"
echo Uses environment variables and pt_ai_square\runtime_config.py. Read README.md first.
"%PTAI_PYTHON%" -m pt_ai_square run
pause
