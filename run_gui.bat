@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
REM Portable local translator - GUI via pythonw (must use CRLF line endings on Windows)
pushd "%~dp0" 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot open install folder.
    pause
    exit /b 1
)
set "ROOT=%CD%"
popd
if not defined ROOT (
    echo [ERROR] Failed to resolve install root.
    pause
    exit /b 1
)
if not exist "%ROOT%\venv\Scripts\pythonw.exe" (
    echo [ERROR] Missing Python environment:
    echo   %ROOT%\venv\Scripts\pythonw.exe
    echo.
    echo This folder is not a complete install.
    echo See: %ROOT%\命令\首次安装说明.txt
    echo.
    echo Do not run only the launcher exe from Downloads folder.
    pause
    exit /b 1
)
set "XDG_DATA_HOME=%ROOT%\data\local"
set "XDG_CONFIG_HOME=%ROOT%\data\config"
set "XDG_CACHE_HOME=%ROOT%\data\cache"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "ARGOS_FAST_STARTUP=1"
set "ARGOS_DEBUG=0"
cd /d "%ROOT%"

echo.
echo [Local Translator] Starting. Window in about 2 seconds.
echo.

if exist "%ROOT%\tools\apply_portable_gui_patch.py" (
    "%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\apply_portable_gui_patch.py" >nul 2>&1
)

if exist "%ROOT%\portable_launcher.py" (
    start "" "%ROOT%\venv\Scripts\pythonw.exe" "%ROOT%\portable_launcher.py"
    endlocal
    exit /b 0
)

start "" "%ROOT%\venv\Scripts\pythonw.exe" -c "from argostranslategui import gui; gui.main()"
endlocal
exit /b 0
