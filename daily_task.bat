@echo on
python daily_task.py
if %errorlevel% == 0 ( python main.py --config daily_config.yml --mode 1) ^
else if %errorlevel% == 1 ( python main.py --config daily_config.yml) ^
else (echo "failed")
pause