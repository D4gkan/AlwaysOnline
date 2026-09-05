# Architecture

## Purpose and scope

This is a **health-monitoring and alerting system**, not a presence
simulator. It watches ordinary, persistent, visible browser sessions for
CSFloat and CSGOEmpire and tells a human operator when something needs
attention. It never attempts to bypass CAPTCHAs, spoof fingerprints,
rotate proxies/IPs, or fake human input beyond the minimal scroll activity
needed to avoid idle staleness.

## Components

```
app/
  accounts/      account data model + local JSON storage (no secrets)
  browser/       Playwright persistent-context session manager
  health/        page classification (login/CAPTCHA/2FA/challenge/identity) + check orchestration
  notify/        Discord webhook client + optional slash-command bot
  cli/           operator CLI (create/launch/delete accounts, status, screenshots)
  scheduler.py   the always-on loop tying the above together
  main.py        process entrypoint (scheduler + bot in one process)
```

### Accounts (`app/accounts/`)

An `Account` record holds only: a name, the two target URLs, and
per-site state (last state, last error, pause flag, screenshot path).
**No credentials, cookies, session tokens, or Steam Guard codes are ever
stored here** — those live entirely inside the browser profile directory,
which Playwright/Chrome manage as an ordinary user-data-dir. Deleting an
account removes its JSON record and its profile directories, nothing
more; it never touches the real CSFloat/CSGOEmpire account.

Storage is one JSON file per account under `accounts/<name>.json`, with
atomic writes and account-name validation that rejects path traversal.

### Browser session manager (`app/browser/manager.py`)

One Playwright driver owns two persistent `BrowserContext` objects per
account — one for CSFloat, one for CSGOEmpire — each with its own
`user_data_dir` under `browser_profiles/<account>/<site>/`. Contexts are
reused across health checks so cookies/session state persist naturally,
exactly as they would in a browser a person left open.

Window placement is derived deterministically from `(account_index,
site)` so windows never overlap, with a configurable width/height for
small displays.

The only "activity" beyond navigation is a small, randomized scroll
(`light_activity`) and a periodic full refresh (`refresh`) — both gated to
only run on already-healthy sessions, and both are about avoiding idle
timeouts, not simulating a human.

### Health detection (`app/health/`)

`detectors.py` classifies the *current* page into one of: healthy,
login-required, 2FA/Steam-Guard-required, CAPTCHA, challenge (e.g.
Cloudflare), identity-mismatch, or a generic transient failure — using
plain text/URL heuristics on the page a logged-in human would also see.
It never interacts with a CAPTCHA/challenge, only recognizes it.

`checker.py` orchestrates one check: navigate, classify, retry on
transient failure (`RETRY_ATTEMPTS`, `RETRY_BACKOFF_SEC`), capture a
screenshot only on a problem state, and persist the result into the
account's `SiteState`. States that clearly need a human (login/2FA/
CAPTCHA/session-expired/challenge/identity-mismatch) set `paused = True`
so the scheduler stops driving that site until the operator resolves it
in the visible browser window and it re-checks healthy.

### Notification (`app/notify/`)

`discord.py` posts to a single webhook URL loaded only from the
environment. It **deduplicates by (account, site) state** — it alerts
once when a problem starts and once when it resolves, never repeatedly
for an unresolved issue. `discord_bot.py` is an optional slash-command
bot (`/status`) that reads the same on-disk account state; it only starts
if `DISCORD_BOT_TOKEN` is set.

### Scheduler (`app/scheduler.py`)

The main loop: for every (account, site), run a health check (or a
lightweight re-check if paused), persist state, fire alerts on state
changes, and run light-activity/refresh on healthy sessions on their own
independent timers. It also aggregates the sweep's results to detect a
**global outage**: if a large fraction of sites fail with
connectivity-shaped errors in the same sweep, it sends *one* outage alert
instead of one per account, and *one* recovery alert once things clear.
One account's failure never stops others from being checked.

### CLI (`app/cli/main.py`)

The operator-facing entrypoint for one-off actions: `account create`,
`account launch <name>` (opens the two windows for manual first login),
`account delete <name>`, `status`, and `request-screenshots`. The
always-on process (`app/main.py`) is separate and meant to run under a
process supervisor.

## Data flow (one sweep)

```
scheduler.sweep_once()
  for account in accounts:
    for site in (csfloat, csgoempire):
      checker.check_site()          -> navigate + classify + retry
        browser.manager              -> reuse/open persistent context
        health.detectors             -> classify page
      account_store.save()          -> persist new SiteState
      if state changed:
        notifier.notify_state_change() -> dedup'd Discord alert
      if healthy:
        light_activity / refresh on their own timers
  scheduler._evaluate_global_outage() -> one alert, not N
```

## Failure isolation

- One account/site failing never blocks others in the same sweep — each
  check is independent and wrapped so unexpected exceptions are logged
  and turned into an `OFFLINE` state rather than propagating.
- The self-healing order (verify → retry → refresh → reopen tab → restart
  browser context → re-verify → alert) prefers preserving the existing
  authenticated profile at every step; nothing deletes a profile
  automatically.
- Crash recovery at the process level is handled by the OS service
  manager (systemd on Linux, described in `scripts/`), not by the
  application trying to supervise itself.

## Scaling from 5 to 20+ accounts

Nothing in the design assumes a fixed account count: `account_index` is
derived from the sorted account list at runtime, window geometry wraps
across a grid, and the scheduler loops over however many accounts exist
on disk. The practical scaling constraint is host RAM (see
`docs/hosting.md`), not the code.
