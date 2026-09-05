"""
Browser session manager.

Manages one persistent, isolated Chrome profile + visible window per
(account, site) pair. This intentionally does NOT do anything to disguise
automation, spoof fingerprints, rotate proxies, or fake human input beyond
a small amount of harmless scrolling to prevent idle/staleness. The whole
point is a normal, visible, long-lived logged-in browser tab that a human
also could have left open.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

from app.accounts.models import Account, Site
from app.config import settings

logger = logging.getLogger("browser.manager")


def _ensure_firefox_profile_layout(profile_dir: Path) -> None:
    """Create a valid Firefox profile directory layout so Firefox accepts the profile on Windows."""
    root = profile_dir.parent
    root.mkdir(parents=True, exist_ok=True)
    profile_name = profile_dir.name
    profiles_ini = root / "profiles.ini"
    if not profiles_ini.exists():
        profiles_ini.write_text(
            "[Install4F96D1932A9F858E]\n"
            "Default=Profiles/\n"
            "Locked=1\n\n"
            f"[Profile0]\n"
            f"Name={profile_name}\n"
            f"IsRelative=1\n"
            f"Path={profile_name}\n"
            "Default=1\n",
            encoding="utf-8",
        )
    else:
        text = profiles_ini.read_text(encoding="utf-8", errors="ignore")
        if f"Path={profile_name}" not in text:
            text = text.rstrip() + "\n\n" + (
                f"[Profile0]\n"
                f"Name={profile_name}\n"
                f"IsRelative=1\n"
                f"Path={profile_name}\n"
                "Default=1\n"
            )
            profiles_ini.write_text(text, encoding="utf-8")

    profile_dir.mkdir(parents=True, exist_ok=True)


# Compact, stable non-overlapping square window geometry, one slot per
# (account_index, site). Grid wraps across the screen with a fallback
# for small displays via env-configured width/height.
_COLS = 4
_WINDOW_GAP = 12


def _get_screen_dimensions() -> tuple[int, int]:
    """Get screen dimensions, falling back to default if unable to detect."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()  # Hide the window
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return width, height
    except Exception:
        # Fallback to common screen size
        return 1920, 1080


def window_position(account_index: int, site: Site) -> tuple[int, int]:
    """Derive a stable, non-overlapping (x, y) screen position, constrained to screen bounds."""
    slot = account_index * 2 + (0 if site == Site.CSFLOAT else 1)
    col = slot % _COLS
    row = slot // _COLS
    x = col * (settings.window_width + _WINDOW_GAP)
    y = row * (settings.window_height + _WINDOW_GAP)
    
    # Constrain to screen bounds to prevent windows from spawning off-screen
    screen_width, screen_height = _get_screen_dimensions()
    max_x = max(0, screen_width - settings.window_width - 50)  # 50px margin
    max_y = max(0, screen_height - settings.window_height - 100)  # 100px margin (taskbar)
    
    x = min(x, max_x)
    y = min(y, max_y)
    
    return x, y


def browser_name() -> str:
    """Return the configured browser backend; Brave is the preferred default on Windows."""
    return (os.environ.get("BROWSER") or "brave").strip().lower() or "brave"


def firefox_window_geometry_script(x: int, y: int, width: int, height: int) -> str:
    """Return script that moves and resizes the current Firefox window to a unique location."""
    return (
        "window.moveTo(arguments[0], arguments[1]); "
        "window.resizeTo(arguments[2], arguments[3]);"
    )


def brave_launch_options() -> dict[str, str]:
    """Use the installed Brave browser when available."""
    options: dict[str, str] = {}
    brave_path = os.environ.get("BRAVE_PATH") or os.environ.get("BRAVE_BIN")
    if brave_path:
        options["executable_path"] = brave_path
    elif os.name == "nt":
        candidates = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                options["executable_path"] = candidate
                break
    return options


def firefox_launch_options() -> dict[str, str]:
    """Use the installed Firefox browser if available."""
    options: dict[str, str] = {}
    firefox_path = (
        os.environ.get("FIREFOX_PATH")
        or os.environ.get("MOZILLA_FIREFOX_PATH")
        or os.environ.get("FIREFOX_BIN")
    )
    if firefox_path:
        options["executable_path"] = firefox_path
    elif os.name == "nt":
        candidates = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                options["executable_path"] = candidate
                break
    return options


def chrome_launch_options() -> dict[str, str]:
    """Use the installed system Chrome so extensions and normal Chrome behavior work."""
    options: dict[str, str] = {"channel": "chrome"}
    chrome_path = os.environ.get("CHROME_PATH") or os.environ.get("GOOGLE_CHROME_PATH")
    if chrome_path:
        options["executable_path"] = chrome_path
    elif os.name == "nt":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                options["executable_path"] = candidate
                break
    return options


def browser_extension_paths() -> list[str]:
    """Return configured extension directories to load into Brave/Chromium."""
    raw: list[str] = []
    for key in ("EXTENSION_PATHS", "BRAVE_EXTENSION_PATHS", "CHROME_EXTENSION_PATHS"):
        val = os.environ.get(key)
        if not val:
            continue
        raw.extend(piece.strip() for piece in val.replace(";", ",").split(",") if piece.strip())
    return raw


def browser_extension_args(browser_kind: str) -> list[str]:
    """Return the flags needed to enable one or more unpacked extensions."""
    paths = browser_extension_paths()
    if not paths or browser_kind not in {"brave", "chrome"}:
        return []
    return [
        "--disable-extensions-except=" + ",".join(paths),
        *[f"--load-extension={path}" for path in paths],
    ]


def browser_chromium_launch_options() -> dict[str, bool | str]:
    """Ensure Chromium launches with sandboxing enabled unless explicitly disabled."""
    options: dict[str, bool | str] = {"chromium_sandbox": True}
    if browser_name() == "brave":
        options.update(brave_launch_options())
    else:
        options.update(chrome_launch_options())
    return options


@dataclass
class SiteSession:
    account_name: str
    site: Site
    context: BrowserContext
    page: Page


class BrowserManager:
    """Owns one Playwright driver and all live (account, site) sessions."""

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._sessions: dict[tuple[str, Site], SiteSession] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def stop(self) -> None:
        async with self._lock:
            for key in list(self._sessions.keys()):
                await self._close_session(key)
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    async def _close_session(self, key: tuple[str, Site]) -> None:
        session = self._sessions.pop(key, None)
        if session is not None:
            try:
                await session.context.close()
            except Exception:
                logger.exception("Error closing context for %s", key)

    async def get_or_create_session(
        self, account: Account, site: Site, account_index: int
    ) -> SiteSession:
        key = (account.name, site)
        async with self._lock:
            existing = self._sessions.get(key)
            if existing is not None:
                try:
                    # Confirm the underlying browser process/context is alive.
                    _ = existing.context.pages
                    return existing
                except Exception:
                    await self._close_session(key)

            await self.start()
            profile_dir: Path = account.profile_dir(site)
            browser_kind = browser_name()
            if browser_kind == "firefox":
                _ensure_firefox_profile_layout(profile_dir)
            else:
                profile_dir.mkdir(parents=True, exist_ok=True)
            x, y = window_position(account_index, site)

            if browser_kind == "firefox":
                user_data_dir = str(profile_dir)
                args = [
                    "-new-window",
                    "-width",
                    str(settings.window_width),
                    "-height",
                    str(settings.window_height),
                ]
                launch_options = firefox_launch_options()
                browser = self._playwright.firefox
            else:
                user_data_dir = str(profile_dir)
                args = [
                    f"--window-position={x},{y}",
                    f"--window-size={settings.window_width},{settings.window_height}",
                    "--disable-notifications",
                ]
                args.extend(browser_extension_args(browser_kind))
                launch_options = browser_chromium_launch_options()
                browser = self._playwright.chromium

            context = await browser.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=settings.headless,
                viewport={"width": settings.window_width, "height": settings.window_height - 90},
                args=args,
                **launch_options,
            )
            page = context.pages[0] if context.pages else await context.new_page()
            if browser_kind == "firefox":
                await page.evaluate(
                    firefox_window_geometry_script(x, y, settings.window_width, settings.window_height),
                    x,
                    y,
                    settings.window_width,
                    settings.window_height,
                )
            zoom = max(10, min(settings.browser_zoom_percent, 100)) / 100
            await page.evaluate("zoom => { document.body.style.zoom = String(zoom); }", zoom)
            await page.evaluate("zoom => { document.body.style.transform = `scale(${zoom})`; }", zoom)
            await page.evaluate("document.body.style.transformOrigin = 'top left' ;")
            await page.evaluate("zoom => { document.body.style.width = `${100 / zoom}%`; }", zoom)
            session = SiteSession(account_name=account.name, site=site, context=context, page=page)
            target_url = account.url_for(site)
            try:
                if not page.url or page.url == "about:blank":
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                logger.debug("Initial navigation skipped for %s/%s to %s", account.name, site.value, target_url, exc_info=True)
            self._sessions[key] = session
            return session

    async def close_session(self, account_name: str, site: Site) -> None:
        async with self._lock:
            await self._close_session((account_name, site))

    def is_running(self, account_name: str, site: Site) -> bool:
        return (account_name, site) in self._sessions

    async def navigate(self, session: SiteSession, url: str, timeout_ms: int = 30_000) -> None:
        await session.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    async def light_activity(self, session: SiteSession) -> None:
        """Minimal, harmless scroll activity to avoid idle/staleness.

        This is NOT meant to simulate a human or evade any detection --
        it's just enough interaction that the tab doesn't sit perfectly
        static for hours.
        """
        page = session.page
        try:
            down = random.randint(200, 600)
            await page.mouse.wheel(0, down)
            await asyncio.sleep(random.uniform(1.0, 2.5))
            if random.random() < 0.5:
                await page.mouse.wheel(0, -down // 2)
        except Exception:
            logger.debug("Light activity failed for %s/%s", session.account_name, session.site, exc_info=True)

    async def refresh(self, session: SiteSession, timeout_ms: int = 30_000) -> None:
        await session.page.reload(wait_until="domcontentloaded", timeout=timeout_ms)

    async def screenshot(self, session: SiteSession, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        await session.page.screenshot(path=str(path))
        return path
