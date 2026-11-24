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
  echo Python was not found.
  echo Install Python 3.10 - 3.12 from https://www.python.org/downloads/windows/
  echo IMPORTANT: Check "Add Python to PATH" during installation.
  pause
  exit /b 1
)

echo Installing required packages...
%PYTHON_CMD% -m pip install --upgrade pip
if errorlevel 1 goto install_error
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 goto install_error

echo Starting Video AutoClicker...
%PYTHON_CMD% main.py
if errorlevel 1 (
  echo The program stopped with an error.
  pause
)
exit /b 0

:install_error
echo Package installation failed. Check your Internet connection and Python installation.
pause
exit /b 1
