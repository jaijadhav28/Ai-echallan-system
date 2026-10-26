@echo off
REM One-link website: build React UI, then serve FE+BE together on port 8000.
cd /d "%~dp0"

echo Building frontend...
cd frontend
if not exist "node_modules" (
  echo Installing frontend packages...
  call npm install
)
if not exist ".env" if exist ".env.example" (
  copy ".env.example" ".env" >nul
)
call npm run build
if errorlevel 1 (
  echo Frontend build failed.
  exit /b 1
)

cd ..\backend
if not exist ".env" if exist ".env.example" (
  copy ".env.example" ".env" >nul
)

set "PYTHON_CMD=python"
where python >nul 2>&1 || (where py >nul 2>&1 && set "PYTHON_CMD=py")

set "REBUILD_VENV=0"
if not exist ".venv\Scripts\python.exe" (
  set "REBUILD_VENV=1"
) else (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo [Notice] Virtual environment was copied from another machine. Re-creating...
    rmdir /s /q ".venv"
    set "REBUILD_VENV=1"
  )
)

if "%REBUILD_VENV%"=="1" (
  echo Creating Python venv...
  %PYTHON_CMD% -m venv .venv
  call .venv\Scripts\pip.exe install --default-timeout 100 -r requirements.txt
)

echo.
echo Starting website at http://127.0.0.1:8000/
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
