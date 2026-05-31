@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
pushd "%~dp0.." 2>nul
set "ROOT=%CD%"
popd
set "LAUNCH=%ROOT%\dist\本地翻译器\本地翻译器.exe"
set "ICON=%ROOT%\assets\app_icon.ico"
if not exist "%LAUNCH%" (
    set "LAUNCH=%ROOT%\run_gui.bat"
)
if not exist "%LAUNCH%" (
    echo [ERROR] Missing launcher. Run 构建启动程序.bat first.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\本地翻译器（俄乌）.lnk'); $lnk.TargetPath = '%LAUNCH%'; $lnk.WorkingDirectory = '%ROOT%'; if (Test-Path '%ICON%') { $lnk.IconLocation = '%ICON%,0' }; $lnk.Description = '本地翻译器（俄乌）'; $lnk.Save()"
if errorlevel 1 (
    echo [ERROR] Failed to create shortcut.
    pause
    exit /b 1
)
echo [OK] Desktop shortcut created: 本地翻译器（俄乌）.lnk
pause
