#!/usr/bin/env bash
# Small, sourceable state decisions used by install.sh and parity fixtures.

# A stale systemd manager view is evidence that a prior deployment stopped after
# writing the unit but before completing daemon-reload/restart. Observe it before
# this install runs daemon-reload, otherwise the evidence is erased.
paseo_unit_needs_daemon_reload() {
  local unit="${1:?unit required}" state
  state="$(systemctl --user show "$unit" -p NeedDaemonReload --value 2>/dev/null || true)"
  [ "$state" = yes ]
}

# Pure restart decision: current-run change, prior partial deployment, or a dead
# service all require restart. This is deliberately separate from systemctl so
# every branch can be driven by a deterministic fixture.
paseo_should_restart() {
  local changed="${1:-0}" daemon_reload="${2:-no}" active="${3:-inactive}"
  [ "$changed" = 1 ] || [ "$daemon_reload" = yes ] || [ "$active" != active ]
}

# Linger is host/account policy, not app policy. Report missing persistence but
# never grant it here; the operator can make that decision outside the app install.
warn_paseo_linger() {
  local who="${1:-}" linger
  if ! command -v loginctl >/dev/null 2>&1; then
    log "WARN: loginctl unavailable; could not verify linger for ${who:-current user}"
    return 0
  fi
  if [ -z "$who" ]; then
    who="$(id -un 2>/dev/null || true)"
  fi
  if [ -z "$who" ]; then
    log "WARN: current user unknown; could not verify linger"
    return 0
  fi
  linger="$(loginctl show-user "$who" -p Linger --value 2>/dev/null || true)"
  [ "$linger" = yes ] \
    || log "WARN: linger is not enabled for $who; Paseo did not enable it"
}
