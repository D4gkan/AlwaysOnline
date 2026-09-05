"""
Discord notifications.

- Sends alerts through a single webhook URL (never hard-coded, never logged).
- Deduplicates: it will not spam the same unresolved problem repeatedly --
  it alerts once on a state change into a problem, and once on recovery.
- Never includes credentials, cookies, tokens, or Steam Guard codes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

from app.accounts.models import SessionState, Site
from app.config import settings

logger = logging.getLogger("notify.discord")

_STATE_LABELS = {
    SessionState.LOGIN_REQUIRED: "Login required",
    SessionState.TWO_FACTOR_REQUIRED: "Steam Guard / 2FA required",
    SessionState.CAPTCHA: "CAPTCHA detected",
    SessionState.SESSION_EXPIRED: "Session expired",
    SessionState.CHALLENGE: "Cloudflare / security challenge",
    SessionState.IDENTITY_MISMATCH: "Account identity mismatch",
    SessionState.BROWSER_CRASH: "Browser crash / context failure",
    SessionState.PAGE_TIMEOUT: "Page timeout / site unavailable",
    SessionState.OFFLINE: "Account offline",
}

_COLOR_PROBLEM = 0xE74C3C
_COLOR_RECOVERY = 0x2ECC71
_COLOR_INFO = 0x3498DB


class DiscordNotifier:
    def __init__(self, webhook_url: Optional[str] = None) -> None:
        self.webhook_url = webhook_url or settings.discord_webhook_url
        # Tracks the last *alerted* state per (account, site) so we only
        # notify again when something actually changes.
        self._last_alerted_state: dict[tuple[str, str], str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def _safe_url_for_logs(self) -> str:
        """Never let the webhook URL (which embeds a secret token in its
        path) reach logs, even via an exception's string representation."""
        if not self.webhook_url:
            return "(unset)"
        # Keep only the host, drop path/query where the secret token lives.
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.webhook_url)
            return f"{parsed.scheme}://{parsed.netloc}/[redacted]"
        except Exception:
            return "(redacted)"

    async def _post(self, payload: dict, file_path: Optional[Path] = None) -> None:
        if not self.enabled:
            logger.warning("DISCORD_WEBHOOK_URL not set; skipping notification: %s", payload.get("content", ""))
            return
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                if file_path and file_path.exists():
                    import json as _json
                    with open(file_path, "rb") as f:
                        files = {"file": (file_path.name, f, "image/png")}
                        resp = await client.post(
                            self.webhook_url,
                            data={"payload_json": _json.dumps(payload)},
                            files=files,
                        )
                else:
                    resp = await client.post(self.webhook_url, json=payload)
                if resp.status_code >= 300:
                    # Discord's own response text/status carries no secret,
                    # unlike the request URL, so this is safe to log as-is.
                    logger.warning("Discord webhook returned %s: %s", resp.status_code, resp.text[:300])
            except httpx.HTTPError:
                # Do NOT use logger.exception() here: httpx exceptions often
                # stringify the full request URL, which for a Discord
                # webhook contains a secret token in its path. Log a safe,
                # redacted message instead.
                logger.warning(
                    "Failed to send Discord notification to %s (exception type: %s)",
                    self._safe_url_for_logs(),
                    "HTTPError",
                )

    async def send_text(self, content: str) -> None:
        await self._post({"content": content})

    async def send_embed(
        self, title: str, description: str, *, color: int = _COLOR_INFO, screenshot: Optional[Path] = None
    ) -> None:
        embed = {"title": title, "description": description, "color": color}
        payload = {"embeds": [embed]}
        if screenshot and screenshot.exists():
            embed["image"] = {"url": f"attachment://{screenshot.name}"}
        await self._post(payload, file_path=screenshot)

    async def notify_startup(self, account_count: int, session_count: int, healthy_count: int) -> None:
        await self.send_embed(
            "SYSTEM ONLINE",
            f"{account_count} accounts monitored\n{session_count} sessions being checked\n{healthy_count}/{session_count} healthy",
            color=_COLOR_INFO,
        )

    async def notify_all_sessions_active(self, account_count: int, session_count: int) -> None:
        await self.send_embed(
            "ALL SESSIONS ACTIVE",
            f"{account_count} accounts active\n{session_count}/{session_count} sessions healthy",
            color=_COLOR_RECOVERY,
        )

    async def notify_state_change(
        self,
        account_name: str,
        site: Site,
        state: SessionState,
        reason: str,
        screenshot: Optional[Path] = None,
    ) -> bool:
        """Send an alert only if this state differs from the last alerted state
        for this (account, site). Returns True if a notification was sent."""
        # PAUSED is an internal bookkeeping state, not evidence that a live
        # browser session was lost. Never expose it as a Discord incident.
        if state == SessionState.PAUSED:
            logger.debug("Skipping Discord state alert for internal paused state: %s/%s", account_name, site.value)
            return False

        key = (account_name, site.value)
        if self._last_alerted_state.get(key) == state.value:
            return False  # unresolved issue already alerted; don't spam
        self._last_alerted_state[key] = state.value

        if state == SessionState.HEALTHY:
            await self.send_embed(
                "SESSION RECOVERED",
                f"Account: {account_name}\nPlatform: {site.value}\nStatus: Online",
                color=_COLOR_RECOVERY,
            )
        else:
            label = _STATE_LABELS.get(state, state.value)
            await self.send_embed(
                "SESSION LOST",
                f"Account: {account_name}\nPlatform: {site.value}\nReason: {label}"
                + ("\nScreenshot attached" if screenshot else ""),
                color=_COLOR_PROBLEM,
                screenshot=screenshot,
            )
        return True

    async def notify_global_outage(self) -> None:
        key = ("__global__", "network")
        if self._last_alerted_state.get(key) == "outage":
            return
        self._last_alerted_state[key] = "outage"
        await self.send_embed(
            "NETWORK OUTAGE",
            "Internet connectivity appears down. Multiple accounts failed simultaneously. Retrying in background.",
            color=_COLOR_PROBLEM,
        )

    async def notify_global_recovery(self) -> None:
        key = ("__global__", "network")
        if self._last_alerted_state.get(key) != "outage":
            return
        self._last_alerted_state[key] = "recovered"
        await self.send_embed(
            "NETWORK RECOVERED",
            "Connectivity restored. All profiles re-verified.",
            color=_COLOR_RECOVERY,
        )

    async def send_status_summary(self, summary_text: str) -> None:
        await self.send_embed("STATUS", summary_text, color=_COLOR_INFO)
