@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto :run

set PYCMD=
py -3.13 --version >nul 2>&1
if not errorlevel 1 set PYCMD=py -3.13
if not defined PYCMD (
  py -3.12 --version >nul 2>&1
  if not errorlevel 1 set PYCMD=py -3.12
)
if not defined PYCMD (
  echo Python 3.12 or 3.13 is required ^(newer versions lack prebuilt packages^).
  goto :fail
)
echo Creating virtual environment with %PYCMD% ...
%PYCMD% -m venv .venv
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  rmdir /s /q .venv
  goto :fail
)

:run
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8765
goto :eof

:fail
echo.
echo Setup failed. See the messages above.
pause
