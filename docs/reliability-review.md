# Reliability review

Performed as a dedicated pass after initial implementation. One real bug
was found and fixed; the rest of this document records what was verified
and why the design holds up under partial failure.

## Findings

### 1. FIXED — Manual-intervention states were retried like transient failures

`checker.check_site()` originally retried *every* non-healthy result up
to `RETRY_ATTEMPTS` times with backoff, including CAPTCHA, login-required,
2FA-required, session-expired, challenge, and identity-mismatch. Those
states are not transient — re-navigating to a CAPTCHA page repeatedly
before alerting wastes the retry budget, delays the operator's alert, and
in the CAPTCHA case specifically risks re-triggering the challenge
needlessly.

**Fix:** the retry loop now breaks immediately when the classified state
is in `MANUAL_INTERVENTION_STATES`, escalating to a screenshot + Discord
alert on the first observation. Retries are still used for genuinely
transient signals (`UNKNOWN`/generic offline, timeouts, browser crashes).
Covered by `tests/test_checker_retry.py`
(`test_manual_intervention_state_does_not_retry` asserts exactly one
navigation attempt; `test_transient_failure_is_retried` asserts the full
retry budget is still used for non-manual-intervention failures).

## Reviewed, no change needed

### 2. Failure isolation across accounts

`Scheduler.sweep_once()` iterates accounts/sites in a plain loop, and
`checker.check_site()` wraps its own body in a broad `except Exception`
that converts any unexpected error into an `OFFLINE` state rather than
propagating. Verified: an exception raised while checking one
account/site cannot abort the sweep for the rest — each iteration's
failure is fully contained before the loop continues. `Scheduler.sweep_once`
itself is also wrapped by `run_forever`'s own try/except, so a bug outside
`check_site` (e.g. in notification code) logs and waits for the next
timer tick rather than crashing the process.

### 3. Global outage vs. per-account alert flooding

Verified via `tests/test_scheduler_outage.py`: a sweep where most sites
fail with connectivity-shaped states produces exactly one outage alert
(`notify_global_outage`), not one per account, and clears with exactly
one recovery alert once results return to healthy. The threshold
(`_OUTAGE_MIN_SITES = 3`, `_OUTAGE_FRACTION_THRESHOLD = 0.6`) avoids
misclassifying a couple of unrelated single-account logouts as a network
outage.

### 4. Alert deduplication

`DiscordNotifier.notify_state_change()` tracks the last *alerted* state
per (account, site) and only sends again when that state changes —
verified by reading the dedup logic directly: an unresolved CAPTCHA that
persists across many sweeps produces exactly one "SESSION LOST" message,
not one per sweep, and exactly one "SESSION RECOVERED" when it clears.

### 5. Profile preservation during recovery

`BrowserManager` never deletes a `user_data_dir`; `get_or_create_session`
reuses an existing context when the underlying browser process is still
alive and only replaces the session object (not the profile directory)
when the context has actually died. `account_store.delete()` is the only
code path that removes a profile directory, and it only runs from the
explicit, confirmation-gated CLI `account delete` command — never from
any automatic recovery path. This matches the requirement that
self-healing must never destroy a valid authenticated profile.

### 6. Escalation ordering matches the spec

Traced the actual call path against the required order (verify → retry →
refresh → reopen tab → restart browser context → re-verify → alert):
`check_site` verifies and retries; `get_or_create_session` transparently
reopens a dead context (equivalent to "restart browser context") on the
next call rather than requiring a separate step; a fresh `navigate()` on
that new context is the "re-verify"; and `Scheduler.sweep_once` sends the
alert only after all of that has run and the state is still unhealthy.
No step in this path deletes profile data.

### 7. Paused accounts auto-resume without stuck state

`Scheduler.sweep_once()` calls `checker.try_resume_if_recovered()` for
any paused (account, site) on every sweep, which re-checks without
consuming the "changed" screenshot/alert machinery unless it actually
recovers. Verified there's no code path that leaves a site permanently
paused with no further checks — every sweep re-evaluates it.

### 8. Process-level crash recovery

The application does not attempt to supervise itself; `scripts/cs2-session-monitor.service`
sets `Restart=always` / `RestartSec=5` so systemd restarts the whole
process on any crash, and `app/main.py`'s `startup()` re-verifies every
account/site from scratch on each start rather than trusting stale
in-memory state. This is the correct boundary — a monitoring tool trying
to restart itself after a fatal crash is a common source of zombie/
double-run bugs, so that responsibility is left to the OS service
manager as the spec requested.

## Known limitations (by design, documented rather than silently accepted)

- Health detection is heuristic (text/URL matching). Site markup changes
  could produce a false "healthy" or a false alert; `docs/architecture.md`
  flags this and asks future maintainers to keep the signal lists small
  and easy to update rather than over-fitting to current markup.
- The `/status` slash command and webhook alerts are independent paths
  reading the same on-disk state; if the disk write from a sweep and a
  `/status` call race, the command may show a result up to one sweep
  interval stale. This is an acceptable staleness window for a 5-minute
  default cadence and is not treated as a bug.
