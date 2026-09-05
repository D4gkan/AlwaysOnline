# Installation guide

## Prerequisites

- Python 3.11+
- A Discord server where you can create a webhook (Server Settings →
  Integrations → Webhooks)
- Windows, or a Linux host you can leave running (see `docs/hosting.md`
  if you need to choose one)

## Windows (local machine)

```bat
setup.bat
```

This creates a virtual environment, installs dependencies, installs the
Playwright Chromium browser, and copies `.env.example` to `.env`.

1. Edit `.env` and set `DISCORD_WEBHOOK_URL` to your webhook URL.
2. Create your first account:
   ```bat
   python -m app.cli.main account create
   ```
   You'll be prompted for a name and the two target URLs (defaults are
   provided for the CSFloat stall page and CSGOEmpire home page).
3. Launch it once to log in manually:
   ```bat
   python -m app.cli.main account launch <name>
   ```
   Two Chrome windows open (CSFloat, CSGOEmpire). Log in normally in each
   — this is a real browser, so 2FA/Steam Guard/CAPTCHA all work exactly
   as they would if you'd opened the tabs yourself.
4. Start the always-on monitor:
   ```bat
   start.bat
   ```
  This runs the scheduler and optional Discord bot without opening a
  terminal window. Leave the GUI running.

## Linux (server or always-on machine)

```bash
bash scripts/install_linux.sh
```

This creates a virtual environment, installs dependencies, installs
Chromium via Playwright (with system deps), and copies `.env.example` to
`.env`. Then:

1. Edit `.env` and set `DISCORD_WEBHOOK_URL`.
2. `source .venv/bin/activate`
3. `python -m app.cli.main account create`
4. `python -m app.cli.main account launch <name>` — on a headless server,
   wrap this in `xvfb-run -a` so the "visible" browser has a virtual
   display to render into:
   ```bash
   xvfb-run -a python -m app.cli.main account launch <name>
   ```
   You'll need a way to see the browser to complete the first login —
   either run this step on a machine with a real display, or use a VNC
   server pointed at the Xvfb display for one-time manual login, then
   move the resulting `browser_profiles/` directory to the server.
5. Install as a systemd service for auto-start and auto-restart:
   ```bash
   sudo cp scripts/cs2-session-monitor.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now cs2-session-monitor
   ```
   Edit the `User=`, `WorkingDirectory=`, and paths in the unit file
   first to match your install location.

## Configuration reference

All configuration lives in `.env` (copy from `.env.example`). See that
file for the full list with defaults; the ones you're most likely to
change:

| Variable | Purpose |
|---|---|
| `DISCORD_WEBHOOK_URL` | required — where alerts are sent |
| `DISCORD_BOT_TOKEN` | optional — enables the `/status` slash command |
| `HEALTH_CHECK_INTERVAL_SEC` | how often each site is checked (default 300) |
| `HEADLESS` | keep `false`; use Xvfb on servers instead |

## Verifying it's working

- `python -m app.cli.main status` prints a table of every account/site state.
- Watch `logs/operations.log` for short state-change lines.
- You should see a `SYSTEM ONLINE` message in Discord shortly after
  `python -m app.main` (or `start.bat`) starts.

## Uninstalling an account

```bash
python -m app.cli.main account delete <name>
```

Requires confirmation (or pass `--yes`), stops that account's monitoring,
and removes its local record and browser profile directories. This only
affects local monitor data — it does not touch the real CSFloat/
CSGOEmpire account in any way.
