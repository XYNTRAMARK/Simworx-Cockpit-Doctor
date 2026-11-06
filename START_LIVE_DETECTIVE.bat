@echo off
cd /d "%~dp0"
echo SIMWORX Cockpit Doctor - Live Change Detective v0.5
py -3 -c "import websocket" >nul 2>&1
if errorlevel 1 (
  echo Installing required websocket-client package...
  py -3 -m pip install websocket-client
  if errorlevel 1 (
    echo Installation failed. Please copy this message to ChatGPT.
    pause
    exit /b 1
  )
)
py -3 LiveChangeDetective.py
if errorlevel 1 pause
