"""
Health detectors.

Each detector inspects the *currently loaded* page (URL + visible text +
a few structural signals) and returns a SessionState. These are simple,
transparent heuristics -- text/selector matching on the normal page a
logged-in human would also see. Nothing here tries to defeat a CAPTCHA
or challenge; it only recognizes that one is present so the operator can
be alerted.

Because site markup changes over time, keep the signal list here small,
well-commented, and easy to update -- treat false positives (falsely
flagging a healthy page as broken) as the priority failure mode to avoid,
since they cause alert spam.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import Page

from app.accounts.models import Site, SessionState

logger = logging.getLogger("health.detectors")

_CAPTCHA_SIGNALS = [
    "captcha", "hcaptcha", "recaptcha", "verify you are human", "cf-turnstile",
]
_CHALLENGE_SIGNALS = [
    "checking your browser", "just a moment", "attention required",
    "cloudflare", "ddos protection by",
]
_LOGIN_SIGNALS = [
    "sign in", "log in", "login with steam", "connect with steam",
    "you need to log in", "session expired", "please log in",
]
_TWO_FACTOR_SIGNALS = [
    "steam guard", "mobile authenticator", "enter the code", "two-factor",
    "2fa",
]


@dataclass
class PageSnapshot:
    url: str
    text_lower: str


async def snapshot(page: Page) -> PageSnapshot:
    url = page.url
    try:
        text = await page.inner_text("body")
    except Exception:
        text = ""
    return PageSnapshot(url=url, text_lower=text.lower())


def _any_signal(text: str, signals: list[str]) -> Optional[str]:
    for s in signals:
        if s in text:
            return s
    return None


def classify_generic(snap: PageSnapshot) -> SessionState:
    """Signals common to both sites, checked first (challenge > captcha > 2FA > login)."""
    if _any_signal(snap.text_lower, _CHALLENGE_SIGNALS):
        return SessionState.CHALLENGE
    if _any_signal(snap.text_lower, _CAPTCHA_SIGNALS):
        return SessionState.CAPTCHA
    if _any_signal(snap.text_lower, _TWO_FACTOR_SIGNALS):
        return SessionState.TWO_FACTOR_REQUIRED
    if _any_signal(snap.text_lower, _LOGIN_SIGNALS):
        return SessionState.LOGIN_REQUIRED
    return SessionState.UNKNOWN


async def check_identity(page: Page, site: Site, expected_identity: Optional[str]) -> bool:
    """Best-effort check that the page shows the expected account identity.

    `expected_identity` is an operator-provided string (e.g. a Steam
    display name or CSFloat username) stored only in the account's local
    notes, never guessed automatically. If not configured, identity
    checking is skipped (returns True) rather than producing false
    mismatch alerts.
    """
    if not expected_identity:
        return True
    try:
        text = await page.inner_text("body")
    except Exception:
        return True
    return expected_identity.lower() in text.lower()


async def classify_csfloat(page: Page, expected_identity: Optional[str] = None) -> tuple[SessionState, str]:
    snap = await snapshot(page)
    generic = classify_generic(snap)
    if generic != SessionState.UNKNOWN:
        return generic, f"matched signal on csfloat page ({generic.value})"

    if "/stall/" not in snap.url and "csfloat.com" not in snap.url:
        return SessionState.PAGE_TIMEOUT, "unexpected url after navigation"

    if not await check_identity(page, Site.CSFLOAT, expected_identity):
        return SessionState.IDENTITY_MISMATCH, "expected identity not found on page"

    return SessionState.HEALTHY, "ok"


# Presence of the balance/currency element is the authenticated-state
# indicator for CSGOEmpire: it only renders for a logged-in session, so its
# absence after the render timeout is the sole lost-session signal. Page
# text, URL, and the generic detectors above are intentionally not used.
# checker.check_site retries a miss according to settings.retry_attempts.
CSGOEMPIRE_BALANCE_SELECTOR = '[data-testid="currency-amount"]'
CSGOEMPIRE_BALANCE_TIMEOUT_MS = 30_000


async def has_csgoempire_balance_element(page: Page) -> bool:
    """Check whether the CSGOEmpire authenticated-balance element is present.

    CSGOEmpire is a client-rendered application. ``domcontentloaded`` fires
    while its loading splash is still visible, so an immediate query can
    produce a false negative. Wait for the same single selector rather than
    using any additional page signal.

    Safe to call even if the page/browser was just closed out from under
    us -- returns False instead of raising, so a closed page is reported
    as "no balance element" rather than crashing the health check.
    """
    try:
        element = await page.wait_for_selector(
            CSGOEMPIRE_BALANCE_SELECTOR,
            state="attached",
            timeout=CSGOEMPIRE_BALANCE_TIMEOUT_MS,
        )
    except Exception:
        logger.debug("CSGOEmpire balance-element check failed (page may be closed)", exc_info=True)
        return False
    return element is not None


async def classify_csgoempire(page: Page, expected_identity: Optional[str] = None) -> tuple[SessionState, str]:
    """Classify CSGOEmpire solely by its authenticated balance element.

    The page's text and URL are deliberately ignored. CSGOEmpire may render
    login, 2FA, or challenge-related wording inside an otherwise authenticated
    application shell; none of those signals is as reliable as the account's
    currency amount being present in the DOM.
    """
    has_balance = await has_csgoempire_balance_element(page)
    logger.debug("CSGOEmpire %s found: %s", CSGOEMPIRE_BALANCE_SELECTOR, has_balance)
    if has_balance:
        return SessionState.HEALTHY, "currency-amount element found"

    # OFFLINE (rather than a MANUAL_INTERVENTION_STATE) is deliberate: it
    # keeps this in checker.py's transient-failure retry path instead of
    # pausing the account immediately, so a page that is merely still
    # loading gets a few chances to resolve itself before anyone is alerted.
    return SessionState.OFFLINE, "authenticated balance element not found (session may have expired)"


async def classify(page: Page, site: Site, expected_identity: Optional[str] = None) -> tuple[SessionState, str]:
    if site == Site.CSFLOAT:
        return await classify_csfloat(page, expected_identity)
    return await classify_csgoempire(page, expected_identity)
