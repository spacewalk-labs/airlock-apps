#!/usr/bin/env bash
# devterm — browser web terminal: a custom xterm.js client + a programmable gate in
# front of a ttyd PTY backend, all behind the Airlock owner gate.
#
#   browser --https--> tailscale serve :HTTPS --(identity)--> nginx owner-gate
#           --(owner only / else 403)--> devterm-gate 127.0.0.1:BACKEND
#                                        --> serves web/ + API, proxies /ws,/token --> ttyd --> tmux
#
# Config comes from airlock.toml ([apps.devterm]). Optional features (Claude account
# pool, Codex login, markwand file-open, Orca worktree sidebar) turn on only when their
# config + tools are present; otherwise they no-op cleanly.
# Honors AIRLOCK_DRY_RUN=1 (print system-mutating steps instead of running them).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"
# shellcheck source=/dev/null
. "$ROOT/gate/nginx-lib.sh"

airlock_load devterm
TTYD_PORT="${AIRLOCK_DEVTERM_TTYD_PORT:?}"
BACKEND_PORT="${AIRLOCK_DEVTERM_BACKEND_PORT:?}"
GATE_PORT="${AIRLOCK_DEVTERM_GATE_PORT:?}"
HTTPS_PORT="${AIRLOCK_DEVTERM_HTTPS_PORT:?}"
PUBLIC_PORT="${AIRLOCK_DEVTERM_PUBLIC_PORT:?}"
CONFD="${AIRLOCK_CONFD:-/etc/airlock/nginx}"
TTYD_BIN="${TTYD_BIN:-$HOME/.local/bin/ttyd}"
DEVTERM_LANG="${AIRLOCK_DEVTERM_LANG:-C.UTF-8}"
FONT_SIZE="${AIRLOCK_DEVTERM_FONT_SIZE:-15}"
IDENTITY_HEADER="${AIRLOCK_IDENTITY_HEADER:?}"
ACCOUNTS="${AIRLOCK_DEVTERM_ACCOUNTS:-false}"
REMOTE_HOSTS="${AIRLOCK_DEVTERM_REMOTE_HOSTS:-}"
CLAUDE_SWITCH="${AIRLOCK_DEVTERM_CLAUDE_SWITCH:-}"
CLAUDE_STATUS="${AIRLOCK_DEVTERM_CLAUDE_STATUS:-}"
FLEET_STORE="${AIRLOCK_DEVTERM_FLEET_STORE:-}"
FLEET_STORE_URL="${AIRLOCK_DEVTERM_FLEET_STORE_URL:-}"
ORCA_SHIM_CFG="${AIRLOCK_DEVTERM_ORCA_SHIM:-}"
CODE_ROOT="${AIRLOCK_CODE_ROOT:-}"
WEB_ROOT="$HOME/.local/share/airlock-devterm/web"
GATE_PY="$HERE/backend/devterm-gate.py"
UNIT_DIR="$HOME/.config/systemd/user"
PY="$(command -v python3)"

require_cmd tmux python3

# is app <name> enabled in airlock.toml?
app_enabled() { airlock_config apps | grep -qx "$1"; }

# --- resolve optional feature wiring ---
# markwand file-open: on only when [apps.markwand] is enabled AND a code_root is set.
MARKWAND=false
if app_enabled markwand && [ -n "$CODE_ROOT" ]; then MARKWAND=true; fi
# Orca worktree sidebar: use the configured shim path, else the conventional one when
# [apps.orca] is enabled, else empty (feature off). The gate checks the file at runtime.
ORCA_SHIM=""
if [ -n "$ORCA_SHIM_CFG" ]; then ORCA_SHIM="$ORCA_SHIM_CFG"
elif app_enabled orca; then ORCA_SHIM="~/.config/orca/linux-orca-cli-shim/orca"; fi  # gate expanduser()s the ~
# hub http port (for the client's hubBase on plain http). Hub is required.
HUB_HTTP_PORT="$(airlock_config get apps.hub.http_port)"

# --- 1. provision ttyd (sha256-pinned) ---
provision_ttyd() {
  [ -x "$TTYD_BIN" ] && { log "ttyd present: $TTYD_BIN"; return; }
  local ver=1.7.7 asset sha
  case "$(uname -m)" in
    x86_64)  asset=ttyd.x86_64;  sha=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 ;;
    aarch64) asset=ttyd.aarch64; sha='' ;;   # no pin for arm64 yet — downloads unverified
    *) die "ttyd: unsupported arch $(uname -m) — install manually (github.com/tsl0922/ttyd)" ;;
  esac
  local url="https://github.com/tsl0922/ttyd/releases/download/${ver}/${asset}"
  if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then log "[dry] download+verify ttyd ${ver} -> $TTYD_BIN"; return; fi
  local tmp; tmp="$(mktemp)"
  curl -fsSL --max-time 60 -o "$tmp" "$url" || { rm -f "$tmp"; die "ttyd download failed: $url"; }
  if [ -n "$sha" ]; then
    local got; got="$(sha256sum "$tmp" | cut -d' ' -f1)"
    [ "$got" = "$sha" ] || { rm -f "$tmp"; die "ttyd sha256 mismatch got=$got want=$sha"; }
    log "ttyd sha256 verified ($ver)"
  else
    log "warning: no sha256 pin for $(uname -m) — ttyd downloaded unverified"
  fi
  install -D -m755 "$tmp" "$TTYD_BIN"; rm -f "$tmp"
}
provision_ttyd

# --- 2. shell wrapper ---
airlock_run install -D -m755 "$HERE/bin/devterm-shell" "$HOME/.local/bin/devterm-shell"

# --- 3. custom web client into WEB_ROOT (index.html templated with runtime config) ---
CFG_JSON="{\"httpsPort\":${HTTPS_PORT},\"publicPort\":${PUBLIC_PORT},\"hubHttpPort\":${HUB_HTTP_PORT},\"accounts\":${ACCOUNTS},\"markwand\":${MARKWAND},\"orca\":$([ -n "$ORCA_SHIM" ] && echo true || echo false)}"
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] install web/ -> $WEB_ROOT (index.html config=${CFG_JSON})"
else
  install -d "$WEB_ROOT/vendor"
  install -m644 "$HERE/web/app.js" "$HERE/web/accounts.js" "$HERE/web/favicon.svg" "$WEB_ROOT/"
  install -m644 "$HERE"/web/vendor/* "$WEB_ROOT/vendor/"
  # template the config placeholder (JSON has no sed metachars; use | as delimiter)
  sed "s|%%DEVTERM_CONFIG%%|${CFG_JSON}|" "$HERE/web/index.html" > "$WEB_ROOT/index.html"
  chmod 644 "$WEB_ROOT/index.html"
fi

# --- 4. systemd user units (write_if_changed -> restart only when content changes) ---
# ttyd unit: pure PTY backend, loopback only. KillMode=process so a redeploy that does
# change the unit restarts ttyd without killing tmux sessions born in its cgroup.
install -d "$UNIT_DIR"
changed_ttyd=0
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] write $UNIT_DIR/airlock-devterm.service (ttyd -i 127.0.0.1 -p $TTYD_PORT)"
else
  if write_if_changed "$UNIT_DIR/airlock-devterm.service" <<UNIT
[Unit]
Description=airlock devterm — ttyd PTY backend (127.0.0.1:${TTYD_PORT})
After=network.target

[Service]
Environment=LANG=${DEVTERM_LANG}
Environment=LC_CTYPE=${DEVTERM_LANG}
# -a: pass ?arg= to the shell as its session name; -W: writable; -P 2: fast dead-conn detect
ExecStart=${TTYD_BIN} -i 127.0.0.1 -p ${TTYD_PORT} -P 2 -W -a -t fontSize=${FONT_SIZE} %h/.local/bin/devterm-shell
KillMode=process
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
UNIT
  then changed_ttyd=1; fi
fi

# gate unit: serves the custom client + API, proxies /ws,/token to ttyd. A content
# revision (hash of gate + web) is embedded so write_if_changed triggers a restart when
# the code changes — and NOT on a no-op re-run.
REV="$(cat "$GATE_PY" "$HERE"/web/app.js "$HERE"/web/accounts.js "$HERE"/web/index.html 2>/dev/null | sha256sum | cut -c1-12)"
gate_env=""
add_env() { gate_env="${gate_env}Environment=$1=$2
"; }
add_env DEVTERM_REV "$REV"
add_env DEVTERM_LISTEN_HOST 127.0.0.1
add_env DEVTERM_LISTEN_PORT "$BACKEND_PORT"
add_env DEVTERM_TTYD_HOST 127.0.0.1
add_env DEVTERM_TTYD_PORT "$TTYD_PORT"
add_env DEVTERM_WEB "$WEB_ROOT"
add_env AIRLOCK_IDENTITY_HEADER "$IDENTITY_HEADER"
add_env AIRLOCK_OWNER "$AIRLOCK_OWNER"
add_env AIRLOCK_CODE_ROOT "$CODE_ROOT"
add_env DEVTERM_MARKWAND "$MARKWAND"
add_env DEVTERM_ACCOUNTS "$ACCOUNTS"
add_env DEVTERM_REMOTE_HOSTS "$REMOTE_HOSTS"
add_env DEVTERM_ORCA_SHIM "$ORCA_SHIM"
# account tools are wired only when accounts=true (else the endpoints stay disabled)
if [ "$ACCOUNTS" = true ]; then
  add_env DEVTERM_CLAUDE_SWITCH "$CLAUDE_SWITCH"
  add_env DEVTERM_CLAUDE_STATUS "$CLAUDE_STATUS"
  add_env DEVTERM_FLEET_STORE "$FLEET_STORE"
  add_env DEVTERM_FLEET_STORE_URL "$FLEET_STORE_URL"
fi

changed_gate=0
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] write $UNIT_DIR/airlock-devterm-gate.service (127.0.0.1:$BACKEND_PORT; accounts=$ACCOUNTS markwand=$MARKWAND orca=$([ -n "$ORCA_SHIM" ] && echo true || echo false))"
else
  if write_if_changed "$UNIT_DIR/airlock-devterm-gate.service" <<UNIT
[Unit]
Description=airlock devterm-gate — custom client + API, proxies to ttyd (127.0.0.1:${BACKEND_PORT})
After=network.target airlock-devterm.service
Wants=airlock-devterm.service

[Service]
Type=simple
${gate_env}ExecStart=${PY} ${GATE_PY}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
UNIT
  then changed_gate=1; fi
fi

airlock_run systemctl --user daemon-reload
airlock_run systemctl --user enable airlock-devterm.service airlock-devterm-gate.service
# restart only what changed (no needless restarts on idempotent re-runs)
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] restart ttyd/gate units if changed"
else
  systemctl --user is-active --quiet airlock-devterm.service || changed_ttyd=1
  systemctl --user is-active --quiet airlock-devterm-gate.service || changed_gate=1
  [ "$changed_ttyd" = 1 ] && airlock_run systemctl --user restart airlock-devterm.service || true
  [ "$changed_gate" = 1 ] && airlock_run systemctl --user restart airlock-devterm-gate.service || true
fi

# --- 5. nginx owner-gate fragment (proxies GATE_PORT -> devterm-gate; owner-only) ---
# Written unconditionally: it is config the renderer includes, not a system mutation.
frag="$CONFD/servers.d/devterm.conf"
install -d "$CONFD/servers.d"
{
  echo "# devterm owner gate — generated by apps/devterm/install.sh"
  emit_owner_gate "$GATE_PORT" "127.0.0.1:${BACKEND_PORT}" owner_ok
} > "$frag"
log "wrote nginx fragment: $frag"

# --- 6. tailscale serve: expose HTTPS (secure context) + HTTP (convenience) -> gate ---
# HTTPS gives a secure context (clipboard, OSC52). Needs the FQDN cert Tailscale issues.
airlock_run sudo tailscale serve --bg --https="${HTTPS_PORT}" "http://127.0.0.1:${GATE_PORT}"
airlock_run sudo tailscale serve --bg --http="${PUBLIC_PORT}"  "http://127.0.0.1:${GATE_PORT}"

# NOTE: smoke runs from the orchestrator AFTER nginx is rendered + reloaded.
log "devterm installed (owner: ${AIRLOCK_OWNER}; accounts=${ACCOUNTS}, markwand=${MARKWAND}, orca=$([ -n "$ORCA_SHIM" ] && echo true || echo false))"
