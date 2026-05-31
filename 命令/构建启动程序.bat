@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
pushd "%~dp0.." 2>nul
set "ROOT=%CD%"
popd
echo [INFO] Building launcher with embedded icon (first run may take several minutes)...
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\build_app_launcher.py"
if errorlevel 1 pause & exit /b 1
echo.
echo [OK] After build, start via run_gui.bat — taskbar will show your icon.
pause
