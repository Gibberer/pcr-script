@echo on
python daily_task.py
if %errorlevel% == 0 ( python main.py --config daily_config.yml ) else (echo 失败)
pause