@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
pushd "%~dp0.." 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot open ArgosTranslate folder.
    pause
    exit /b 1
)
set "ROOT=%CD%"
popd
if not exist "%ROOT%\venv\Scripts\python.exe" (
    echo [ERROR] Missing venv.
    pause
    exit /b 1
)
echo [INFO] Building update .exe (may take a few minutes)...
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\build_update_exe.py"
if errorlevel 1 pause & exit /b 1
echo.
echo [OK] Distribute: dist\update\Argos翻译-*-更新.exe
echo Users double-click it to update installed ArgosTranslate and launch the app.
pause
