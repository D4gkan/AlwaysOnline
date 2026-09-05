#!/usr/bin/env bash
# One-time setup for a Linux host: venv, deps, Playwright browser, Xvfb.
# Run from the repo root: bash scripts/install_linux.sh
set -euo pipefail

if ! command -v python3 >/dev/null; then
  echo "python3 not found. Install Python 3.11+ first." >&2
  exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install --with-deps chromium

if ! command -v xvfb-run >/dev/null; then
  echo "xvfb-run not found. On Debian/Ubuntu: sudo apt install xvfb"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env - edit it and set DISCORD_WEBHOOK_URL before starting."
fi

cat <<'EOF'

Setup complete.

Next steps:
  1. Edit .env and set DISCORD_WEBHOOK_URL.
  2. source .venv/bin/activate
  3. python -m app.cli.main account create
  4. python -m app.cli.main account launch <name>   # log in manually once
  5. To run under systemd (auto-start + auto-restart):
       sudo cp scripts/cs2-session-monitor.service /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now cs2-session-monitor
EOF
