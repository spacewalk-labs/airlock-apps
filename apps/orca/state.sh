#!/usr/bin/env bash
# Sourceable Orca lifecycle decisions. Functions only: tests and the installer
# share the same three-state evidence rules without touching a live service.

orca_notice() {
  if declare -F log >/dev/null 2>&1; then
    log "$*"
  else
    printf '[orca] %s\n' "$*" >&2
  fi
}

# orca_restart_plan XVFB_CHANGED XVFB_ACTIVE SOCKET_READY
#                   ORCA_CHANGED BINARY_CHANGED STALE_APPRUN ORCA_ACTIVE
# Prints the user services to restart, in dependency order.
orca_restart_plan() {
  local xvfb_changed="$1" xvfb_active="$2" socket_ready="$3"
  local orca_changed="$4" binary_changed="$5" stale_apprun="$6" orca_active="$7"
  local xvfb_restarted=0

  if [ "$xvfb_changed" = 1 ] || [ "$xvfb_active" != 1 ] || [ "$socket_ready" != 1 ]; then
    printf '%s\n' airlock-orca-xvfb.service
    xvfb_restarted=1
  fi
  if [ "$orca_changed" = 1 ] || [ "$binary_changed" = 1 ] \
      || [ "$stale_apprun" = 1 ] || [ "$xvfb_restarted" = 1 ] \
      || [ "$orca_active" != 1 ]; then
    printf '%s\n' airlock-orca.service
  fi
}

orca_unit_needs_reload() {
  [ "$(systemctl --user show "$1" -p NeedDaemonReload --value 2>/dev/null || true)" = yes ]
}

orca_apprun_is_stale() {
  local unit="$1" apprun="$2" started_text started_epoch apprun_epoch
  systemctl --user is-active --quiet "$unit" 2>/dev/null || return 1
  started_text="$(systemctl --user show "$unit" -p ActiveEnterTimestamp --value 2>/dev/null || true)"
  started_epoch="$(date -d "$started_text" +%s 2>/dev/null || printf '0')"
  apprun_epoch="$(stat -c %Y "$apprun" 2>/dev/null || printf '0')"
  [ "$started_epoch" -gt 0 ] && [ "$apprun_epoch" -gt "$started_epoch" ]
}

warn_orca_linger() {
  local user="${1:-$(id -un)}" linger
  linger="$(loginctl show-user "$user" -p Linger --value 2>/dev/null || true)"
  if [ "$linger" = yes ]; then
    orca_notice "linger=yes for $user (observed; app made no change)"
  else
    orca_notice "WARN: linger is not enabled for $user; reboot persistence is not guaranteed (observe only)"
  fi
}

# Three-state result: 0=live serve evidence, 1=proven orphan, 2=unknown.
# Unknown is intentionally fail-safe: unreadable cgroup/proc evidence is never a
# license to stop a user's live scope.
orca_scope_has_serve() {
  local scope="$1" cgroup_root="${ORCA_CGROUP_ROOT:-/sys/fs/cgroup}"
  local proc_root="${ORCA_PROC_ROOT:-/proc}" control_group procs pid arg unknown=0
  local -a argv=()

  control_group="$(systemctl --user show "$scope" -p ControlGroup --value 2>/dev/null)" \
    || return 2
  [ -n "$control_group" ] || return 2
  procs="${cgroup_root}${control_group}/cgroup.procs"
  [ -r "$procs" ] || return 2

  while read -r pid; do
    [ -n "$pid" ] || continue
    if [ ! -r "$proc_root/$pid/cmdline" ]; then
      unknown=1
      continue
    fi
    argv=()
    mapfile -d '' -t argv < "$proc_root/$pid/cmdline" 2>/dev/null || {
      unknown=1
      continue
    }
    for arg in "${argv[@]}"; do
      [ "$arg" != --serve ] || return 0
    done
    # The shipped Orca AppImage uses the positional `AppRun serve --port ...`
    # form. Keep the older --serve spelling as compatible live evidence too.
    if [ "${argv[1]:-}" = serve ] && [ "$(basename "${argv[0]:-}")" = AppRun ]; then
      return 0
    fi
  done < "$procs"

  [ "$unknown" = 0 ] || return 2
  return 1
}

reconcile_orca_scopes() {
  local units scope rc reaped=0
  units="$(systemctl --user list-units --all --no-legend --plain \
    'app-orca-*.scope' 2>/dev/null)" || {
      orca_notice "WARN: unable to list app-orca scopes; preserving unknown state"
      return 0
    }

  while read -r scope _; do
    case "$scope" in app-orca-*.scope) ;; *) continue ;; esac
    if orca_scope_has_serve "$scope"; then
      orca_notice "preserved live scope: $scope"
      continue
    else
      rc=$?
    fi
    if [ "$rc" = 1 ]; then
      if systemctl --user stop "$scope" >/dev/null 2>&1; then
        reaped=$((reaped + 1))
      else
        orca_notice "WARN: failed to stop proven orphan scope: $scope"
      fi
    else
      orca_notice "WARN: preserved scope with unknown evidence: $scope"
    fi
  done <<< "$units"

  [ "$reaped" -eq 0 ] || orca_notice "reaped=$reaped proven app-orca orphan scope(s)"
}
