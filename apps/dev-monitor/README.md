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

### Failure behaviour

Nothing here is allowed to take observability down with it. A half-set gate, a corrupt or
locked database, an unwritable state directory: each is logged with its reason, the owner
routes return 404, and the monitor keeps serving. `messages` in the startup banner and in
`GET /monitor/api/health` reports what actually started, not what the config asked for, so
a half-configured install is visible to a script and not only in the boot log.

### Tests

```
python3 backend/test_devmon.py     # 135 offline checks, no install required
```

Covers validation, dedup, coalescing, crash recovery, urgency promotion, read≠notified,
sweep, flood detection, the approval/run state machine and the Slack outbox.
