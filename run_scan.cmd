@echo off
REM Windows Task Scheduler entry point. Runs one scan and exits.
REM Keep this file ASCII-only: cmd.exe mangles non-ASCII in some codepages.
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo. >> logs\scan.log
echo ===== %DATE% %TIME% ===== >> logs\scan.log
"C:\Users\deaja\AppData\Local\Programs\Python\Python312\python.exe" -u main.py scan >> logs\scan.log 2>&1
