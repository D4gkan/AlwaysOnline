# AlwaysOnline

<div align="center">
  <img src="icon.ico" alt="AlwaysOnline Logo" width="96" />
  <p><strong>CSFloat & CSGOEmpire Session Monitor</strong></p>
  <p>
    <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version 0.1.0" />
    <a href="#license"><img src="https://img.shields.io/badge/license-All%20Rights%20Reserved-red.svg" alt="All Rights Reserved" /></a>
  </p>
</div>

---

## 📖 READ BEFORE LAUNCH

> **Recommended:** Press `Ctrl + Windows + D` to create a new desktop profile, then launch this bot there. This keeps your sessions isolated and stable.

---

## What is AlwaysOnline?

AlwaysOnline is a Windows-focused monitoring bot that keeps your CSFloat and CSGOEmpire browser sessions alive and healthy. It:

- 🔍 **Monitors** your trading sessions every few minutes
- 🎯 **Detects** login expiries, CAPTCHAs, 2FA prompts, and connection issues
- 📲 **Alerts** you on Discord with screenshots when something needs attention
- 🔧 **Auto-resumes** once you manually fix an issue in the visible browser window
- 📊 **Does NOT** spoof, bypass, or fake anything—it watches real sessions

This is **not a bot evasion tool**. It simply keeps visible browser tabs open the way you would if you watched them yourself.

---

## Quick Start

### 1️⃣ Install

```bat
setup.bat
```

This will:
- Create a Python virtual environment
- Install required dependencies
- Set up Playwright browsers
- Create a `.env` file (edit with your Discord webhook)

### 2️⃣ Configure

Open `.env` and add your Discord webhook:

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your/webhook
```

### 3️⃣ Create Accounts

Launch the GUI:

```bat
start.bat
```

Or use the CLI:

```bat
python -m app.cli.main account create
```

**⏰ Tip:** When creating multiple accounts, wait ~1 minute between each to keep profiles stable.

### 4️⃣ Launch

From your clean desktop profile, run:

```bat
start.bat
```

The bot opens visible browser windows. Log in manually, and it monitors automatically.

---

## How It Works

### Architecture

```
Account Record (JSON)
    ↓
Browser Profile (isolated per account/site)
    ↓
Health Check (every ~5 min)
    ↓
State Classification (healthy / login required / CAPTCHA / offline / etc)
    ↓
Discord Alert (on state change)
```

### Session States

| State | Meaning | Action |
|-------|---------|--------|
| ✅ **Healthy** | Session is good | Continue monitoring, occasional refresh |
| 🔐 **Login Required** | Account logged out | ⏸️ Paused—fix in browser, auto-resumes |
| 🔒 **2FA Required** | Steam Guard needed | ⏸️ Paused—complete in browser |
| 🤖 **CAPTCHA** | Challenge detected | ⏸️ Paused—solve in browser |
| ⏱️ **Timeout** | Page load failed | Retry with backoff |
| 🔴 **Offline** | Connection down | Alert, continue checking |

---

## Commands

### GUI

```bat
start.bat
```

Manage accounts visually:
- Create new account
- Launch existing account
- Test active sessions
- Stop running sessions

### CLI

```bash
# Create an account
python -m app.cli.main account create

# Launch an account (opens browser windows)
python -m app.cli.main account launch <name>

# View all account statuses
python -m app.cli.main status

# Request screenshots on demand
python -m app.cli.main request-screenshots

# Delete an account
python -m app.cli.main account delete <name>

# Run the background monitor
python -m app.main

# Open the GUI manager
python -m app.gui
```

---

## Folder Structure

```
AlwaysOnline/
├── app/                    # Core application
│   ├── accounts/          # Account management & models
│   ├── browser/           # Browser session manager
│   ├── health/            # Health checks & page detection
│   ├── notify/            # Discord notifications
│   ├── cli/               # Command-line interface
│   ├── dashboard/         # (Web dashboard resources)
│   ├── utils/             # Logging & helpers
│   ├── config.py          # Central configuration
│   ├── gui.py             # Desktop GUI
│   ├── main.py            # Background monitor
│   └── scheduler.py       # Monitoring loop
├── accounts/              # Account records (JSON)
├── browser_profiles/      # Isolated browser profiles
├── logs/                  # Runtime logs & screenshots
├── tests/                 # Automated tests
├── docs/                  # Detailed documentation
├── .env                   # Secrets (git-ignored)
├── .env.example           # Template
├── requirements.txt       # Python dependencies
├── setup.bat              # Setup script
├── start.bat              # Launch script
├── LICENSE                # MIT License
└── README.md              # This file
```

---

## Security

✅ **Safe practices:**
- Account credentials **never stored** in JSON files
- Discord webhook URL kept in `.env` (git-ignored)
- Session cookies & tokens stay in the browser profile only
- No credentials logged or sent to Discord
- Only screenshots of the visible page sent (no credentials)

---

## Configuration

Edit `.env` to customize behavior:

```env
# Required
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Optional (for slash commands)
DISCORD_BOT_TOKEN=...
DISCORD_APPLICATION_ID=...
DISCORD_GUILD_ID=...

# Monitoring intervals (seconds)
HEALTH_CHECK_INTERVAL_SEC=300          # Check every 5 min
LIGHT_ACTIVITY_MIN_SEC=300             # Scroll range minimum
LIGHT_ACTIVITY_MAX_SEC=900             # Scroll range maximum
REFRESH_INTERVAL_SEC=1800              # Full refresh every 30 min
RETRY_ATTEMPTS=2                       # Retry failed checks
RETRY_BACKOFF_SEC=15                   # Wait between retries

# Browser
HEADLESS=false                         # Keep visible (recommended)
BROWSER_ZOOM_PERCENT=60                # Window zoom level
WINDOW_WIDTH=256                       # Window dimensions
WINDOW_HEIGHT=256
```

---

## Testing

Run the automated test suite:

```bat
.venv\Scripts\activate
pytest
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Brave not found** | Install from https://brave.com/download/ |
| **Python not found** | Install Python 3.11+ from python.org |
| **Discord alerts not working** | Check `.env` has a valid `DISCORD_WEBHOOK_URL` |
| **Browser profiles corrupted** | Delete the profile under `browser_profiles/` and re-login |
| **Multiple accounts conflicting** | Create each account ~1 minute apart |

---

## Feedback & Issues

We're still in development! We'd love your feedback.

Found a bug? **Please open an issue** with:
- What went wrong
- Which account/site was affected
- Steps to reproduce
- Screenshots or logs if available

💬 We're open to suggestions and improvements.

---

## License

All Rights Reserved — see [LICENSE](LICENSE) for details.

This project is proprietary. You may make private local modifications for your own use, but redistribution, sharing, publication, resale, or reuse by others is not permitted without the express written permission of the copyright holder.

---

<div align="center">
  <p><strong>AlwaysOnline v0.1.0</strong></p>
  <p>Keep your sessions alive. Stay ahead. Never miss a deal.</p>
</div>

