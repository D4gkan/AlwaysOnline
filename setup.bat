@echo off
setlocal

echo === AlwaysOnline setup ===

echo Recommended: press Ctrl + Windows + D to create a clean desktop profile, then run this bot there.

dir "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3.11+ from https://www.python.org/downloads/windows/ and rerun this script.
    exit /b 1
  )
)

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing Python dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Installing Playwright browsers...
python -m playwright install chromium

set BRAVE_PATH=C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe
if not exist "%BRAVE_PATH%" (
  echo WARNING: Brave was not found at %BRAVE_PATH%.
  echo Install Brave from https://brave.com/download/ before launching the bot.
  echo The app can still be configured, but Brave is the recommended browser backend.
)

if not exist ".env" (
  echo Creating .env from .env.example...
  copy .env.example .env
  echo Edit .env and set DISCORD_WEBHOOK_URL before starting.
)

if not exist "accounts" mkdir accounts
if not exist "browser_profiles" mkdir browser_profiles
if not exist "logs" mkdir logs
if not exist "logs\screenshots" mkdir "logs\screenshots"

echo.
echo Setup complete.
echo 1. Edit .env and fill in DISCORD_WEBHOOK_URL.
echo 2. Create accounts one at a time, leaving about 1 minute between each.
echo 3. Launch the GUI:       start.bat
echo 4. Or CLI launch:        python -m app.cli.main account launch ^<name^>
echo.
endlocal
