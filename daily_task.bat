@echo on
python daily_task.py
pause
@REM timeout /t 300
@REM echo "try kill process dnplayer.exe ..."
@REM taskkill /IM dnplayer.exe /F /T