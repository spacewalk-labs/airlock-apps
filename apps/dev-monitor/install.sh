#!/usr/bin/env bash
# dev-monitor — per-box system/service/network/storage observability, served as a
# same-origin subpath under the hub (owner + collaborators), plus an OPTIONAL
# owner-only message/action console (messages = true; default off).
#
#   browser --> hub (tailscale serve) --(identity)--> hub nginx
#     /monitor/        -> dashboard UI (static, from the hub webroot)
#     /monitor/api/    -> airlock-dev-monitor backend 127.0.0.1:BACKEND (loopback)
#
# The backend binds loopback and strips the /monitor/ prefix itself. Config from
# airlock.toml ([apps.dev-monitor]). Honors AIRLOCK_DRY_RUN=1.
set -euo pipefail

# ABI (D5): prefer the orchestrator-supplied AIRLOCK_ROOT/AIRLOCK_APP_DIR/
# AIRLOCK_APP_ID, falling back to $0-relative computation for a standalone
# invocation (a test harness that runs this script directly).
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${AIRLOCK_ROOT:-$(cd "$HERE/../.." && pwd)}"
HERE="${AIRLOCK_APP_DIR:-$HERE}"
AIRLOCK_APP_ID="${AIRLOCK_APP_ID:-dev-monitor}"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"
# shellcheck source=/dev/null
. "$HERE/render.sh"

require_cmd python3 systemctl journalctl

airlock_load dev-monitor
BACKEND_PORT="${AIRLOCK_DEV_MONITOR_BACKEND_PORT:?}"
MESSAGES="${AIRLOCK_DEV_MONITOR_MESSAGES:-false}"
SLACK_WEBHOOK_ENV="${AIRLOCK_DEV_MONITOR_SLACK_WEBHOOK_ENV:-}"
EXEC_CWD_ROOT="${AIRLOCK_DEV_MONITOR_EXEC_CWD_ROOT:-}"
EXEC_SESSION="${AIRLOCK_DEV_MONITOR_EXEC_SESSION:-devmon-exec}"
SKILL_ALLOW="${AIRLOCK_DEV_MONITOR_SKILL_ALLOW:-}"
CONFD="${AIRLOCK_CONFD:-/etc/airlock/nginx}"
WEBROOT="${AIRLOCK_WEBROOT:-/opt/airlock/hub}"
IDENTITY_HEADER="${AIRLOCK_IDENTITY_HEADER:?}"
# This value is interpolated into an nginx variable name below. airlock-config derives it
# from a fixed provider map so it is always well formed, but this script can be run
# standalone with the env var set — and a value carrying whitespace or a brace would either
# break the hub config (reload fails, whole hub down) or inject directives.
case "$IDENTITY_HEADER" in
  *[!A-Za-z0-9-]*|'') die "AIRLOCK_IDENTITY_HEADER must be a bare HTTP header name (letters, digits, '-'): got '$IDENTITY_HEADER'" ;;
esac
# Same reasoning one level down: these three end up as lines in a systemd EnvironmentFile,
# where a newline would inject additional environment entries.
for _v in "$EXEC_CWD_ROOT" "$EXEC_SESSION" "$SKILL_ALLOW" "$SLACK_WEBHOOK_ENV"; do
  case "$_v" in *[$'\n\r']*) die "config values must not contain newlines" ;; esac
done
OWNER="${AIRLOCK_OWNER:?}"
UNIT_DIR="$HOME/.config/systemd/user"
DEVMON_STATE="$HOME/.local/state/airlock/dev-monitor"
DEVMON_ENV="$HOME/.config/airlock/dev-monitor.env"
# AIRLOCK_RENDER_DIR: harness-only destination-root override (highest
# priority). Redirects only where render output lands — install/lib.sh
# fail-closes if this is set without AIRLOCK_DRY_RUN=1, since real system
# mutations (systemctl, sudo tailscale serve, and orca's own sudo nft/
# systemctl calls) are gated on dry-run alone, not on this variable.
if [ -n "${AIRLOCK_RENDER_DIR:-}" ]; then
  CONFD="$AIRLOCK_RENDER_DIR/confd"
  UNIT_DIR="$AIRLOCK_RENDER_DIR/units"
fi

# The unread badge (hub/assets/airlock-return.js) polls owner/messages/preview
# cross-origin from the separate-port tools (devterm/code-server/orca/paseo — same box,
# different ports). That path matches the OWNER location in the fragment below, not the
# general one, because nginx picks the longest matching prefix. So the echo has to come
# from the backend — which is also the only place that knows this particular route is
# the badge's rather than the owner's data. All we do here is name the hosts that count
# as this box; everything else the backend serves stays same-origin only.
#
# With no measurable FQDN we pass nothing: the backend still recognises its own hostname,
# so a short-name origin keeps working and the badge degrades instead of breaking.
FQDN="${AIRLOCK_TS_FQDN:-}"
# Two statements, not `$(... || true)`: ts_fqdn ends in `die`, and an `exit` inside a
# command substitution kills the substitution before `|| true` can run. Same trap
# install/render-nginx.sh documents.
[ -n "$FQDN" ] || FQDN="$(ts_fqdn 2>/dev/null)" || FQDN=""
cors_hosts=""
if [ -n "$FQDN" ]; then
  cors_hosts="${FQDN},${FQDN%%.*}"
else
  log "WARN: tailnet FQDN unresolved — the unread badge is reachable only from a short-name origin"
fi

# --- 0. message/action console state (only when messages = true) ---
# Four env vars are all-or-nothing (devmon_owner fails closed on a partial set), so
# they are written as one file and the file is REMOVED when the feature is off —
# leaving a stale env behind would quietly re-enable the console on the next restart.
#
# The proxy secret is what proves a request came through nginx rather than straight to
# the loopback port. A real install rotates it: nginx and the unit are rewritten in the
# same run, so rotation costs nothing and bounds the lifetime of a value that leaked from
# an old config.
#
# A DRY RUN must not rotate it, so it reuses the deployed secret when it can read one.
# That alone is not enough — an unreadable env file leaves nothing to reuse — which is why
# the fragment write further down also refuses to overwrite an existing file on a dry run.
# Between them, a preview can never hand nginx a secret the running backend has not seen.
#
# The spool is 0700 and owned by the operator. Anything that can write it can create a
# card — including an `action` card — so treat spool write access as equivalent to
# console access. It is not equivalent to execution: an action card still has to be
# approved by the owner in the console, and the approved plan is hash-pinned, before
# anything runs. See SECURITY.md.
DEVMON_SECRET=""
if [ "$MESSAGES" = true ]; then
  if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ] && [ -r "$DEVMON_ENV" ]; then
    DEVMON_SECRET="$(sed -n 's/^DEV_MONITOR_PROXY_SECRET=//p' "$DEVMON_ENV" | head -1)"
  fi
  # Nothing to reuse (no env file yet, or it is unreadable): mint one. Safe on a dry run
  # only because the fragment write below will not overwrite an existing file.
  [ -n "$DEVMON_SECRET" ] || DEVMON_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
if [ "$MESSAGES" = true ] && [ "${AIRLOCK_DRY_RUN:-0}" != 1 ]; then
  install -d -m 700 "$DEVMON_STATE" "$DEVMON_STATE/spool" \
                    "$DEVMON_STATE/spool/tmp" "$DEVMON_STATE/spool/new" \
                    "$DEVMON_STATE/spool/processing" "$DEVMON_STATE/spool/bad"
  install -d -m 700 "$(dirname "$DEVMON_ENV")"
  # The webhook is a secret (it is a bearer capability to post in the channel), so it
  # lives in the environment named by slack_webhook_env, never in airlock.toml — the
  # same indirection [apps.publish] and [apps.feedback] use for their tokens.
  SLACK_WEBHOOK=""
  if [ -n "$SLACK_WEBHOOK_ENV" ]; then
    SLACK_WEBHOOK="$(printenv "$SLACK_WEBHOOK_ENV" 2>/dev/null || true)"
    [ -n "$SLACK_WEBHOOK" ] || log "WARN: slack_webhook_env=$SLACK_WEBHOOK_ENV is unset — Slack delivery stays off (cards and the feed are unaffected)"
  fi
  # The console link that Slack messages carry. Without a resolvable tailnet FQDN there
  # is no address that works from a phone, so the link is omitted rather than guessed.
  CONSOLE_URL=""
  if [ -n "$FQDN" ]; then
    CONSOLE_URL="https://${FQDN}/monitor/#messages"
  else
    log "WARN: tailnet FQDN unresolved — Slack notifications will carry no console link"
  fi
  # Not a preflight row: preflight is per-app and fails the whole install, and tmux is only
  # needed by the ACTION half of an optional console. Cards, coalescing, Slack and the feed
  # all work without it; an approval is refused with a reason instead of appearing to run.
  command -v tmux >/dev/null 2>&1 || \
    log "WARN: tmux not found — cards and the feed work, but approved actions cannot run. Install it (sudo apt-get install -y tmux) to use the action half."
  ( umask 077; cat >"$DEVMON_ENV" <<ENVF
# generated by apps/dev-monitor/install.sh — rewritten on every install
DEV_MONITOR_OWNER=${OWNER}
DEV_MONITOR_PROXY_SECRET=${DEVMON_SECRET}
DEV_MONITOR_SPOOL=${DEVMON_STATE}/spool
DEV_MONITOR_DB=${DEVMON_STATE}/messages.db
DEV_MONITOR_CWD_ROOT=${EXEC_CWD_ROOT:-$HOME}
DEV_MONITOR_EXEC_SESSION=${EXEC_SESSION}
DEV_MONITOR_SKILL_ALLOW=${SKILL_ALLOW}
AIRLOCK_DEVMON_SLACK_WEBHOOK=${SLACK_WEBHOOK}
AIRLOCK_DEVMON_CONSOLE_URL=${CONSOLE_URL}
ENVF
  )
  chmod 600 "$DEVMON_ENV"
elif [ "${AIRLOCK_DRY_RUN:-0}" != 1 ]; then
  rm -f "$DEVMON_ENV"
  # Turning the console off does not reach into a run that is already going. Killing
  # someone's in-flight work to honour a config change would be worse than leaving it —
  # but leaving it silently would be worse still, because the UI that could stop it is
  # about to disappear.
  if tmux has-session -t "$EXEC_SESSION" 2>/dev/null; then
    log "WARN: messages is now false, but tmux session '$EXEC_SESSION' still has running actions. \
They keep running and the console can no longer stop them — attach with 'tmux attach -t $EXEC_SESSION'."
  fi
fi

# --- 1. systemd user unit (loopback backend) ---
# AIRLOCK_RENDER_DIR forces the write branch even under AIRLOCK_DRY_RUN=1 —
# see install/lib.sh's fail-closed guard (RENDER_DIR without DRY_RUN=1 never
# reaches this line) and apps/feedback/install.sh's identical comment.
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ] && [ -z "${AIRLOCK_RENDER_DIR:-}" ]; then
  log "[dry] write $UNIT_DIR/airlock-dev-monitor.service (127.0.0.1:$BACKEND_PORT, messages=$MESSAGES)"
else
  install -d "$UNIT_DIR"
  render_dev_monitor_unit "$BACKEND_PORT" "$MESSAGES" "$IDENTITY_HEADER" "$cors_hosts" "$DEVMON_ENV" \
    >"$UNIT_DIR/airlock-dev-monitor.service"
fi
airlock_run systemctl --user daemon-reload
airlock_run systemctl --user enable airlock-dev-monitor.service
airlock_run systemctl --user restart airlock-dev-monitor.service

# --- 2. dashboard UI into the hub webroot (served by the hub's static location /) ---
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] install dev-monitor.html -> $WEBROOT/monitor/index.html"
else
  install -d "$WEBROOT/monitor"
  install -m644 "$HERE/frontend/dev-monitor.html" "$WEBROOT/monitor/index.html"
fi

# --- 3. nginx subpath fragment (included inside the hub server = server-level gate) ---
# Config, not a system mutation — written unconditionally. nginx runtime vars are
# escaped as \$ so the shell never expands them; the only shell substitutions are
# the backend port and the same-box origin regex below. No per-location guard: the
# hub server-level gate ($hub_ok) covers it.
frag="$CONFD/hub-locations.d/dev-monitor.conf"
install -d "$CONFD/hub-locations.d"

# Owner-only routes for the message/action console. This location exists ONLY when the
# console is enabled: with it absent, an owner request falls through to the general
# /monitor/api/ location, which blanks the identity headers, so the backend sees an
# unauthenticated request and 404s the feature. Fail-closed by construction.
#
# Both X-Devmon-* headers are set here, which is also what makes a client-supplied copy
# of them harmless — proxy_set_header REPLACES whatever the browser sent. The owner is
# taken from the ingress-injected identity header (never from the request body), and the
# secret proves the request came through nginx rather than straight to the loopback port.
owner_location=""
if [ "$MESSAGES" = true ]; then
  # nginx exposes a request header as $http_<name>, lowercased with '-' turned into '_'.
  hdr_var="$(printf '%s' "${IDENTITY_HEADER//-/_}" | tr '[:upper:]' '[:lower:]')"
  owner_location="$(render_dev_monitor_owner_location "$BACKEND_PORT" "$hdr_var" "$DEVMON_SECRET")"
fi

# A dry run must not touch an EXISTING fragment. Elsewhere in Airlock the nginx fragment
# is pure config and is written unconditionally, which is safe because it is a pure
# function of the config. This one is not: it carries a freshly minted secret, and whether
# it contains the owner location at all depends on `messages`. Previewing `messages = false`
# on a live box would therefore delete the owner location from the file nginx actually
# serves, and the console would 404 at the next reload with nothing to explain why.
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ] && [ -e "$frag" ]; then
  log "[dry] would rewrite $frag (messages=$MESSAGES) — left as is"
  frag="$(mktemp)"
fi
# Created restricted, THEN written: the fragment carries the proxy secret, and
# `cat > file` would otherwise create it under the default umask (world-readable) with
# the secret already in it and only narrow the mode afterwards. nginx reads its config
# as root, so 0600 owned by the installing user is readable where it needs to be.
install -m 600 /dev/null "$frag"
render_dev_monitor_nginx "$BACKEND_PORT" "$owner_location" >"$frag"
log "wrote nginx fragment: $frag"

# NOTE: smoke runs from the orchestrator AFTER nginx reload (gate not live before).
log "dev-monitor installed (owner: ${AIRLOCK_OWNER}; messages: ${MESSAGES})"
