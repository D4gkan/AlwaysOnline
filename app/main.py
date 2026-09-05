"""
Main always-on process.

Runs three things concurrently in one process:
  - the monitoring scheduler (health checks, activity, refresh, alerts)
  - the optional Discord bot for `/status` (only if DISCORD_BOT_TOKEN set)

Intended to be run under a process supervisor (systemd on Linux, or
start.bat on Windows) so it restarts automatically on crash.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import threading

from app.config import settings
from app.scheduler import Scheduler
from app.utils.logging_setup import configure_logging, op_log, purge_old_logs

logger = logging.getLogger("main")


def _maybe_run_bot_in_thread():
    if not settings.discord_bot_token:
        return None
    from app.notify.discord_bot import run_bot

    thread = threading.Thread(target=run_bot, daemon=True, name="discord-bot")
    thread.start()
    return thread


async def _run_periodic_log_purge():
    while True:
        purge_old_logs()
        await asyncio.sleep(3600)


async def async_main():
    configure_logging()
    op_log("System starting")

    scheduler = Scheduler()

    _maybe_run_bot_in_thread()

    purge_task = asyncio.create_task(_run_periodic_log_purge())

    stop_event = asyncio.Event()

    def _handle_signal(*_args):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for all signals.
            pass

    monitor_task = asyncio.create_task(scheduler.run_forever())

    await stop_event.wait()
    op_log("System shutting down")
    purge_task.cancel()
    await scheduler.stop()
    monitor_task.cancel()


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
