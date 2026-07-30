@echo off
setlocal EnableExtensions EnableDelayedExpansion
title RELAY

rem ===========================================================================
rem  RELAY -- double-click launcher for Windows.
rem
rem  First run: finds Python, builds a private environment beside this file,
rem  installs the dependencies and downloads the browser the collectors drive.
rem  Every run after that: starts the dashboard and opens it. Nothing is
rem  installed twice -- the setup is repeated only when requirements.txt
rem  changes, which is the one thing that can make the environment stale.
rem
rem  Nothing here touches the system Python or the PATH. Delete the .venv-win
rem  folder to undo the install completely.
rem ===========================================================================

rem Explorer starts a double-clicked .bat in the folder it lives in, but a
rem shortcut or a scheduled task can hand it C:\Windows\System32 -- and RELAY
rem resolves ./data against the working directory. Pin both, so the reports and
rem the run history always land beside this file.
cd /d "%~dp0"
set "RELAY_DATA_DIR=%~dp0data"

rem A separate name from .venv: this folder is often shared with a Linux
rem checkout, and the two environments cannot use the same directory.
set "VENV=%~dp0.venv-win"
set "PY=%VENV%\Scripts\python.exe"
set "STAMP=%VENV%\.relay-requirements.txt"

echo(
echo   RELAY  --  Somoy TV sponsored-content reporting
echo   ================================================
echo(

if not exist "%PY%" goto :setup

rem Re-install when requirements.txt has changed since the last setup. Without
rem this check a dependency bump would silently never reach the desktop.
fc /b "%STAMP%" "%~dp0requirements.txt" >nul 2>&1 || goto :deps
goto :run


rem --- first-time setup ------------------------------------------------------
:setup
call :find_python
if not defined LAUNCHER goto :no_python
echo   Setting RELAY up. This happens once and takes a few minutes.
echo(
echo   [1/3] Creating a private Python environment...
%LAUNCHER% -m venv "%VENV%"
if errorlevel 1 goto :failed

:deps
echo   [2/3] Installing dependencies...
"%PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%PY%" -m pip install --quiet --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto :failed

echo   [3/3] Downloading the browser the collectors drive (about 150 MB)...
"%PY%" -m playwright install chromium
if errorlevel 1 (
  echo(
  echo   Note: the browser download did not finish. Matching, the dashboard and
  echo   report generation still work -- only the Facebook/Instagram/X
  echo   collectors need it. Run this file again later to retry.
  echo(
)

rem Stamped last: if anything above failed we did not get here, so the next
rem run repeats the install rather than assuming it succeeded.
copy /y "%~dp0requirements.txt" "%STAMP%" >nul
echo(
echo   Setup complete.
echo(


rem --- run -------------------------------------------------------------------
:run
echo   Starting RELAY -- your browser will open in a moment.
echo   Keep this window open while you work. Closing it stops RELAY.
echo(
"%PY%" -m relay.cli serve --host 127.0.0.1 --port 8501 --auto-port --open
if errorlevel 1 goto :failed
exit /b 0


rem --- finding a Python ------------------------------------------------------
rem The py launcher ships with every python.org install and can name an exact
rem version; a Microsoft Store install may only put `python` on the PATH.
:find_python
set "LAUNCHER="
for %%V in (3.12 3.13 3.14 3) do call :try_py %%V
if defined LAUNCHER exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
if not errorlevel 1 set "LAUNCHER=python"
exit /b 0

:try_py
if defined LAUNCHER exit /b 0
py -%1 -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
if not errorlevel 1 set "LAUNCHER=py -%1"
exit /b 0


rem --- failure paths ---------------------------------------------------------
:no_python
echo   RELAY needs Python 3.12 or newer, and this PC does not have it.
echo(
where winget >nul 2>&1 && goto :offer_winget
echo   Install it from   https://www.python.org/downloads/
echo   Tick "Add python.exe to PATH" in the installer, then run this file again.
goto :halt

:offer_winget
choice /c YN /n /m "   Install Python 3.12 now? [Y/N] "
if errorlevel 2 goto :halt
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
echo(
echo   Close this window and double-click "Start RELAY" again -- Windows only
echo   picks up the new Python in a fresh window.
goto :halt

:failed
echo(
echo   Something went wrong. The lines above say what.
echo   If it mentions pip or a network error, check the connection and try again.
goto :halt

:halt
echo(
pause
exit /b 1
