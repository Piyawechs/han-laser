@echo off
rem Start han-laser UI. Uses .venv in this folder if present, otherwise global pythonw.
rem First time: python -m venv .venv  then  .venv\Scripts\pip install -r requirements.txt
cd /d "%~dp0"
set "PYW=pythonw"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"
start "" "%PYW%" han_laser_ui.pyw %*
