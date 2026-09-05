# Security review

Performed as a dedicated pass after initial implementation, per the
project's own completion requirements. Findings are listed with status;
two real issues were found and fixed during this pass.

## Findings

### 1. FIXED — Webhook URL could leak into logs via exception text

`DiscordNotifier._post()` originally called `logger.exception(...)` in
its `httpx.HTTPError` handler. httpx exceptions frequently stringify the
full request URL, and a Discord webhook URL embeds a secret token in its
path (`.../webhooks/<id>/<token>`). Logging the raw exception would have
written that token into `logs/operations.log` or stdout on any network
failure — a real secret-leak path, and one the project's own logging
rules explicitly forbid.

**Fix:** replaced the exception logging with a redacted, host-only
message (scheme + netloc only, path/token stripped) and dropped the
`.exception()` call in favor of `.warning()` with a fixed, non-secret
message. Discord's own response body/status (logged separately) carries
no secret and was left as-is.

### 3. Reviewed, no change needed — credential/secret handling

- Account records (`app/accounts/models.py`, `store.py`) contain only
  name, URLs, and health-state fields — verified no field or code path
  writes passwords, cookies, tokens, or Steam Guard codes into the JSON
  files.
- `app/utils/logging_setup.op_log()` redacts any token-shaped string
  (32+ alphanumeric/`_`/`-` characters) as defense in depth, on top of
  callers only ever passing short state strings.
- The Discord webhook and bot token are read only from environment
  variables (`app/config.py`), never hard-coded, and `.env` is
  gitignored. `.env.example` contains placeholders only.
- No code path sends account credentials, cookies, or tokens to Discord;
  notification payloads are built from `SessionState`/reason strings and
  screenshots only.

### 4. Reviewed, no change needed — path traversal in account names

`app/accounts/models.validate_account_name()` restricts names to
`[A-Za-z0-9_-]{1,64}` and explicitly rejects `.`/`..`/separators.
`app/accounts/store._account_path()` additionally re-resolves the final
path and asserts it's still inside `ACCOUNTS_DIR` as defense in depth.
Covered by `tests/test_accounts.py::test_validate_account_name_rejects_unsafe_names`
and `tests/test_store.py::test_path_traversal_rejected`.

### 4. Reviewed, no change needed — no CAPTCHA/anti-bot evasion code exists

Confirmed by reading `app/health/detectors.py` and
`app/browser/manager.py` end to end: detection is text/URL matching only;
the only page interaction beyond navigation is a bounded, randomized
scroll (`light_activity`) explicitly gated to healthy sessions and
documented as anti-idle, not anti-detection. No proxy rotation,
fingerprint manipulation, or stealth plugins are present anywhere in the
codebase.

## Not fully addressed (documented, operator-owned)

- **Discord bot token scope**: if the operator enables `/status` via
  `DISCORD_BOT_TOKEN`, that token's blast radius depends on the bot's
  permissions in their server — outside this codebase's control. The
  installation doc should note using a minimal-permission bot (this has
  been added).
- **Host-level security** (OS patching, SSH hardening, firewall rules on
  a VPS) is out of scope for an application-level review and is the
  operator's responsibility per `docs/hosting.md`.
