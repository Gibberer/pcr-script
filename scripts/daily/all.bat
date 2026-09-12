@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 daily_task.py
) else (
    python -X utf8 daily_task.py
)
exit /b %errorlevel%
