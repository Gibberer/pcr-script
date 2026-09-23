@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 scripts\daily\story_event.py %*
) else (
    python -X utf8 scripts\daily\story_event.py %*
)
exit /b %errorlevel%
