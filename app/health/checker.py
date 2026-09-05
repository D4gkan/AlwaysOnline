"""
Health check orchestrator.

For each (account, site):
  1. ensure a browser session exists
  2. navigate to the target URL
  3. classify the resulting page
  4. on failure, retry a couple of times with short backoff
  5. update the account's persisted site state
  6. return a HealthResult so the caller (scheduler) can decide whether to
     fire alerts, take a screenshot, or pause the account.

This module contains no Discord/alerting logic itself -- it only reports
results. That separation keeps notification policy (dedupe, formatting)
out of the detection code.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import Error as PlaywrightError
from app.accounts.models import Account, Site, SessionState, SiteState
from app.browser.manager import BrowserManager, SiteSession
from app.config import settings, SCREENSHOTS_DIR
from app.health import detectors

logger = logging.getLogger("health.checker")

# States that warrant pausing the site and waiting on the operator, i.e.
# "manual intervention" states rather than transient blips.
MANUAL_INTERVENTION_STATES = {
    SessionState.LOGIN_REQUIRED,
    SessionState.TWO_FACTOR_REQUIRED,
    SessionState.CAPTCHA,
    SessionState.SESSION_EXPIRED,
    SessionState.CHALLENGE,
    SessionState.IDENTITY_MISMATCH,
}


@dataclass
class HealthResult:
    account_name: str
    site: Site
    state: SessionState
    reason: str
    screenshot_path: Optional[Path] = None
    changed: bool = False  # True if this differs from the previously recorded state


async def check_site(
    manager: BrowserManager,
    account: Account,
    site: Site,
    account_index: int,
    *,
    expected_identity: Optional[str] = None,
    take_screenshot_on_problem: bool = True,
    check_while_paused: bool = False,
) -> HealthResult:
    site_state: SiteState = account.site_state(site)

    if site_state.paused and not check_while_paused:
        return HealthResult(account.name, site, SessionState.PAUSED, "paused pending operator action", changed=False)

    url = account.url_for(site)
    attempts = max(1, settings.retry_attempts)
    last_state = SessionState.OFFLINE
    last_reason = "unknown failure"

    for attempt in range(1, attempts + 1):
        try:
            session: SiteSession = await manager.get_or_create_session(account, site, account_index)
            await manager.navigate(session, url)
            state, reason = await detectors.classify(session.page, site, expected_identity)
            last_state, last_reason = state, reason
            if state == SessionState.HEALTHY:
                break
            if state in MANUAL_INTERVENTION_STATES:
                # These aren't transient -- retrying navigation won't fix a
                # CAPTCHA/login/2FA prompt and could re-trigger it
                # needlessly. Escalate immediately instead of retrying.
                break
        except PlaywrightError as exc:
            last_state, last_reason = SessionState.BROWSER_CRASH, f"playwright error: {exc}"
        except asyncio.TimeoutError:
            last_state, last_reason = SessionState.PAGE_TIMEOUT, "navigation timed out"
        except Exception as exc:  # last resort -- never let one account crash the loop
            logger.exception("Unexpected error checking %s/%s", account.name, site.value)
            last_state, last_reason = SessionState.OFFLINE, f"unexpected error: {exc}"

        if attempt < attempts:
            await asyncio.sleep(settings.retry_backoff_sec)

    changed = last_state.value != site_state.state
    screenshot_path = None
    if take_screenshot_on_problem and last_state != SessionState.HEALTHY:
        try:
            session = await manager.get_or_create_session(account, site, account_index)
            fname = f"{account.name}-{site.value}-{int(time.time())}.png"
            screenshot_path = await manager.screenshot(session, SCREENSHOTS_DIR / fname)
        except Exception:
            logger.exception("Failed to capture screenshot for %s/%s", account.name, site.value)

    now = time.time()
    site_state.state = last_state.value
    site_state.last_checked = now
    site_state.last_error = "" if last_state == SessionState.HEALTHY else last_reason
    if last_state == SessionState.HEALTHY:
        site_state.last_healthy = now
        site_state.consecutive_failures = 0
        site_state.paused = False
    else:
        site_state.consecutive_failures += 1
        if last_state in MANUAL_INTERVENTION_STATES:
            site_state.paused = True
    if screenshot_path:
        site_state.last_screenshot = str(screenshot_path)

    return HealthResult(
        account_name=account.name,
        site=site,
        state=last_state,
        reason=last_reason,
        screenshot_path=screenshot_path,
        changed=changed,
    )


async def light_activity_if_healthy(manager: BrowserManager, account: Account, site: Site, account_index: int) -> None:
    site_state = account.site_state(site)
    if site_state.state != SessionState.HEALTHY.value or site_state.paused:
        return
    try:
        session = await manager.get_or_create_session(account, site, account_index)
        await manager.light_activity(session)
    except Exception:
        logger.debug("Light activity skipped for %s/%s", account.name, site.value, exc_info=True)


async def refresh_if_healthy(manager: BrowserManager, account: Account, site: Site, account_index: int) -> None:
    site_state = account.site_state(site)
    if site_state.state != SessionState.HEALTHY.value or site_state.paused:
        return
    try:
        session = await manager.get_or_create_session(account, site, account_index)
        await manager.refresh(session)
    except Exception:
        logger.debug("Periodic refresh skipped for %s/%s", account.name, site.value, exc_info=True)


async def try_resume_if_recovered(
    manager: BrowserManager, account: Account, site: Site, account_index: int, *, expected_identity: Optional[str] = None
) -> Optional[HealthResult]:
    """Re-check a paused site; if it's now healthy, clear the pause.

    Called by the scheduler for paused accounts so that once the operator
    manually completes a login/CAPTCHA/2FA in the visible browser window,
    monitoring resumes automatically instead of staying paused forever.
    """
    site_state = account.site_state(site)
    if not site_state.paused:
        return None
    result = await check_site(
        manager, account, site, account_index,
        expected_identity=expected_identity,
        take_screenshot_on_problem=False,
        check_while_paused=True,
    )
    return result
