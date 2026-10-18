@echo off
setlocal
cd /d "%~dp0.."
set "PTAI_AUTH_MODE=mock"
set "MONGODB_URI=mongodb://127.0.0.1:27018/"
set "MONGODB_DATABASE=pt_ai_square_preview"
set "PTAI_MOCK_ADMIN=true"
set "PTAI_COOKIE_SECURE=false"
set "PTAI_DATA_DIR=%CD%\pt_ai_square\.preview"
set "PTAI_PYTHON=python"
if exist ".venv-square\Scripts\python.exe" set "PTAI_PYTHON=.venv-square\Scripts\python.exe"
"%PTAI_PYTHON%" -c "import flask,waitress" >nul 2>&1
if errorlevel 1 (
  echo Install dependencies first: python -m pip install -r pt_ai_square\requirements.txt
  pause
  exit /b 1
)
"%PTAI_PYTHON%" -m pt_ai_square.seed_preview
echo Open http://127.0.0.1:5080 in your browser. Press Ctrl+C to stop.
"%PTAI_PYTHON%" -m pt_ai_square run
pause
