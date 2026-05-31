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
echo [INFO] Building update payload...
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\build_update_package.py"
if errorlevel 1 pause & exit /b 1
echo.
echo [OK] See dist\update\ folder. Run 构建更新程序.bat to build the .exe
pause
