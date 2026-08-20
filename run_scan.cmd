@echo off
REM Windows Task Scheduler entry point. Runs one scan and exits.
REM Keep this file ASCII-only: cmd.exe mangles non-ASCII in some codepages.
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PY="C:\Users\deaja\AppData\Local\Programs\Python\Python312\python.exe"
echo. >> logs\scan.log
echo ===== %DATE% %TIME% ===== >> logs\scan.log

REM 1) Pull the newest price history that GitHub Actions may have pushed.
REM    Both sides must share alerts_sent, or the same deal is alerted twice.
%PY% -u git_sync.py pull >> logs\scan.log 2>&1

REM 2) Scan and send alerts.
%PY% -u main.py scan >> logs\scan.log 2>&1

REM 3) Push this scan's history back (personal data is scrubbed first).
%PY% -u git_sync.py push >> logs\scan.log 2>&1
