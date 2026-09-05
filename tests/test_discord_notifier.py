import pytest

from app.accounts.models import SessionState, Site
from app.notify.discord import DiscordNotifier


class RecordingNotifier(DiscordNotifier):
    def __init__(self):
        super().__init__(webhook_url="https://discord.test/webhook")
        self.embeds = []

    async def send_embed(self, title, description, *, color, screenshot=None):
        self.embeds.append((title, description))


@pytest.mark.asyncio
async def test_paused_state_never_sends_session_lost_alert():
    notifier = RecordingNotifier()

    sent = await notifier.notify_state_change(
        "account",
        Site.CSGOEMPIRE,
        SessionState.PAUSED,
        "paused pending operator action",
    )

    assert sent is False
    assert notifier.embeds == []


@pytest.mark.asyncio
async def test_all_sessions_active_notification():
    notifier = RecordingNotifier()

    await notifier.notify_all_sessions_active(account_count=4, session_count=8)

    assert notifier.embeds == [
        ("ALL SESSIONS ACTIVE", "4 accounts active\n8/8 sessions healthy")
    ]
