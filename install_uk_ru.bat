@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
pushd "%~dp0" 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot open install folder.
    pause
    exit /b 1
)
set "ROOT=%CD%"
popd
set "XDG_DATA_HOME=%ROOT%\data\local"
set "XDG_CONFIG_HOME=%ROOT%\data\config"
set "XDG_CACHE_HOME=%ROOT%\data\cache"
set "PYTHONUTF8=1"

echo.
echo [Argos] Installing Ukrainian -^> Russian direct package (OPUS-MT)...
echo First run downloads ~275MB; keep network connected.
echo.

"%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\build_uk_ru_from_opus_zip.py"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
    echo.
    echo [ERROR] Install failed, code %EC%
    pause
    exit /b %EC%
)
echo.
echo [OK] uk-^>ru installed. Restart run_gui.bat, select Ukrainian -^> Russian.
pause
endlocal
exit /b 0
