@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%"
title PrintGuard - Starting...

echo.
echo  ============================================================
echo   PrintGuard - Multi Printer Monitoring
echo  ============================================================
echo.

:: --- Step 1: Check Python ---
echo  [1/5] Checking Python...
set "PY_CMD=python"
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" set "PY_CMD=%SCRIPT_DIR%.venv\Scripts\python.exe"

"%PY_CMD%" --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('"%PY_CMD%" --version 2^>^&1') do echo  [OK] Python %%v

:: --- Step 2: Clean cache ---
echo  [2/5] Cleaning cache...
for /d /r "%SCRIPT_DIR%" %%d in (__pycache__) do rd /s /q "%%d" 2>nul
del /s /q "%SCRIPT_DIR%*.pyc" 2>nul
echo  [OK] Cache cleared

:: --- Step 3: Dependencies ---
echo  [3/5] Checking dependencies...
"%PY_CMD%" -m pip install -r "%SCRIPT_DIR%requirements.txt" -q --disable-pip-version-check 2>nul
echo  [OK] Dependencies ready

:: --- Step 4: Port ---
echo  [4/5] Port configuration...
set "USER_PORT=5053"
set /p USER_PORT="  Port [5053]: "
if "%USER_PORT%"=="" set USER_PORT=5053
set FLASK_PORT=%USER_PORT%
echo  [OK] Port: %USER_PORT%

:: --- Step 5: Kill old processes ---
echo  [5/5] Cleaning old processes on port %USER_PORT%...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%USER_PORT% " ^| findstr "LISTENING"') do (
    echo        Killing PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo  [OK] Port %USER_PORT% ready

:: --- Launch ---
echo.
echo  ============================================================
echo   Launching on http://localhost:%USER_PORT%/
echo   Press Ctrl+C to stop
echo  ============================================================
echo.

title PrintGuard [Port %USER_PORT%]

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 3; Start-Process 'http://localhost:%USER_PORT%/'"

"%PY_CMD%" run.py

echo.
echo  PrintGuard stopped.
popd
pause
