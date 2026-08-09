# dev-monitor

Per-box observability — CPU, memory, services, network, storage, top processes and recent
unit logs — served as a same-origin subpath under the hub at `/monitor/`. No agent, no
`psutil`: the backend reads `/proc` and shells out to `systemctl`/`journalctl`, so it runs
in a minimal container. Observability is visible to the owner and collaborators.

Optionally it also carries an **owner-only message and action console** (`messages = true`,
default off). That half is described below; if you leave it off, everything below is inert.

## The message and action console

The problem it solves: an agent, a cron job or a build finishes something on the box and
you find out when you next happen to look. The console gives those producers one place to
say so, and gives you one place to act on it from a phone.

Two axes, deliberately separated:

- **Messages.** A producer drops a JSON file in a spool. It becomes a *card*. Cards
  coalesce by `group_key` inside a 24h window, so a job that fails hourly is one card with
  a count, not twenty-four notifications. Urgent cards are also delivered to Slack if a
  webhook is configured.
- **Actions.** A card may carry a `recommended_action` — a working directory plus either a
  skill name, a prompt, or an argv list. It does nothing until you approve it. Approving
  derives a canonical plan and hashes it; executing runs that plan in a tmux window you can
  then watch from devterm.

### The storage split (why there are two tables)

An **occurrence** is an immutable ledger row: this event arrived, at this time, with this
payload. A **card** is a mutable projection: read/unread, pinned, archived, dismissed, with
a count of the occurrences behind it. Producers only ever append occurrences; the console
only ever mutates cards. Every state transition happens inside a `BEGIN IMMEDIATE`
transaction with a conditional `UPDATE` plus an audit row, so two clicks racing each other
cannot both win.

### The spool

Maildir-style, at `~/.local/state/airlock/dev-monitor/spool`:

```
spool/tmp/          write here first
spool/new/          hard-link (or rename) here when the file is complete
spool/processing/   the watcher's working area
spool/bad/          rejected payloads, kept for inspection
```

Writing to `tmp/` and only then linking into `new/` is what makes a partially written file
impossible to ingest. See `examples/emit_message.py` for a producer you can copy.

Anything that can write the spool can post a card — treat that as equivalent to console
access. It is *not* equivalent to execution: see [SECURITY.md](../../SECURITY.md).

### Configuration

```toml
[apps.dev-monitor]
backend_port = 18804
messages     = true
# slack_webhook_env = "AIRLOCK_DEVMON_SLACK_WEBHOOK"   # NAME of the env var, not the URL
# exec_cwd_root     = ""                                # empty = $HOME
# exec_session      = "devmon-exec"
# skill_allow       = ""                                # filters the `skill` field only
```

The installer creates the spool and database (`0700`), mints a fresh nginx→backend proxy
secret on every real install (a dry run reuses the deployed one and never rewrites an
existing fragment), and writes `~/.config/airlock/dev-monitor.env` (`0600`). Turning
`messages` back off removes that env file, so the console cannot come back on a restart.

The Slack webhook is a bearer capability to post in a channel, so — like every other secret
in Airlock — it is *named*, not stored: `slack_webhook_env` holds the name of an
environment variable, and the installer reads the value from there at install time. With
it unset, cards and the feed work exactly the same; only Slack delivery is off.

Approved actions run in tmux, so the *action* half needs `tmux` — and only that half.
Without it cards, coalescing, Slack and the whole feed work normally, and an approval is
refused immediately with a line in the journal instead of leaving a card that looks like it
is running. It is deliberately not an install prerequisite (that would fail the install of
a monitor whose console is off); the installer and `smoke.sh` both warn instead.

## Credential freshness (`token_freshness = true`, default off)

Nothing on a dev box reads a credential's expiry until something fails. Claude Code
refreshes its OAuth token *reactively*, after an HTTP 401/403; paseo's plan panel caches
for five minutes and re-asks nobody; and no timer anywhere looks at `expiresAt`. So the
first sign that a token died is a job that did not run.

Two halves, both off unless you turn them on, and deliberately switched on separately:

| | what it is | how it is turned on |
|---|---|---|
| the card | `GET /monitor/api/tokens` + a **Credentials** panel on the dashboard | `token_freshness = true` |
| the check | `airlock-token-freshness.timer` (a `--user` timer) | `bash install-token-timer.sh` |

The config key makes the verdict *visible*; the timer makes it *happen*. A standing job on
the operator's box is not something a config default should start, so the installer says so
once instead of doing it.

```toml
[apps.dev-monitor]
token_freshness             = true
# token_freshness_warn_hours  = 24   # claude: warn this long before the refresh deadline
# token_freshness_stale_hours = 24   # codex: warn once last_refresh is this old
```

```
bash apps/dev-monitor/install-token-timer.sh [--oncalendar 'daily'] [--no-messages]
bash apps/dev-monitor/install-token-timer.sh --uninstall
```

**Four verdicts, and `unknown` is not `ok`.** `ok` / `expiring-soon` / `expired` /
`unknown`. A missing or unparseable credentials file is `unknown` and renders as a warning
— a checker that scores an absent file green is worse than no checker.

**Which field is the deadline.** For Claude the access token in `expiresAt` turns over by
itself every few hours, so on its own it is noise; what needs a human is
`refreshTokenExpiresAt`, and that drives the verdict when it is present. Codex's
`auth.json` has no expiry field at all — `tokens.last_refresh` is the only field that
proves the session is still alive, so the codex verdict is an *age* verdict and never
claims `expired`, because staleness cannot prove death.

**It never reads, logs or publishes a token value** — only field presence and timestamps.
`test-backend.py` asserts that against a fixture whose token values are a sentinel string.

**Where the warning goes.** Into the message console that already exists: a run publishes
one `info` card per unhealthy provider to the spool, and the collector's 24-hour coalescing
makes that one card per provider per day whatever the schedule. So this half wants
`messages = true`; without it the timer still writes its snapshot and the dashboard card
still shows the verdict, but nothing pushes — and `install-token-timer.sh` refuses to wire
a timer whose loud channel is absent unless you pass `--no-messages` and mean it.

**A dead checker is visible as staleness, not silence.** Every run writes
`~/.local/state/airlock/dev-monitor/token-freshness.json` whatever the verdict, and the
card shows how old it is (`never`, if the timer has not been wired). The unit also carries
`OnFailure=airlock-token-freshness-failed.service`, which leaves evidence on the box and
posts an urgent card — because a watchdog that dies quietly leaves the card showing its
last verdict, and the last verdict was green.

### Failure behaviour

Nothing here is allowed to take observability down with it. A half-set gate, a corrupt or
locked database, an unwritable state directory: each is logged with its reason, the owner
routes return 404, and the monitor keeps serving. `messages` in the startup banner and in
`GET /monitor/api/health` reports what actually started, not what the config asked for, so
a half-configured install is visible to a script and not only in the boot log.

### Tests

```
python3 backend/test_devmon.py                     # 141 offline checks, no install required
python3 test-backend.py                            # the backend's own half, incl. credential freshness
bash ../../install/test-token-freshness-timer.sh   # the timer templates, substitution and installer refusals
```

Covers validation, dedup, coalescing, crash recovery, urgency promotion, read≠notified,
sweep, flood detection, the approval/run state machine and the Slack outbox.
