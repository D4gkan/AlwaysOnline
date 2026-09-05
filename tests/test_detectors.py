import pytest

from app.accounts.models import Site, SessionState
from app.health import detectors


class FakePage:
    def __init__(self, url: str, body_text: str, *, has_balance_element: bool = True, closed: bool = False):
        self.url = url
        self._body_text = body_text
        self._has_balance_element = has_balance_element
        self._closed = closed

    async def inner_text(self, selector: str) -> str:
        return self._body_text

    async def query_selector(self, selector: str):
        if self._closed:
            raise RuntimeError("Target page, context or browser has been closed")
        if selector == detectors.CSGOEMPIRE_BALANCE_SELECTOR and self._has_balance_element:
            return object()  # stand-in ElementHandle
        return None

    async def wait_for_selector(self, selector: str, *, state: str, timeout: int):
        assert state == "attached"
        assert timeout == detectors.CSGOEMPIRE_BALANCE_TIMEOUT_MS
        return await self.query_selector(selector)


@pytest.mark.asyncio
async def test_classify_healthy_csfloat_page():
    page = FakePage("https://csfloat.com/stall/me", "My Stall\nItem 1\nItem 2")
    state, reason = await detectors.classify(page, Site.CSFLOAT)
    assert state == SessionState.HEALTHY


@pytest.mark.asyncio
async def test_classify_login_required():
    page = FakePage("https://csfloat.com/stall/me", "Please log in to continue")
    state, _ = await detectors.classify(page, Site.CSFLOAT)
    assert state == SessionState.LOGIN_REQUIRED


@pytest.mark.asyncio
async def test_classify_captcha():
    page = FakePage("https://csfloat.com/stall/me", "Please complete the hCaptcha to continue")
    state, _ = await detectors.classify(page, Site.CSFLOAT)
    assert state == SessionState.CAPTCHA


@pytest.mark.asyncio
async def test_classify_two_factor():
    page = FakePage("https://csfloat.com/stall/me", "Enter your Steam Guard code")
    state, _ = await detectors.classify(page, Site.CSFLOAT)
    assert state == SessionState.TWO_FACTOR_REQUIRED


@pytest.mark.asyncio
async def test_classify_challenge():
    page = FakePage("https://csfloat.com/stall/me", "Checking your browser before accessing csfloat.com")
    state, _ = await detectors.classify(page, Site.CSFLOAT)
    assert state == SessionState.CHALLENGE


@pytest.mark.asyncio
async def test_identity_mismatch_when_configured_and_absent():
    page = FakePage("https://csfloat.com/stall/me", "Someone Else's Stall")
    state, _ = await detectors.classify(page, Site.CSFLOAT, expected_identity="MyUsername")
    assert state == SessionState.IDENTITY_MISMATCH


@pytest.mark.asyncio
async def test_identity_present_is_healthy():
    page = FakePage("https://csfloat.com/stall/me", "MyUsername's Stall")
    state, _ = await detectors.classify(page, Site.CSFLOAT, expected_identity="MyUsername")
    assert state == SessionState.HEALTHY


@pytest.mark.asyncio
async def test_no_identity_configured_skips_check():
    page = FakePage("https://csfloat.com/stall/me", "Anyone's Stall")
    state, _ = await detectors.classify(page, Site.CSFLOAT, expected_identity=None)
    assert state == SessionState.HEALTHY


@pytest.mark.asyncio
async def test_csgoempire_healthy_when_balance_element_present():
    page = FakePage("https://csgoempire.com/deposit", "My Deposit", has_balance_element=True)
    state, reason = await detectors.classify(page, Site.CSGOEMPIRE)
    assert state == SessionState.HEALTHY
    assert "currency-amount element found" in reason


@pytest.mark.asyncio
async def test_csgoempire_authenticated_element_overrides_incidental_login_text():
    """A logged-in application shell may still render login wording in a
    menu or dormant modal.  The authenticated DOM marker is stronger proof."""
    page = FakePage(
        "https://csgoempire.com/deposit",
        "My Deposit\nLog in with Steam\n2FA help",
        has_balance_element=True,
    )
    state, reason = await detectors.classify(page, Site.CSGOEMPIRE)
    assert state == SessionState.HEALTHY
    assert "currency-amount element found" in reason


@pytest.mark.asyncio
async def test_csgoempire_login_text_without_authenticated_element_is_offline():
    page = FakePage(
        "https://csgoempire.com/deposit",
        "Please log in to continue",
        has_balance_element=False,
    )
    state, reason = await detectors.classify(page, Site.CSGOEMPIRE)
    assert state == SessionState.OFFLINE
    assert "balance element" in reason


@pytest.mark.asyncio
async def test_csgoempire_balance_element_is_the_only_check():
    page = FakePage(
        "https://unrelated.invalid/",
        "CAPTCHA login required Steam Guard",
        has_balance_element=True,
    )
    state, _ = await detectors.classify(
        page,
        Site.CSGOEMPIRE,
        expected_identity="identity-not-on-page",
    )
    assert state == SessionState.HEALTHY


@pytest.mark.asyncio
async def test_csgoempire_offline_when_balance_element_missing():
    """Missing currency-amount element -- classified OFFLINE (transient-retry
    path in checker.py), not a manual-intervention state, so a page that's
    merely still loading isn't immediately treated as a logout."""
    page = FakePage("https://csgoempire.com/deposit", "My Deposit", has_balance_element=False)
    state, reason = await detectors.classify(page, Site.CSGOEMPIRE)
    assert state == SessionState.OFFLINE
    assert "balance element" in reason


@pytest.mark.asyncio
async def test_csgoempire_balance_check_survives_closed_page():
    """A closed page/browser must not raise out of classification."""
    page = FakePage("https://csgoempire.com/deposit", "My Deposit", closed=True)
    found = await detectors.has_csgoempire_balance_element(page)
    assert found is False


@pytest.mark.asyncio
async def test_csgoempire_ignores_page_text_and_uses_only_balance_element():
    page = FakePage("https://csgoempire.com/", "Please complete the hCaptcha to continue", has_balance_element=False)
    state, _ = await detectors.classify(page, Site.CSGOEMPIRE)
    assert state == SessionState.OFFLINE
