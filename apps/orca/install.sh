#!/usr/bin/env bash
# orca — headless Orca ADE (an Electron agent IDE served in the browser) behind
# the Airlock owner gate.  Upstream: https://github.com/stablyai/orca
#
#   browser --https--> tailscale serve :https_port --(identity)--> nginx owner-gate
#           --(owner only / else 403)--> orca serve 0.0.0.0:backend_port
#                                        (nft loopback-only: only the gate reaches it)
#
# v1 uses the UPSTREAM web client that `orca serve` ships. The patched web-bundle
# (local browser render, PTY-reload fix, element grab) lives in a separate repo and
# is a documented follow-up — see README.md. Nothing here deploys a web overlay.
#
# Config from airlock.toml ([apps.orca]). Honors AIRLOCK_DRY_RUN=1: every system
# mutation (download, apt, systemctl, nft, tailscale, sudo) prints "[dry] ..."
# instead of running. The nginx fragment is config, not a mutation — always written.
#
# Pilot findings encoded below (each cost real debugging; do NOT "simplify" away):
# - orca serve has no --host flag, so it binds 0.0.0.0 -> nft loopback-only.
# - Under systemd --user the AppImage FUSE mount fails -> --appimage-extract + APPDIR.
# - orca is Electron (Chromium): even headless `serve` needs GTK libs + an X display
#   (no GTK -> 'libgtk-3.so.0' status 127; no display -> 'Missing X server' SIGSEGV).
# - The pairing URL is only ever written to serve.log, never to journald.
# - The orca daemon self-detaches into an app-orca-*.scope (app.slice), so the
#   service's own KillMode/MemoryMax never reach it -> ExecStopPost reap.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"
# shellcheck source=/dev/null
. "$ROOT/gate/nginx-lib.sh"

airlock_load orca
GATE_PORT="${AIRLOCK_ORCA_GATE_PORT:?}"
BACKEND_PORT="${AIRLOCK_ORCA_BACKEND_PORT:?}"
HTTPS_PORT="${AIRLOCK_ORCA_HTTPS_PORT:?}"
CONFD="${AIRLOCK_CONFD:-/etc/airlock/nginx}"

require_cmd curl sha256sum tar systemctl tailscale python3 nft

# The pinned SHA below is for the amd64 AppImage only.
case "$(uname -m)" in
  x86_64) ;;
  *) die "orca: unsupported arch $(uname -m) — the pinned SHA is for amd64" ;;
esac

VER=1.4.139
ASSET=orca-linux.AppImage
URL="https://github.com/stablyai/orca/releases/download/v${VER}/${ASSET}"
SHA256=35ab8dc3b1427544ea1fc67f8c54a337f0b9b4d315abee4eedd9306006b43fb2

ORCA_DIR="$HOME/.local/share/airlock-orca"
APPIMAGE="$ORCA_DIR/orca-${VER}.AppImage"
SQUASHFS="$ORCA_DIR/squashfs-root"
APPRUN="$SQUASHFS/AppRun"
SERVELOG="$ORCA_DIR/serve.log"
UNIT_DIR="$HOME/.config/systemd/user"
REAP_BIN="$HOME/.local/bin/airlock-orca-reap"
PAIRING_FILE="$HOME/.config/orca/airlock-pairing-code"
# Dedicated Xvfb display number so we never squat an ambient :99 someone else runs.
XDISP=59

# --- 1a. Electron runtime deps (Xvfb + GTK/nss/gbm/...) ---
# noble renamed several libs to the t64 ABI, so fall back to the non-t64 name per
# package -> distro-independent. sudo apt; skipped when already satisfied.
ORCA_DEPS="xvfb libgtk-3-0t64 libgbm1 libnss3 libasound2t64 libnotify4 libxtst6 libxss1 libatspi2.0-0t64 libsecret-1-0"
provision_runtime_deps() {
  if command -v Xvfb >/dev/null 2>&1 && ldconfig -p 2>/dev/null | grep -q 'libgtk-3\.so\.0'; then
    log "Electron runtime deps present (Xvfb + GTK)"; return
  fi
  if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
    log "[dry] sudo apt-get install Electron runtime deps: $ORCA_DEPS"; return
  fi
  sudo apt-get update -qq >/dev/null 2>&1 || true
  local p
  for p in $ORCA_DEPS; do
    sudo apt-get install -y "$p" >/dev/null 2>&1 \
      || sudo apt-get install -y "${p%t64}" >/dev/null 2>&1 || true
  done
  command -v Xvfb >/dev/null 2>&1 || die "Xvfb install failed"
  ldconfig -p 2>/dev/null | grep -q 'libgtk-3\.so\.0' || die "libgtk-3 install failed — Electron cannot run"
}
provision_runtime_deps

# --- 1b. provision orca (sha256-pinned AppImage; extract for FUSE-less run) ---
provision_orca() {
  if [ -x "$APPRUN" ] && [ -f "$APPIMAGE" ] \
     && [ "$(sha256sum "$APPIMAGE" | cut -d' ' -f1)" = "$SHA256" ] \
     && [ ! "$APPIMAGE" -nt "$APPRUN" ]; then
    log "orca $VER present + extracted (sha ok)"; return
  fi
  if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
    log "[dry] download+verify orca $VER ($ASSET) + --appimage-extract -> $SQUASHFS"; return
  fi
  install -d -m 700 "$ORCA_DIR"
  if [ ! -f "$APPIMAGE" ] || [ "$(sha256sum "$APPIMAGE" | cut -d' ' -f1)" != "$SHA256" ]; then
    log "downloading orca $VER: $URL"
    local td; td="$(mktemp -d)"
    curl -fsSL --max-time 300 -o "$td/$ASSET" "$URL" || { rm -rf "$td"; die "orca download failed: $URL"; }
    local got; got="$(sha256sum "$td/$ASSET" | cut -d' ' -f1)"
    [ "$got" = "$SHA256" ] || { rm -rf "$td"; die "orca sha256 mismatch got=$got want=$SHA256"; }
    mv "$td/$ASSET" "$APPIMAGE"; rm -rf "$td"
    log "orca sha256 verified ($VER)"
  fi
  chmod +x "$APPIMAGE"
  # AppImage FUSE mount fails under systemd --user -> extract and run AppRun directly.
  rm -rf "$SQUASHFS"
  ( cd "$ORCA_DIR" && "$APPIMAGE" --appimage-extract >/dev/null ) || die "orca AppImage extract failed"
  [ -x "$APPRUN" ] || die "orca AppRun missing after extract: $APPRUN"
}
provision_orca

# --- 2. fixed pairing code + tailnet FQDN (both baked into the unit ExecStart) ---
# A fixed pairing code -> a stable webClientUrl the owner can bookmark across
# restarts. The blob is just an endpoint pointer and sits behind the owner gate +
# nft, so it is inert if leaked. Owner-only (0600).
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] ensure fixed pairing code at $PAIRING_FILE (0600)"
  PAIRING_CODE="<pairing-code>"
  FQDN="<your-box>.ts.net"
else
  install -d "$HOME/.config/orca"
  if [ -s "$PAIRING_FILE" ]; then
    PAIRING_CODE="$(cat "$PAIRING_FILE")"
  else
    PAIRING_CODE="$(python3 -c 'import secrets;print(secrets.token_hex(16))')"
    install -m 600 /dev/null "$PAIRING_FILE"
    printf '%s' "$PAIRING_CODE" > "$PAIRING_FILE"
    log "generated fixed pairing code ($PAIRING_FILE, 0600)"
  fi
  FQDN="$(ts_fqdn)"
fi

# --- 3. systemd --user units: reap helper + dedicated Xvfb + orca serve ---
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] write $REAP_BIN, $UNIT_DIR/airlock-orca-xvfb.service, $UNIT_DIR/airlock-orca.service"
else
  install -d "$UNIT_DIR" "$HOME/.local/bin"

  # Daemon reap — orca forks its daemon into app-orca-*.scope (app.slice), which
  # the service's KillMode never reaches. Runs as ExecStopPost (i.e. on every
  # restart): kill the daemon pid (PID-reuse-safe via /proc/<pid>/exe) and stop
  # every leftover app-orca-*.scope (one agent-browser child leaks per restart).
  cat >"$REAP_BIN" <<'REAP'
#!/usr/bin/env bash
# airlock-orca daemon reap — ExecStopPost for airlock-orca.service. PID-reuse safe.
for f in "$HOME"/.config/orca/daemon/daemon-v*.pid; do
    [ -f "$f" ] || continue
    p=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["pid"])' "$f" 2>/dev/null)
    [ -n "$p" ] || { rm -f "$f"; continue; }
    exe=$(readlink -f "/proc/$p/exe" 2>/dev/null)
    case "$exe" in
        *orca*) kill "$p" 2>/dev/null || true ;;   # only orca-family pids (PID-reuse guard)
    esac
    rm -f "$f"
done
# Reclaim self-detached scopes: killing the daemon leaves its app-orca-*.scope and
# the agent-browser child inside it, which otherwise accumulate one per restart.
# orca is single-instance and this only runs while the service is down, so every
# app-orca-* here belongs to the dying (or already-dead) instance -> stop them all.
systemctl --user stop 'app-orca-*.scope' 2>/dev/null || true
exit 0
REAP
  chmod +x "$REAP_BIN"

  # Dedicated persistent Xvfb — orca is Electron and needs a real X display even
  # headless. A per-start xvfb-run races the socket create on some boxes ('Missing
  # X server'); a standing unit removes that race. orca (below) After/Requires it.
  cat >"$UNIT_DIR/airlock-orca-xvfb.service" <<UNIT
[Unit]
Description=airlock-orca-xvfb — dedicated virtual display (:${XDISP}) for Orca ADE
After=default.target

[Service]
Type=simple
# Clear a stale lock/socket for our own display (:${XDISP}) before Xvfb recreates it.
ExecStartPre=-/bin/sh -c 'rm -f /tmp/.X${XDISP}-lock /tmp/.X11-unix/X${XDISP}'
# -extension GLX: on boxes with NVIDIA userspace EGL/GBM libs, Xvfb SIGSEGVs while
#   loading libEGL_nvidia during GLX init (no real GPU in a container). orca renders
#   with LIBGL_ALWAYS_SOFTWARE so it never needs server GLX -> disabling it is safe.
ExecStart=/usr/bin/Xvfb :${XDISP} -screen 0 1280x1024x24 -nolisten tcp -extension GLX
# active != socket-ready -> poll for the socket (up to ~10s) so orca's After holds.
ExecStartPost=/bin/sh -c 'for _ in \$(seq 1 100); do [ -S /tmp/.X11-unix/X${XDISP} ] && exit 0; sleep 0.1; done; exit 1'
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
UNIT

  # orca serve — single instance behind the loopback gate.
  cat >"$UNIT_DIR/airlock-orca.service" <<UNIT
[Unit]
Description=airlock-orca — Orca ADE headless serve (behind the 127.0.0.1 owner gate)
Requires=airlock-orca-xvfb.service
After=default.target airlock-orca-xvfb.service

[Service]
Type=simple
Environment=LIBGL_ALWAYS_SOFTWARE=1
Environment=APPDIR=${SQUASHFS}
# DISPLAY is provided by the dedicated Xvfb unit; without it orca SIGSEGVs.
Environment=DISPLAY=:${XDISP}
# Defensive: even with xvfb active the socket can lag a moment — wait for it.
ExecStartPre=/bin/sh -c 'for _ in \$(seq 1 100); do [ -S /tmp/.X11-unix/X${XDISP} ] && exit 0; sleep 0.1; done; echo "X${XDISP} socket not ready"; exit 1'
# --pairing-code fixed (above) -> stable webClientUrl. --pairing-address rewrites
# the endpoint the web client dials to the public gate (default ws://0.0.0.0:BACKEND
# is not browser-reachable). The webClientUrl is only ever emitted to serve.log
# (Electron stdout never reaches journald), so capture it there.
ExecStart=/bin/sh -c 'exec ${APPRUN} serve --port ${BACKEND_PORT} --pairing-code ${PAIRING_CODE} --pairing-address wss://${FQDN}:${HTTPS_PORT} > ${SERVELOG} 2>&1'
# The daemon self-detaches into app-orca-*.scope, so reclaim it on stop.
ExecStopPost=${REAP_BIN}
Restart=on-failure
RestartSec=3
# Backstop only — app-orca-*.scope lives in app.slice, outside this cap.
MemoryMax=8G
TasksMax=1024
NoNewPrivileges=yes

[Install]
WantedBy=default.target
UNIT

  # serve.log 0600 (it holds the pairing webClientUrl). ExecStart's '>' preserves
  # an existing file's mode, so lock it down before the first start.
  [ -e "$SERVELOG" ] || : > "$SERVELOG" 2>/dev/null || true
  chmod 600 "$SERVELOG" 2>/dev/null || true
fi

airlock_run systemctl --user daemon-reload
airlock_run systemctl --user enable airlock-orca-xvfb.service airlock-orca.service
airlock_run systemctl --user restart airlock-orca-xvfb.service
airlock_run systemctl --user restart airlock-orca.service

# --- 4. nft: restrict the backend to loopback callers (orca binds 0.0.0.0) ---
# orca serve has no --host flag, so it binds 0.0.0.0:BACKEND. Without this the
# backend is reachable directly over the tailnet, bypassing the owner gate.
# render_loopback_nft fills the shared gate/loopback-only.nft.tpl (table
# airlock_orca, isolated from docker's ip/ip6 tables). A systemd oneshot re-applies
# it on boot — nft rulesets are not persistent by default, so a reboot would
# otherwise silently reopen the hole.
NFT_FILE="/etc/airlock/orca-loopback.nft"
NFT_UNIT="/etc/systemd/system/airlock-orca-firewall.service"
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] render_loopback_nft airlock_orca $BACKEND_PORT -> $NFT_FILE"
  log "[dry] write $NFT_UNIT + sudo nft -f (drop non-loopback -> :$BACKEND_PORT)"
else
  sudo install -d "$(dirname "$NFT_FILE")"
  render_loopback_nft airlock_orca "$BACKEND_PORT" | sudo tee "$NFT_FILE" >/dev/null
  sudo tee "$NFT_UNIT" >/dev/null <<UNIT
[Unit]
Description=airlock-orca firewall — drop non-loopback traffic to :${BACKEND_PORT} (orca binds 0.0.0.0)
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
# Idempotent re-apply: drop only our own table, then reload it (docker untouched).
ExecStart=/bin/sh -c '/usr/sbin/nft delete table inet airlock_orca 2>/dev/null; /usr/sbin/nft -f ${NFT_FILE}'
ExecStop=/usr/sbin/nft delete table inet airlock_orca

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  sudo systemctl enable --now airlock-orca-firewall.service
fi

# --- 5. nginx owner-gate fragment (owner-only; written unconditionally) ---
frag="$CONFD/servers.d/orca.conf"
install -d "$CONFD/servers.d"
{
  echo "# orca owner gate — generated by apps/orca/install.sh"
  emit_owner_gate "$GATE_PORT" "127.0.0.1:${BACKEND_PORT}" owner_ok
} > "$frag"
log "wrote nginx fragment: $frag"

# --- 6. tailscale serve: HTTPS (secure context, for clipboard) -> the owner gate ---
airlock_run sudo tailscale serve --bg --https="${HTTPS_PORT}" "http://127.0.0.1:${GATE_PORT}"

# orca (Electron) cold-starts slowly. Give the backend a bounded window to bind
# before the orchestrator renders nginx and smokes, so smoke doesn't race a
# still-booting daemon. Non-fatal: the orchestrator's smoke is the real gate.
if [ "${AIRLOCK_DRY_RUN:-0}" != 1 ]; then
  ready=0
  for _ in $(seq 1 30); do
    if ss -ltn 2>/dev/null | grep -qE ":${BACKEND_PORT}\b"; then ready=1; break; fi
    sleep 2
  done
  if [ "$ready" = 1 ]; then
    log "orca backend listening on 127.0.0.1:${BACKEND_PORT}"
    url="$(grep -oE 'https://[^ "]*web-index\.html#pairing=[^ "]*' "$SERVELOG" 2>/dev/null | tail -1 || true)"
    [ -n "$url" ] && log "web client (bookmark this): $url" \
      || log "web client: https://${FQDN}:${HTTPS_PORT}/ (pairing URL not in $SERVELOG yet)"
  else
    log "warning: orca backend not listening after ~60s (smoke will verify; check: journalctl --user -u airlock-orca)"
  fi
fi

# NOTE: smoke runs from the orchestrator AFTER nginx is rendered + reloaded
# (the gate isn't live until then). See install/airlock-install.sh.
log "orca installed (owner: ${AIRLOCK_OWNER})"
