@echo off
rem Start han-laser UI. Uses .venv in this folder if present, otherwise global pythonw.
rem First time: python -m venv .venv  then  .venv\Scripts\pip install -r requirements.txt
rem FITS: copy fits_env.bat (same file as the bobcat bridge) next to this file.
cd /d "%~dp0"
if exist "fits_env.bat" call "fits_env.bat"
set "PYW=pythonw"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"
start "" "%PYW%" han_laser_ui.pyw %*
