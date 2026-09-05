@echo off
setlocal

echo Recommended: press Ctrl + Windows + D to create a clean desktop profile and run this bot there.

echo Starting AlwaysOnline...

if not exist ".venv" (
  echo Virtual environment not found. Run setup.bat first.
  exit /b 1
)

call .venv\Scripts\activate.bat

if not exist ".env" (
  echo .env not found. Copy .env.example to .env and set DISCORD_WEBHOOK_URL before launching.
  exit /b 1
)

if not exist "accounts" mkdir accounts
if not exist "browser_profiles" mkdir browser_profiles
if not exist "logs" mkdir logs
if not exist "logs\screenshots" mkdir "logs\screenshots"

set BROWSER=brave
set BRAVE_PATH=C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe

if not exist "%BRAVE_PATH%" (
  echo WARNING: Brave was not found at %BRAVE_PATH%.
  echo Install Brave before launching multi-account monitoring.
)

echo Opening the AlwaysOnline account manager...
start "" /b ".venv\Scripts\pythonw.exe" -m app.gui

endlocal
