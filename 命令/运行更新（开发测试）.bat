@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
pushd "%~dp0.." 2>nul
set "ROOT=%CD%"
popd
set "PAYLOAD=%ROOT%\dist\update"
for /d %%D in ("%PAYLOAD%\Argos翻译-*-更新包") do set "PKG=%%D"
if not defined PKG (
    echo [INFO] Building payload first...
    "%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\build_update_package.py"
    for /d %%D in ("%PAYLOAD%\Argos翻译-*-更新包") do set "PKG=%%D"
)
if not defined PKG (
    echo [ERROR] No payload folder under dist\update
    pause
    exit /b 1
)
echo [INFO] Update target: %ROOT%
echo [INFO] Payload: %PKG%
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\updater_main.py" --payload "%PKG%" --target "%ROOT%" --force
pause
