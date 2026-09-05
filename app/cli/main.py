"""
Compact operator CLI.

Commands:
  launch account <name>       launch one account's two isolated Chrome windows and monitor it
  create account              interactively create an account record
    check status                print current account/site status
  request screenshots         capture screenshots from selected accounts/sites, send to Discord
  delete account <name>       stop browsers and remove the local account record after confirmation

Run `python -m app.cli.main --help` for full usage.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from app.accounts import store as account_store
from app.accounts.models import Account, AccountValidationError, SessionState, Site
from app.accounts.store import AccountAlreadyExistsError, AccountNotFoundError
from app.browser.manager import BrowserManager
from app.config import settings, SCREENSHOTS_DIR
from app.health import checker
from app.notify.discord import DiscordNotifier
from app.utils.logging_setup import configure_logging

console = Console()
app = typer.Typer(help="CS2 Session Monitor CLI", no_args_is_help=True)
account_app = typer.Typer(help="Account management")
app.add_typer(account_app, name="account")


# ---------------------------------------------------------------- create --

@account_app.command("create")
def create_account(
    name: str = typer.Option(..., prompt="Account name"),
    csfloat_url: str = typer.Option(settings.csfloat_default_url, prompt="CSFloat URL"),
    csgoempire_url: str = typer.Option(settings.csgoempire_default_url, prompt="CSGOEmpire URL"),
):
    """Interactively create an account record (no secrets requested or stored)."""
    try:
        account = account_store.create(name, csfloat_url, csgoempire_url)
    except (AccountAlreadyExistsError, AccountValidationError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Created account[/green] {account.name}")
    console.print(
        "Launch it with: [bold]python -m app.cli.main account launch "
        f"{account.name}[/bold], then log in manually in the two browser "
        "windows that open."
    )


# ---------------------------------------------------------------- launch --

@account_app.command("launch")
def launch_account(name: str):
    """Launch one account's two isolated Chrome windows and begin monitoring it."""
    try:
        account = account_store.load(name)
    except AccountNotFoundError:
        console.print(f"[red]No such account:[/red] {name}")
        raise typer.Exit(1)

    async def _run():
        manager = BrowserManager()
        notifier = DiscordNotifier()
        # Use launch sequence index if provided by GUI, otherwise fall back to account list position
        launch_seq_index = os.environ.get("LAUNCH_SEQUENCE_INDEX")
        if launch_seq_index is not None:
            try:
                idx = int(launch_seq_index)
            except ValueError:
                idx = account_store.list_names().index(name)
        else:
            idx = account_store.list_names().index(name)
        await manager.start()

        # Open both visible windows before either site's health check runs.
        # A failed navigation must not prevent the other site from opening.
        for site in (Site.CSFLOAT, Site.CSGOEMPIRE):
            try:
                await manager.get_or_create_session(account, site, idx)
            except Exception as exc:
                console.print(f"{site.value}: [red]could not open browser ({exc})[/red]")

        for site in (Site.CSFLOAT, Site.CSGOEMPIRE):
            try:
                # A saved pause is bookkeeping from an earlier failure, not
                # the current browser status. A freshly launched browser must
                # always be inspected so a valid session can recover.
                result = await checker.check_site(
                    manager,
                    account,
                    site,
                    idx,
                    check_while_paused=True,
                )
                account_store.save(account)
                console.print(f"{site.value}: [bold]{result.state.value}[/bold] ({result.reason})")
                if result.state not in {SessionState.HEALTHY, SessionState.PAUSED}:
                    await notifier.notify_state_change(account.name, site, result.state, result.reason, result.screenshot_path)
            except Exception as exc:
                console.print(f"{site.value}: [red]health check failed ({exc})[/red]")
        console.print(
            "\n[yellow]Two browser windows are now open for this account.[/yellow] "
            "If either shows a login/CAPTCHA/Steam Guard prompt, resolve it there manually.\n"
            "This session stays open until you close the console window or stop the process.\n"
            "You can also run the main monitor separately with:\n"
            "  [bold]python -m app.main[/bold]"
        )
        async def _listen_for_commands():
            while True:
                command = await asyncio.to_thread(sys.stdin.readline)
                if not command:
                    return
                if command.strip().lower() == "test":
                    sessions = list(manager._sessions.values())
                    for session in sessions:
                        await manager.light_activity(session)

        command_task = asyncio.create_task(_listen_for_commands())
        try:
            # Keep the persistent browser windows open for the operator and their manual login flow.
            while True:
                await asyncio.sleep(60)
        finally:
            command_task.cancel()

    asyncio.run(_run())


# ---------------------------------------------------------------- delete --

@account_app.command("delete")
def delete_account(name: str, yes: bool = typer.Option(False, "--yes", help="Skip confirmation")):
    """Stop that account's browsers and remove its local record."""
    try:
        account_store.load(name)
    except AccountNotFoundError:
        console.print(f"[red]No such account:[/red] {name}")
        raise typer.Exit(1)

    if not yes:
        confirm = typer.confirm(
            f"Delete account '{name}' and its local browser profiles? This does not touch the real "
            "CSFloat/CSGOEmpire accounts, only local monitor data."
        )
        if not confirm:
            console.print("Cancelled.")
            raise typer.Exit(0)

    account_store.delete(name, remove_browser_profiles=True)
    console.print(f"[green]Deleted[/green] {name}")


# ---------------------------------------------------------------- status --

@app.command("status")
def check_status():
    """Print the current account and site status."""
    accounts = account_store.list_all()
    table = Table(title="Session status")
    table.add_column("Account")
    table.add_column("Site")
    table.add_column("State")
    table.add_column("Last error")
    for account in accounts:
        for site in (Site.CSFLOAT, Site.CSGOEMPIRE):
            s = account.site_state(site)
            table.add_row(account.name, site.value, s.state, s.last_error or "")
    console.print(table)


# ------------------------------------------------------- request screenshots --

@app.command("request-screenshots")
def request_screenshots(
    account: Optional[str] = typer.Option(None, help="Limit to one account (default: all)"),
    site: Optional[str] = typer.Option(None, help="Limit to one site: csfloat|csgoempire"),
):
    """Capture screenshots from selected accounts/sites and send them to Discord."""
    accounts = [account_store.load(account)] if account else account_store.list_all()
    sites = [Site(site)] if site else [Site.CSFLOAT, Site.CSGOEMPIRE]

    async def _run():
        manager = BrowserManager()
        notifier = DiscordNotifier()
        await manager.start()
        names = account_store.list_names()
        for acc in accounts:
            idx = names.index(acc.name) if acc.name in names else 0
            for s in sites:
                try:
                    result = await checker.check_site(manager, acc, s, idx, take_screenshot_on_problem=True)
                    if result.screenshot_path is None:
                        # Force a screenshot even on a healthy page for an on-demand request.
                        session = await manager.get_or_create_session(acc, s, idx)
                        fname = f"{acc.name}-{s.value}-{int(time.time())}-ondemand.png"
                        result.screenshot_path = await manager.screenshot(session, SCREENSHOTS_DIR / fname)
                    console.print(f"{acc.name}/{s.value}: [bold]{result.state.value}[/bold] -> {result.screenshot_path}")
                    await notifier.send_embed(
                        f"SCREENSHOT: {acc.name} / {s.value}",
                        f"State: {result.state.value}",
                        screenshot=result.screenshot_path,
                    )
                except Exception as exc:
                    console.print(f"[red]Failed for {acc.name}/{s.value}: {exc}[/red]")
        await manager.stop()

    asyncio.run(_run())


def main():
    configure_logging()
    app()


if __name__ == "__main__":
    main()
