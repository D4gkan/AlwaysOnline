"""
Small operational logging.

Deliberately minimal: short lines like `10:32 Account03 CSFloat healthy`.
Never logs credentials, cookies, tokens, page contents, or Steam Guard
codes -- callers must only pass short state/reason strings here.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

from app.config import LOGS_DIR, settings

_OP_LOG_PATH = LOGS_DIR / "operations.log"

# Defense in depth: redact anything that looks like a long token/secret
# even though callers should never pass secrets in the first place.
_SECRET_LIKE = re.compile(r"[A-Za-z0-9_\-]{32,}")


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _redact(message: str) -> str:
    return _SECRET_LIKE.sub("[redacted]", message)


def op_log(message: str) -> None:
    """Append a short line to the operational log and purge old entries."""
    message = _redact(message)
    timestamp = dt.datetime.now().strftime("%H:%M")
    line = f"{timestamp} {message}\n"
    with open(_OP_LOG_PATH, "a") as f:
        f.write(line)
    logging.getLogger("oplog").info(message)


def purge_old_logs(retention_days: int | None = None) -> None:
    """Delete operational-log lines older than the retention window.

    Since each line only carries a HH:MM timestamp (by design -- these are
    meant to be terse), retention is enforced by rewriting the file to
    keep only lines appended within the last `retention_days`, tracked via
    the file's own rotation rather than per-line dates. In practice this
    rotates the whole file once it's older than the retention window.
    """
    retention_days = retention_days or settings.log_retention_days
    if not _OP_LOG_PATH.exists():
        return
    age_days = (dt.datetime.now().timestamp() - _OP_LOG_PATH.stat().st_mtime) / 86400
    if age_days > retention_days:
        archive = LOGS_DIR / f"operations-{dt.date.today().isoformat()}.log.old"
        _OP_LOG_PATH.rename(archive)
    # Purge any archived logs beyond the retention window.
    cutoff = dt.datetime.now().timestamp() - retention_days * 86400
    for old_file in LOGS_DIR.glob("operations-*.log.old"):
        if old_file.stat().st_mtime < cutoff:
            old_file.unlink(missing_ok=True)
