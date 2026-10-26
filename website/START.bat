@echo off
cd /d "%~dp0"
title RTO E-Challan Website
set "PY=%~dp0..\backend\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\backend\.venv313\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo Website: http://127.0.0.1:8000/
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
