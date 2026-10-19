@echo off
setlocal
cd /d "%~dp0"
set "PTAI_PYTHON=python"
if exist ".venv-square\Scripts\python.exe" set "PTAI_PYTHON=.venv-square\Scripts\python.exe"
echo Uses runtime_config.py in this folder. Read README.md first.
"%PTAI_PYTHON%" web_main.py
pause
