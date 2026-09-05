import pytest

from app.accounts.models import Site, SessionState
from app.health.checker import HealthResult
from app.notify.discord import DiscordNotifier
from app.scheduler import Scheduler


def make_result(account, site, state):
    return HealthResult(account_name=account, site=site, state=state, reason="test")


class RecordingNotifier(DiscordNotifier):
    def __init__(self):
        super().__init__(webhook_url="https://discord.test/webhook")
        self.outage_calls = 0
        self.recovery_calls = 0

    async def notify_global_outage(self):
        self.outage_calls += 1

    async def notify_global_recovery(self):
        self.recovery_calls += 1


@pytest.mark.asyncio
async def test_global_outage_detected_when_most_sites_down():
    scheduler = Scheduler(notifier=RecordingNotifier())
    results = [
        make_result("a1", Site.CSFLOAT, SessionState.PAGE_TIMEOUT),
        make_result("a1", Site.CSGOEMPIRE, SessionState.OFFLINE),
        make_result("a2", Site.CSFLOAT, SessionState.PAGE_TIMEOUT),
        make_result("a2", Site.CSGOEMPIRE, SessionState.HEALTHY),
    ]
    await scheduler._evaluate_global_outage(results)
    assert scheduler.state.in_global_outage is True
    assert scheduler.notifier.outage_calls == 1


@pytest.mark.asyncio
async def test_no_outage_when_failures_are_isolated():
    scheduler = Scheduler(notifier=RecordingNotifier())
    results = [
        make_result("a1", Site.CSFLOAT, SessionState.LOGIN_REQUIRED),
        make_result("a1", Site.CSGOEMPIRE, SessionState.HEALTHY),
        make_result("a2", Site.CSFLOAT, SessionState.HEALTHY),
        make_result("a2", Site.CSGOEMPIRE, SessionState.HEALTHY),
    ]
    await scheduler._evaluate_global_outage(results)
    assert scheduler.state.in_global_outage is False
    assert scheduler.notifier.outage_calls == 0


@pytest.mark.asyncio
async def test_recovery_alert_fires_once_after_outage_clears():
    scheduler = Scheduler(notifier=RecordingNotifier())
    outage_results = [make_result(f"a{i}", Site.CSFLOAT, SessionState.OFFLINE) for i in range(4)]
    await scheduler._evaluate_global_outage(outage_results)
    assert scheduler.state.in_global_outage is True

    healthy_results = [make_result(f"a{i}", Site.CSFLOAT, SessionState.HEALTHY) for i in range(4)]
    await scheduler._evaluate_global_outage(healthy_results)
    assert scheduler.state.in_global_outage is False
    assert scheduler.notifier.recovery_calls == 1
