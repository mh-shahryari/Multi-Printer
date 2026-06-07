@echo off
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%"
title Multi Printer Monitoring - Starting...

:: ============================================================
::   Multi Printer Monitoring  -  Start Script
:: ============================================================

echo.
echo  ============================================================
echo   Multi Printer Monitoring
echo  ============================================================
echo.

:: --- Step 1: Check Python --------------------------------
echo [1/5] Checking Python installation...
set "PY_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%PY_EXE%" (
    set "PY_CMD=%PY_EXE%"
) else (
    set "PY_CMD=python"
)

"%PY_CMD%" --version > nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python not found.
    echo  Install Python 3.10+ from https://www.python.org/downloads/
    echo  Check 'Add Python to PATH' during installation.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('"%PY_CMD%" --version 2^>^&1') do set PY_VER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 goto :python_old
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 goto :python_old
echo  [OK] Python %PY_VER% (3.10+ required)
goto :step2

:python_old
echo  [ERROR] Python %PY_VER% is too old. Requires 3.10+
pause
exit /b 1

:: --- Step 2: Clean cache ---------------------------------
:step2
echo [2/5] Cleaning Python cache...
for /d /r "%SCRIPT_DIR%" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d" 2>nul
)
del /s /q "%SCRIPT_DIR%\*.pyc" 2>nul
echo  [OK] Cache cleared

:: --- Step 3: Install dependencies -----------------------
echo [3/5] Checking dependencies...
if not exist "%SCRIPT_DIR%requirements.txt" (
    echo  [SKIP] requirements.txt not found
    goto :step4
)
"%PY_CMD%" -m pip install -r "%SCRIPT_DIR%requirements.txt" -q --disable-pip-version-check
if errorlevel 1 (
    echo  [WARN] Some packages may have failed. Run manually if needed:
    echo         pip install -r requirements.txt
) else (
    echo  [OK] Dependencies ready
)

:: --- Step 4: Check project files ------------------------
:step4
echo [4/5] Checking project files...
if not exist "%SCRIPT_DIR%run.py" (
    echo  [ERROR] run.py not found. Run this script from the project root folder.
    popd
    pause
    exit /b 1
)
echo  [OK] run.py
if exist "%SCRIPT_DIR%printers.json"   (echo  [OK] printers.json)   else (echo  [INFO] printers.json    - will be created on first run)
if exist "%SCRIPT_DIR%logs.db"         (echo  [OK] logs.db)         else (echo  [INFO] logs.db          - will be created on first run)
if exist "%SCRIPT_DIR%oid_profiles.json" (echo  [OK] oid_profiles.json) else (echo  [INFO] oid_profiles.json - will be created after first scan)

:: --- Step 5: Choose port --------------------------------
echo [5/5] Port configuration...
echo.
echo  Default port: 5053
echo  Press ENTER to keep default, or type a custom port (1024-65535):
echo.
set /p USER_PORT="  Port [5053]: "
if "%USER_PORT%"=="" set USER_PORT=5053

:: Validate: must be numeric
set PORT_VALID=1
for /f "delims=0123456789" %%i in ("%USER_PORT%") do set PORT_VALID=0
if "%PORT_VALID%"=="0" (
    echo  [WARN] Invalid input - using default port 5053
    set USER_PORT=5053
)

:: Export FLASK_PORT to environment so run.py can pick it up
set FLASK_PORT=%USER_PORT%
if not "%USER_PORT%"=="5053" (
    echo  [OK] Port set to %USER_PORT% (exported FLASK_PORT)
) else (
    echo  [OK] Using default port %USER_PORT%
)

:: --- Launch ---------------------------------------------
echo.
echo  ============================================================
echo   Launching on http://localhost:%USER_PORT%/
echo   Press Ctrl+C to stop the server
echo  ============================================================
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://localhost:%USER_PORT%/'"

"%PY_CMD%" run.py

:: --- Stopped --------------------------------------------
echo.
echo  Printer Monitor stopped.
popd
pause
