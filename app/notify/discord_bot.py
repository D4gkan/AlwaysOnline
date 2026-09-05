"""
Discord bot providing the `/status` slash command (and optional extras).

This runs as a separate optional process/task from the webhook notifier --
webhooks are one-way (outbound alerts), while a slash command needs a bot
token with the `applications.commands` scope. Both read the same
account-store state, so `/status` always reflects the latest sweep.

Requires DISCORD_BOT_TOKEN to be set; if absent, the bot simply doesn't
start (webhook alerts still work fine without it).
"""
from __future__ import annotations

import logging

from app.accounts import store as account_store
from app.accounts.models import Site
from app.config import settings

logger = logging.getLogger("notify.discord_bot")


def build_status_summary() -> str:
    accounts = account_store.list_all()
    total = 0
    healthy = 0
    problems = []
    for account in accounts:
        for site in (Site.CSFLOAT, Site.CSGOEMPIRE):
            s = account.site_state(site)
            total += 1
            if s.state == "healthy":
                healthy += 1
            else:
                label = s.state.replace("_", " ")
                problems.append(f"{account.name} — {site.value} {label}")

    lines = [f"{len(accounts)} accounts monitored", f"{healthy}/{total} sessions healthy"]
    if problems:
        lines.append(f"{len(problems)} needs attention:")
        lines.extend(f"  {p}" for p in problems[:10])
    return "\n".join(lines)


def create_bot():
    """Build the discord.py bot with a `/status` slash command.

    Imported lazily so `discord.py` is only required when the bot is
    actually used.
    """
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @tree.command(name="status", description="Show current CS2 session monitor health summary")
    async def status_command(interaction: "discord.Interaction"):
        summary = build_status_summary()
        await interaction.response.send_message(f"```{summary}```")

    @client.event
    async def on_ready():
        guild_id = settings.discord_guild_id
        if guild_id:
            await tree.sync(guild=discord.Object(id=int(guild_id)))
        else:
            await tree.sync()
        logger.info("Discord bot ready as %s", client.user)

    return client


def run_bot() -> None:
    if not settings.discord_bot_token:
        logger.info("DISCORD_BOT_TOKEN not set; skipping slash-command bot (webhook alerts still active).")
        return
    client = create_bot()
    client.run(settings.discord_bot_token)
