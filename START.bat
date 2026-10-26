@echo off
title RTO E-Challan System Launcher
cd /d "%~dp0"

echo =========================================================================
echo       AI Driven Camera Detected RTO E-Challan System
echo =========================================================================
echo.

:: 1. Check Python installation
set "PYTHON_CMD="
where python >nul 2>&1 && set "PYTHON_CMD=python"
if "%PYTHON_CMD%"=="" where py >nul 2>&1 && set "PYTHON_CMD=py"

if "%PYTHON_CMD%"=="" (
  echo [ERROR] Python is not installed or not found in system PATH!
  echo.
  echo Please download and install Python 3.10+ from:
  echo   https://www.python.org/downloads/
  echo.
  echo CRITICAL: Ensure you check "Add python.exe to PATH" during installation.
  echo =========================================================================
  pause
  exit /b 1
)

:: 2. Check Node.js / NPM installation
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js / npm is not installed or not found in system PATH!
  echo.
  echo Please download and install Node.js (LTS version) from:
  echo   https://nodejs.org/
  echo =========================================================================
  pause
  exit /b 1
)

:: 3. Check if .venv is valid on THIS machine (fixes copied folder path issues)
set "REBUILD_VENV=0"
if not exist "backend\.venv\Scripts\python.exe" (
  set "REBUILD_VENV=1"
) else (
  "backend\.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo [Notice] Virtual environment was copied from another laptop.
    echo Resetting Python environment for this machine...
    rmdir /s /q "backend\.venv"
    set "REBUILD_VENV=1"
  )
)

if "%REBUILD_VENV%"=="1" (
  echo Creating fresh Python virtual environment on this machine...
  cd backend
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    cd ..
    pause
    exit /b 1
  )
  echo Installing backend dependencies (this only happens once)...
  call .venv\Scripts\pip.exe install --default-timeout 100 -r requirements.txt
  cd ..
)

:: 4. Ensure .env files exist
if not exist "backend\.env" if exist "backend\.env.example" (
  copy "backend\.env.example" "backend\.env" >nul
)
if not exist "frontend\.env" if exist "frontend\.env.example" (
  copy "frontend\.env.example" "frontend\.env" >nul
)

:: 5. Ensure frontend node_modules exist
if not exist "frontend\node_modules" (
  echo Installing frontend packages (first run)...
  cd frontend
  call npm install
  cd ..
)

echo.
echo Starting Backend and Frontend servers...
echo.

:: 6. Launch Backend on port 8000
start "RTO Backend (Port 8000)" cmd /k "title RTO Backend ^& cd /d "%~dp0backend" ^& echo Starting FastAPI backend on http://127.0.0.1:8000 ... ^& .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload || (echo. ^& echo [ERROR] Backend crashed or failed to start. Check above messages. ^& pause)"

:: 7. Wait 3 seconds for backend to initialize
timeout /t 3 /nobreak >nul

:: 8. Launch Frontend on port 5173
start "RTO Frontend (Port 5173)" cmd /k "title RTO Frontend ^& cd /d "%~dp0frontend" ^& echo Starting Vite UI on http://localhost:5173 ... ^& npm run dev || (echo. ^& echo [ERROR] Frontend failed to start. ^& pause)"

echo =========================================================================
echo  System is running:
echo    - Backend API : http://127.0.0.1:8000
echo    - Frontend UI : http://localhost:5173
echo    - Admin Login : ADMIN001  /  Admin@123
echo =========================================================================
echo.
timeout /t 2 /nobreak >nul
start http://localhost:5173

echo Keep the two opened terminal windows (Backend and Frontend) open.
pause
