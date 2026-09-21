@echo off
cd /d "%~dp0\..\.."
".venv\Scripts\python.exe" -X utf8 scripts\daily\caravan.py %*
exit /b %errorlevel%
