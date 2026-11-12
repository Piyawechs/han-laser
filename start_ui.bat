@echo off
rem Start han-laser UI (first time: pip install -r requirements.txt)
cd /d "%~dp0"
start "" pythonw han_laser_ui.pyw %*
