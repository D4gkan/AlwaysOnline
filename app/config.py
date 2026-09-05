"""
Central configuration.

All configuration is read from environment variables (optionally loaded
from a local `.env` file). Nothing secret is ever hard-coded here, and
nothing secret is written to logs, config files, or Discord.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv  # python-dotenv
    load_dotenv()
except ImportError:
    # dotenv is optional at import time; setup scripts install it.
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR = BASE_DIR / "accounts"
PROFILES_DIR = BASE_DIR / "browser_profiles"
LOGS_DIR = BASE_DIR / "logs"
SCREENSHOTS_DIR = BASE_DIR / "logs" / "screenshots"

for _d in (ACCOUNTS_DIR, PROFILES_DIR, LOGS_DIR, SCREENSHOTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # --- Discord ---
    discord_webhook_url: str = field(default_factory=lambda: os.environ.get("DISCORD_WEBHOOK_URL", ""))
    discord_bot_token: str = field(default_factory=lambda: os.environ.get("DISCORD_BOT_TOKEN", ""))
    discord_app_id: str = field(default_factory=lambda: os.environ.get("DISCORD_APPLICATION_ID", ""))
    discord_guild_id: str = field(default_factory=lambda: os.environ.get("DISCORD_GUILD_ID", ""))

    # --- Monitoring cadence ---
    health_check_interval_sec: int = field(default_factory=lambda: _env_int("HEALTH_CHECK_INTERVAL_SEC", 300))
    light_activity_min_sec: int = field(default_factory=lambda: _env_int("LIGHT_ACTIVITY_MIN_SEC", 300))
    light_activity_max_sec: int = field(default_factory=lambda: _env_int("LIGHT_ACTIVITY_MAX_SEC", 900))
    refresh_interval_sec: int = field(default_factory=lambda: _env_int("REFRESH_INTERVAL_SEC", 1800))
    retry_attempts: int = field(default_factory=lambda: _env_int("RETRY_ATTEMPTS", 2))
    retry_backoff_sec: int = field(default_factory=lambda: _env_int("RETRY_BACKOFF_SEC", 15))

    # --- Browser ---
    headless: bool = field(default_factory=lambda: _env_bool("HEADLESS", False))
    use_xvfb: bool = field(default_factory=lambda: _env_bool("USE_XVFB", False))
    browser_zoom_percent: int = field(default_factory=lambda: _env_int("BROWSER_ZOOM_PERCENT", 60))
    window_width: int = field(default_factory=lambda: _env_int("WINDOW_WIDTH", 256))
    window_height: int = field(default_factory=lambda: _env_int("WINDOW_HEIGHT", 256))

    # --- Logging ---
    log_retention_days: int = field(default_factory=lambda: _env_int("LOG_RETENTION_DAYS", 7))

    # --- URLs (defaults only; per-account overrides live in account records) ---
    csfloat_default_url: str = "https://csfloat.com/stall/me"
    csgoempire_default_url: str = "https://csgoempire.com/deposit"


settings = Settings()
