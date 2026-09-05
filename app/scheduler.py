"""
Monitoring scheduler.

Runs the always-on loop:
  - per-account, per-site health checks on a timer
  - occasional light activity on healthy sessions
  - periodic refresh (~30 min) on healthy sessions
  - global outage detection (many simultaneous failures -> one alert,
    not N alerts)
  - re-checks paused accounts so they auto-resume once the operator fixes
    them in the visible browser window

This module holds the in-memory "is this a global outage" state used by the
always-on monitor.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from app.accounts import store as account_store
from app.accounts.models import Account, Site, SessionState
from app.browser.manager import BrowserManager
from app.config import settings
from app.health import checker
from app.notify.discord import DiscordNotifier
from app.utils.logging_setup import op_log

logger = logging.getLogger("scheduler")

SITES = (Site.CSFLOAT, Site.CSGOEMPIRE)

# If at least this fraction of sites fail with a connectivity-shaped error
# in the same sweep, treat it as one global outage rather than N alerts.
_OUTAGE_FRACTION_THRESHOLD = 0.6
_OUTAGE_MIN_SITES = 3

_CONNECTIVITY_STATES = {SessionState.PAGE_TIMEOUT, SessionState.OFFLINE, SessionState.BROWSER_CRASH}


@dataclass
class MonitorState:
    started_at: float = field(default_factory=time.time)
    in_global_outage: bool = False
    last_sweep_at: float = 0.0
    last_sweep_results: dict[tuple[str, str], dict] = field(default_factory=dict)

    def uptime_seconds(self) -> float:
        return time.time() - self.started_at


class Scheduler:
    def __init__(self, notifier: DiscordNotifier | None = None) -> None:
        self.manager = BrowserManager()
        self.notifier = notifier or DiscordNotifier()
        self.state = MonitorState()
        self._stopping = asyncio.Event()
        self._next_refresh_at: dict[tuple[str, str], float] = {}
        self._next_activity_at: dict[tuple[str, str], float] = {}

    async def startup(self) -> None:
        await self.manager.start()
        accounts = account_store.list_all()
        session_count = len(accounts) * len(SITES)
        healthy = 0
        for idx, account in enumerate(accounts):
            for site in SITES:
                result = await checker.check_site(self.manager, account, site, idx)
                account_store.save(account)
                op_log(f"{account.name} {site.value} {result.state.value}")
                if result.state == SessionState.HEALTHY:
                    healthy += 1
        await self.notifier.notify_startup(len(accounts), session_count, healthy)
        self.state.last_sweep_at = time.time()

    async def run_forever(self) -> None:
        await self.startup()
        while not self._stopping.is_set():
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("Unhandled error during sweep")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=settings.health_check_interval_sec)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stopping.set()
        await self.manager.stop()

    async def sweep_once(self) -> None:
        accounts = account_store.list_all()
        now = time.time()
        results = []

        for idx, account in enumerate(accounts):
            for site in SITES:
                site_state = account.site_state(site)
                key = (account.name, site.value)

                if site_state.paused:
                    resumed = await checker.try_resume_if_recovered(self.manager, account, site, idx)
                    if resumed is not None:
                        result = resumed
                    else:
                        continue
                else:
                    result = await checker.check_site(self.manager, account, site, idx)

                account_store.save(account)
                results.append(result)
                self.state.last_sweep_results[key] = {
                    "state": result.state.value,
                    "reason": result.reason,
                    "checked_at": now,
                }
                op_log(f"{account.name} {site.value} {result.state.value}" + (f" ({result.reason})" if result.state != SessionState.HEALTHY else ""))

                if result.changed:
                    sent = await self.notifier.notify_state_change(
                        account.name, site, result.state, result.reason, result.screenshot_path
                    )
                    if sent:
                        op_log(f"Discord alert sent for {account.name} {site.value}: {result.state.value}")

                # Light activity / periodic refresh only for healthy, unpaused sites.
                if result.state == SessionState.HEALTHY:
                    if now >= self._next_activity_at.get(key, 0):
                        await checker.light_activity_if_healthy(self.manager, account, site, idx)
                        self._next_activity_at[key] = now + random.randint(
                            settings.light_activity_min_sec, settings.light_activity_max_sec
                        )
                    if now >= self._next_refresh_at.get(key, now + settings.refresh_interval_sec):
                        await checker.refresh_if_healthy(self.manager, account, site, idx)
                        self._next_refresh_at[key] = now + settings.refresh_interval_sec
                    elif key not in self._next_refresh_at:
                        self._next_refresh_at[key] = now + settings.refresh_interval_sec

        await self._evaluate_global_outage(results)
        self.state.last_sweep_at = now

    async def _evaluate_global_outage(self, results: list) -> None:
        if not results:
            return
        connectivity_failures = sum(1 for r in results if r.state in _CONNECTIVITY_STATES)
        fraction = connectivity_failures / len(results)
        is_outage_now = connectivity_failures >= _OUTAGE_MIN_SITES and fraction >= _OUTAGE_FRACTION_THRESHOLD

        if is_outage_now and not self.state.in_global_outage:
            self.state.in_global_outage = True
            await self.notifier.notify_global_outage()
            op_log("Global outage detected")
        elif not is_outage_now and self.state.in_global_outage:
            self.state.in_global_outage = False
            await self.notifier.notify_global_recovery()
            op_log("Global outage recovered")
