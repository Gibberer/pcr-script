@echo on
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 daily_task.py
) else (
    python -X utf8 daily_task.py
)
pause
@REM timeout /t 300
@REM echo "try kill process dnplayer.exe ..."
@REM taskkill /IM dnplayer.exe /F /T
