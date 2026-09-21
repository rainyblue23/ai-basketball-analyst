@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%CD%\src
set PYTHONIOENCODING=utf-8
set PY=%CD%\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo ============================================================
echo   AI Hoop Analyst - backend (FastAPI)
echo ------------------------------------------------------------
echo   API docs : http://127.0.0.1:8000/docs
echo   Health   : http://127.0.0.1:8000/api/health
echo   Frontend : open web\index.html (or use the demo launcher)
echo ------------------------------------------------------------
echo   AUTO-RESTART IS ON.
echo   uvicorn loads the source only once at startup, so editing a
echo   .py file normally has NO effect on a running server and
echo   raises no error ("changed it, nothing changed"). This
echo   launcher watches src\aihoop\*.py and restarts automatically.
echo.
echo   The upload page shows code_rev / code_loaded_at / stale from
echo   /api/health, so a stale process is visible at a glance.
echo   Close this window (or Ctrl+C) to stop the backend.
echo ============================================================
echo.

"%PY%" scripts\serve_reload.py 8000
pause
