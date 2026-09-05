"""Account data model.

Account records are machine-readable (JSON) and hold ONLY non-secret
metadata: a name, the two target URLs, and bookkeeping fields. All
authentication state (cookies, Steam Guard, session tokens) lives inside
the browser profile directory itself, never inside this record.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

from app.config import settings

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Site(str, Enum):
    CSFLOAT = "csfloat"
    CSGOEMPIRE = "csgoempire"


class SessionState(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    LOGIN_REQUIRED = "login_required"
    TWO_FACTOR_REQUIRED = "two_factor_required"
    CAPTCHA = "captcha"
    SESSION_EXPIRED = "session_expired"
    CHALLENGE = "challenge"  # cloudflare / unexpected challenge page
    IDENTITY_MISMATCH = "identity_mismatch"
    BROWSER_CRASH = "browser_crash"
    PAGE_TIMEOUT = "page_timeout"
    OFFLINE = "offline"  # generic unhealthy state pending classification
    PAUSED = "paused"  # paused, waiting on operator


class AccountValidationError(ValueError):
    pass


def validate_account_name(name: str) -> str:
    """Validate an account name; raise if invalid or path-traversal-prone."""
    name = (name or "").strip()
    if not name or not _NAME_RE.match(name):
        raise AccountValidationError(
            "Account name must be 1-64 characters: letters, digits, '_' or '-' only."
        )
    if name in (".", "..") or "/" in name or "\\" in name:
        raise AccountValidationError("Account name may not contain path separators.")
    return name


def validate_url(url: str, *, required_host_suffix: Optional[str] = None) -> str:
    url = (url or "").strip()
    if not url.startswith("https://") and not url.startswith("http://"):
        raise AccountValidationError(f"URL must start with http(s)://: {url!r}")
    if required_host_suffix and required_host_suffix not in url:
        raise AccountValidationError(
            f"URL must point to a {required_host_suffix} page: {url!r}"
        )
    return url


@dataclass
class SiteState:
    state: str = SessionState.UNKNOWN.value
    last_checked: float = 0.0
    last_healthy: float = 0.0
    last_error: str = ""
    last_screenshot: str = ""
    paused: bool = False
    consecutive_failures: int = 0


@dataclass
class Account:
    name: str
    csfloat_url: str
    csgoempire_url: str
    created_at: float = field(default_factory=time.time)
    enabled: bool = True
    csfloat_state: SiteState = field(default_factory=SiteState)
    csgoempire_state: SiteState = field(default_factory=SiteState)

    @staticmethod
    def new(
        name: str,
        csfloat_url: Optional[str] = None,
        csgoempire_url: Optional[str] = None,
    ) -> "Account":
        name = validate_account_name(name)
        csfloat_url = validate_url(csfloat_url or settings.csfloat_default_url, required_host_suffix="csfloat.com")
        csgoempire_url = validate_url(csgoempire_url or settings.csgoempire_default_url, required_host_suffix="csgoempire.com")
        return Account(name=name, csfloat_url=csfloat_url, csgoempire_url=csgoempire_url)

    @staticmethod
    def chrome_profile_root() -> Path:
        from app.config import PROFILES_DIR
        return PROFILES_DIR / "chrome"

    @staticmethod
    def firefox_profile_root() -> Path:
        if os.name == "nt":
            local_appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            return Path(local_appdata) / "Mozilla" / "Firefox" / "Profiles"
        from app.config import PROFILES_DIR
        return PROFILES_DIR / "firefox"

    @staticmethod
    def brave_profile_root() -> Path:
        from app.config import PROFILES_DIR
        return PROFILES_DIR / "brave"

    def profile_dir(self, site: Site):
        from app.config import PROFILES_DIR

        browser = (os.environ.get("BROWSER") or "brave").lower()
        if browser == "firefox":
            return self.firefox_profile_root() / f"AlwaysOnline-{self.name}-{site.value}"
        if browser == "brave":
            return self.brave_profile_root() / f"AlwaysOnline-{self.name}-{site.value}"
        if browser == "chrome":
            return self.chrome_profile_root() / f"AlwaysOnline-{self.name}-{site.value}"
        if os.name == "nt":
            return self.chrome_profile_root() / f"AlwaysOnline-{self.name}-{site.value}"
        return PROFILES_DIR / self.name / site.value

    def site_state(self, site: Site) -> SiteState:
        return self.csfloat_state if site == Site.CSFLOAT else self.csgoempire_state

    def url_for(self, site: Site) -> str:
        return self.csfloat_url if site == Site.CSFLOAT else self.csgoempire_url

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Account":
        d = dict(d)
        d["csfloat_state"] = SiteState(**d.get("csfloat_state") or {})
        d["csgoempire_state"] = SiteState(**d.get("csgoempire_state") or {})
        return Account(**d)
