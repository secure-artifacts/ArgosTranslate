@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
pushd "%~dp0"
set "ROOT=%CD%"
popd
cd /d "%ROOT%"
set "XDG_DATA_HOME=%ROOT%\data\local"
set "XDG_CONFIG_HOME=%ROOT%\data\config"
set "XDG_CACHE_HOME=%ROOT%\data\cache"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo [DEBUG] Running with console — errors will show below.
echo Root: %ROOT%
echo.
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\portable_launcher.py"
echo.
echo Exit code: %ERRORLEVEL%
pause
