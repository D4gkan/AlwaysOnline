import dataclasses

import pytest

from app.accounts.models import Account, Site, SessionState
from app.health import checker


def _with_retries(attempts: int, backoff: int = 0):
    return dataclasses.replace(checker.settings, retry_attempts=attempts, retry_backoff_sec=backoff)


class FakeSession:
    def __init__(self):
        self.page = object()


class FakeManager:
    """Minimal stand-in for BrowserManager that counts navigate() calls
    and returns a scripted sequence of classifier results."""

    def __init__(self):
        self.navigate_calls = 0
        self.screenshot_calls = 0

    async def get_or_create_session(self, account, site, account_index):
        return FakeSession()

    async def navigate(self, session, url, timeout_ms=30_000):
        self.navigate_calls += 1

    async def screenshot(self, session, path):
        self.screenshot_calls += 1
        return path


@pytest.mark.asyncio
async def test_manual_intervention_state_does_not_retry(monkeypatch):
    """A CAPTCHA/login-shaped result should escalate on the first attempt,
    not be retried like a transient failure."""
    account = Account.new("acc1")
    manager = FakeManager()

    async def fake_classify(page, site, expected_identity=None):
        return SessionState.CAPTCHA, "captcha shown"

    monkeypatch.setattr(checker.detectors, "classify", fake_classify)
    monkeypatch.setattr(checker, "settings", _with_retries(3))

    result = await checker.check_site(manager, account, Site.CSFLOAT, 0, take_screenshot_on_problem=False)

    assert result.state == SessionState.CAPTCHA
    assert manager.navigate_calls == 1  # no retries for a manual-intervention state


@pytest.mark.asyncio
async def test_transient_failure_is_retried(monkeypatch):
    """A generic/offline-shaped result should still use the retry budget."""
    account = Account.new("acc2")
    manager = FakeManager()

    async def fake_classify(page, site, expected_identity=None):
        return SessionState.UNKNOWN, "weird page"

    monkeypatch.setattr(checker.detectors, "classify", fake_classify)
    monkeypatch.setattr(checker, "settings", _with_retries(3))

    result = await checker.check_site(manager, account, Site.CSFLOAT, 0, take_screenshot_on_problem=False)

    assert manager.navigate_calls == 3  # retried the full budget for a non-manual-intervention state


@pytest.mark.asyncio
async def test_healthy_stops_immediately(monkeypatch):
    account = Account.new("acc3")
    manager = FakeManager()

    async def fake_classify(page, site, expected_identity=None):
        return SessionState.HEALTHY, "ok"

    monkeypatch.setattr(checker.detectors, "classify", fake_classify)
    monkeypatch.setattr(checker, "settings", _with_retries(3))

    result = await checker.check_site(manager, account, Site.CSFLOAT, 0, take_screenshot_on_problem=False)

    assert result.state == SessionState.HEALTHY
    assert manager.navigate_calls == 1


@pytest.mark.asyncio
async def test_paused_site_is_actually_rechecked_and_resumed(monkeypatch):
    account = Account.new("acc4")
    account.csgoempire_state.paused = True
    account.csgoempire_state.state = SessionState.LOGIN_REQUIRED.value
    manager = FakeManager()

    async def fake_classify(page, site, expected_identity=None):
        return SessionState.HEALTHY, "authenticated marker found"

    monkeypatch.setattr(checker.detectors, "classify", fake_classify)

    result = await checker.try_resume_if_recovered(manager, account, Site.CSGOEMPIRE, 0)

    assert result is not None
    assert result.state == SessionState.HEALTHY
    assert result.changed is True
    assert manager.navigate_calls == 1
    assert account.csgoempire_state.paused is False
