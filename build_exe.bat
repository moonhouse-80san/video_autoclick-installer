@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo Python was not found. Install Python 3.10 - 3.12 first.
  pause
  exit /b 1
)

echo Installing build tools...
%PYTHON_CMD% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto build_error

echo Building exe (this takes a few minutes)...
%PYTHON_CMD% -m PyInstaller --noconfirm --clean --onefile --noconsole --name VideoAutoClick main.py
if errorlevel 1 goto build_error

echo.
echo Done: dist\VideoAutoClick.exe
echo config.json, images folder and autoclick.log are created next to the exe.
pause
exit /b 0

:build_error
echo Build failed. See the messages above.
pause
exit /b 1
