#!/usr/bin/env bash
# paseo — a coding-agent orchestration daemon with a self-hosted web UI, behind
# the Airlock owner gate.  Upstream: https://github.com/getpaseo/paseo
#
#   browser --https--> tailscale serve :https_port --(identity)--> nginx owner-gate
#           --(owner only / else 403)--> paseo daemon 127.0.0.1:backend_port
#                                        --spawn--> claude / codex / gemini (child CLIs)
#
# Unlike orca/code-server, paseo is PURE NODE: no Electron, Xvfb, AppImage or
# nft. The daemon binds 127.0.0.1 (loopback), so localhost binding IS the
# isolation — the only route in is tailscale serve -> the nginx owner gate. It
# serves a same-origin web UI and spawns provider CLIs as child processes.
#
# Three gate/unit specifics are load-bearing (without them the web UI WebSocket
# dies — each cost real debugging; do NOT "simplify" them away):
#   (1) the nginx gate must send `X-Forwarded-Proto https` (literal). This gate is
#       a plain-http listener, so $scheme would be 'http'; the daemon would then
#       tell the web UI to open ws:// and the WebSocket would fail behind TLS.
#   (2) the daemon unit must set PASEO_TRUSTED_PROXIES=127.0.0.1 so it trusts (1)
#       and upgrades the web UI to wss://.
#   (3) the nginx gate must send `Host <fqdn>:<https_port>` WITH the port. $host
#       strips the port and triggers a welcome-screen bug. The daemon's
#       PASEO_HOSTNAMES allowlist must accept that same host (DNS-rebinding guard).
# emit_owner_gate does NOT add (1)/(3), so the paseo gate fragment is written
# directly below — but it replicates emit_owner_gate's structure exactly.
#
# Config from airlock.toml ([apps.paseo]). Honors AIRLOCK_DRY_RUN=1: every system
# mutation (npm, patch, systemctl, tailscale, sudo) prints "[dry] ..." instead of
# running. The nginx fragment is config, not a mutation — always written.
#
# browse-host (server-side browser panels for agents — Playwright headless Chromium
# behind the daemon) is CONFIG-GATED: set `browse = true` under [apps.paseo] to wire
# it in. When on, this installer adds the owner-gated /browse-view/ stream route to
# the gate below and runs browse-host/install.sh (warn-only — a chromium/patch
# failure never breaks the hub or the paseo daemon). Default off keeps the install
# lean (chromium is a ~150MB download). See browse-host/README.md.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load paseo
GATE_PORT="${AIRLOCK_PASEO_GATE_PORT:?}"
BACKEND_PORT="${AIRLOCK_PASEO_BACKEND_PORT:?}"
HTTPS_PORT="${AIRLOCK_PASEO_HTTPS_PORT:?}"
CONFD="${AIRLOCK_CONFD:-/etc/airlock/nginx}"
# browse-host (config-gated). When BROWSE=true we add the /browse-view/ stream
# route to the gate and run browse-host/install.sh at the end (warn-only).
BROWSE="${AIRLOCK_PASEO_BROWSE:-false}"
BROWSE_WS_PORT="${AIRLOCK_PASEO_BROWSE_WS_PORT:-6768}"

PASEO_PKG="@getpaseo/cli"
# Version PIN — do NOT track latest. paseo is pre-1.0; a floating install would
# drift the web-ui bundle and the depth4 anchor out from under us.
PASEO_VER="${AIRLOCK_PASEO_VERSION:-0.1.110}"

# nvm (if present) puts node/npm on PATH; the unit PATH is derived from what we
# resolve here, so per-box node locations never need to be hardcoded.
# shellcheck source=/dev/null
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 || true
require_cmd node npm systemctl tailscale python3

# The paseo daemon (and its node-pty) require node >= 20; node 18 fails at npm
# engine + runtime. Block older boxes explicitly (no silent failure).
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
[ "${NODE_MAJOR:-0}" -ge 20 ] 2>/dev/null \
  || die "paseo needs node >= 20 (found $(node --version 2>/dev/null)). Upgrade node on this box, then re-run."
NODE_BIN="$(dirname "$(readlink -f "$(command -v node)")")"

# Fixed, user-writable npm prefix owned by this installer. A box's default npm
# global prefix varies wildly (/usr = non-root EACCES; a private nvm/npm-global);
# pinning our own prefix makes the install deterministic and the daemon's paseo
# binary + module paths self-contained regardless of the box.
PASEO_PREFIX="$HOME/.npm-global"
NPM_GBIN="$PASEO_PREFIX/bin"
NPM_ROOT="$PASEO_PREFIX/lib/node_modules"
PASEO_BIN="$NPM_GBIN/paseo"
export PATH="$NPM_GBIN:$PATH"

# Unit PATH — npm global bin + provider CLI locations (claude=~/.local/bin,
# codex=~/.npm-global/bin) + node bin + system. Only existing dirs are added
# (box-to-box variation is harmless). The daemon spawns provider CLIs against
# this PATH — a PATH mismatch here is the #1 pilot gotcha (provider "not found").
UNIT_PATH=""
for d in "$NPM_GBIN" "$HOME/.local/bin" "$HOME/.npm-global/bin" "$NODE_BIN"; do
  case ":${UNIT_PATH}:" in *":${d}:"*) continue ;; esac   # de-dupe
  [ -d "$d" ] && UNIT_PATH="${UNIT_PATH}${d}:"
done
UNIT_PATH="${UNIT_PATH}/usr/local/bin:/usr/bin:/bin"

UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/airlock-paseo.service"

# Tracks whether anything requiring a restart changed this run. Kept 0 on an
# idempotent re-run so re-running the installer does NOT restart paseo and drop the
# owner's live agent sessions.
need_restart=0

# --- 1. provision paseo (version-pinned; idempotent) ---
if [ "$("$PASEO_BIN" --version 2>/dev/null || true)" = "$PASEO_VER" ]; then
  log "paseo ${PASEO_PKG}@${PASEO_VER} present (prefix=$PASEO_PREFIX)"
elif [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] npm i -g ${PASEO_PKG}@${PASEO_VER} (prefix=$PASEO_PREFIX)"
else
  log "npm i -g ${PASEO_PKG}@${PASEO_VER} (prefix=$PASEO_PREFIX)"
  # npm_config_prefix overrides the box default (e.g. /usr = non-root fails) so we
  # always land in the fixed user prefix.
  npm_config_prefix="$PASEO_PREFIX" npm i -g "${PASEO_PKG}@${PASEO_VER}" >/dev/null 2>&1 \
    || die "npm install failed: ${PASEO_PKG}@${PASEO_VER} (prefix=$PASEO_PREFIX)"
  [ -x "$PASEO_BIN" ] || die "paseo binary missing after install: $PASEO_BIN"
  [ "$("$PASEO_BIN" --version 2>/dev/null || true)" = "$PASEO_VER" ] \
    || die "paseo version mismatch (want ${PASEO_VER}, got $("$PASEO_BIN" --version 2>/dev/null))"
  need_restart=1   # freshly (re)installed the daemon -> restart to run it
fi

# --- 2. depth4 search patch (idempotent) ---
# paseo's add-project name search full-scans $HOME; on a large home it times out.
# Cap it to maxDepth 4 (workspace @files search is untouched). This edits paseo's
# own bundle, so it is an AGPL-3.0 derivative — see patches/README.md. The .patch
# in patches/ is the reference/re-derivation copy; we apply it via idempotent sed
# so a paseo version bump that moved the anchor warns loudly instead of silently
# skipping (fail-visible, not fail-silent).
SESSION_JS="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/server/session.js"
PATCH_LINE='                maxDepth: searchesWorkspace ? undefined : 4,'
PATCH_ANCHOR='confidentResultScanThreshold: searchesWorkspace ? undefined : 5000,'
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] apply depth4 search patch to $SESSION_JS (idempotent sed after anchor)"
elif [ ! -f "$SESSION_JS" ]; then
  log "warning: session.js not found ($SESSION_JS) — depth4 patch skipped"
elif grep -qF 'maxDepth: searchesWorkspace ? undefined : 4' "$SESSION_JS"; then
  log "depth4 search patch already applied"
elif grep -qF "$PATCH_ANCHOR" "$SESSION_JS"; then
  # Insert the maxDepth line right after the anchor (indentation preserved).
  sed -i "/$(printf '%s' "$PATCH_ANCHOR" | sed 's/[.[\*^$]/\\&/g')/a\\${PATCH_LINE}" "$SESSION_JS" \
    || die "depth4 patch sed failed"
  grep -qF 'maxDepth: searchesWorkspace ? undefined : 4' "$SESSION_JS" \
    || die "depth4 patch verify failed (not inserted after anchor)"
  node --check "$SESSION_JS" || die "depth4 patch produced invalid JS"
  need_restart=1   # bundle changed -> restart so the daemon loads the patched code
  log "depth4 search patch applied (add-project name search maxDepth 4)"
else
  log "warning: depth4 anchor not found (paseo version drift?) — search may be slow; see patches/depth4-search.patch"
fi

# --- 2b. Opus 5 model backport (idempotent) ---
# paseo's model list is hardcoded in its dist, so the version pinned above simply
# has no Opus 5 entry — it cannot appear in the web UI, and restarting the daemon
# changes nothing (a common misread: the UI looks alive because the gate is up).
# Backport the upstream 0.2.x entries into the pinned bundle. Another AGPL-3.0
# derivative — see patches/README.md.
# The model is actually executed by the Claude Code CLI on the daemon's PATH, so
# gate on the measured CLI version first: too old means skip (model never offered)
# rather than offer-then-fail at spawn time.
CLAUDE_MANIFEST_JS="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/server/agent/providers/claude/model-manifest.js"
OPUS5_PATCHER="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/claude-model-opus5.mjs"
OPUS5_MIN_CLI="2.1.219"
claude_cli_ver="$(PATH="$UNIT_PATH" command -v claude >/dev/null 2>&1 && PATH="$UNIT_PATH" claude --version 2>/dev/null | awk '{print $1}' || true)"
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] apply Opus 5 model backport to $CLAUDE_MANIFEST_JS (claude CLI >= ${OPUS5_MIN_CLI} required)"
elif [ ! -f "$CLAUDE_MANIFEST_JS" ]; then
  log "warning: model-manifest.js not found ($CLAUDE_MANIFEST_JS) — Opus 5 backport skipped"
elif [ ! -f "$OPUS5_PATCHER" ]; then
  log "warning: Opus 5 patcher not found ($OPUS5_PATCHER) — backport skipped"
elif [ -z "$claude_cli_ver" ]; then
  log "warning: cannot determine claude CLI version (unit PATH) — Opus 5 backport skipped"
elif [ "$(printf '%s\n%s\n' "$OPUS5_MIN_CLI" "$claude_cli_ver" | sort -V | head -1)" != "$OPUS5_MIN_CLI" ]; then
  log "warning: claude CLI ${claude_cli_ver} < ${OPUS5_MIN_CLI} — Opus 5 backport skipped (upgrade the CLI, then re-run)"
else
  o5_rc=0
  o5_out="$(node "$OPUS5_PATCHER" "$CLAUDE_MANIFEST_JS")" || o5_rc=$?
  case "$o5_rc" in
    10) log "Opus 5 model backport already applied" ;;
    20) log "Opus 5 anchor not found (paseo version drift — already ships Opus 5?) — backport skipped" ;;
    0)
      O5_TMP="${CLAUDE_MANIFEST_JS}.paseo-new.mjs"
      if node --check "$O5_TMP"; then
        mv "$O5_TMP" "$CLAUDE_MANIFEST_JS" || die "Opus 5 backport mv failed"
        need_restart=1   # bundle changed -> restart so the daemon serves the new list
        log "Opus 5 model backport applied (claude CLI ${claude_cli_ver}; default model = Opus 5)"
      else
        rm -f "$O5_TMP"
        die "Opus 5 backport produced invalid JS — not applied"
      fi
      ;;
    *) die "Opus 5 patcher error (rc=$o5_rc): $o5_out" ;;
  esac
fi

# --- 2c. prune superseded models (idempotent) ---
# The pinned manifest still lists Opus 4.7/4.6 and Sonnet 4.6; drop them so the
# picker is the handful people actually choose. Picker-only: the manifest is not
# on the execution path, so sessions pinned to a removed model keep running.
# No CLI version gate here — removing an entry cannot break a spawn.
PRUNE_PATCHER="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/claude-model-prune.mjs"
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] prune superseded models from $CLAUDE_MANIFEST_JS"
elif [ ! -f "$CLAUDE_MANIFEST_JS" ]; then
  :   # already warned by the Opus 5 step above
elif [ ! -f "$PRUNE_PATCHER" ]; then
  log "warning: model prune patcher not found ($PRUNE_PATCHER) — skipped"
else
  pr_rc=0
  pr_out="$(node "$PRUNE_PATCHER" "$CLAUDE_MANIFEST_JS")" || pr_rc=$?
  case "$pr_rc" in
    10) log "model prune already applied" ;;
    20) log "model prune skipped — $pr_out" ;;
    0)
      PR_TMP="${CLAUDE_MANIFEST_JS}.paseo-new.mjs"
      if node --check "$PR_TMP"; then
        mv "$PR_TMP" "$CLAUDE_MANIFEST_JS" || die "model prune mv failed"
        need_restart=1   # bundle changed -> restart so the daemon serves the new list
        log "model prune applied ($pr_out)"
      else
        rm -f "$PR_TMP"
        die "model prune produced invalid JS — not applied"
      fi
      ;;
    *) die "model prune patcher error (rc=$pr_rc): $pr_out" ;;
  esac
fi

# --- 3. tailnet FQDN (for the gate Host header + the daemon hostname allowlist) ---
# In dry-run, ts_fqdn may fail (no tailscale) — use a placeholder so the fragment
# still renders. In a real install a failing ts_fqdn fails closed (as intended).
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  FQDN="<your-box>.ts.net"
else
  FQDN="$(ts_fqdn)"
fi

# --- 4. systemd --user unit (loopback daemon; explicit PATH, HOME, XDG env) ---
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] write $UNIT (paseo daemon 127.0.0.1:${BACKEND_PORT}, PASEO_TRUSTED_PROXIES=127.0.0.1)"
else
  install -d "$UNIT_DIR"
  if write_if_changed "$UNIT" <<UNITEOF
[Unit]
Description=airlock-paseo — Paseo daemon (coding-agent orchestration + web UI) behind the owner gate
Documentation=https://github.com/getpaseo/paseo
After=default.target

[Service]
Type=simple
# Explicit PATH: npm global bin + provider CLI dirs + node + system. The daemon
# spawns provider CLIs against this PATH — a mismatch is the #1 pilot gotcha.
Environment=PATH=${UNIT_PATH}
# Provider CLI credential paths (claude=~/.claude, codex/gemini=~/.config).
Environment=HOME=${HOME}
Environment=XDG_CONFIG_HOME=${HOME}/.config
Environment=PASEO_HOME=${HOME}/.paseo
# Trust the reverse proxy (nginx@127.0.0.1) X-Forwarded-Proto https so the web UI
# uses wss:// (gate specific (1)/(2)). Without this the WebSocket fails behind TLS.
Environment=PASEO_TRUSTED_PROXIES=127.0.0.1
# DNS-rebinding host allowlist — must accept the Host the gate forwards (fqdn WITH
# the https port, gate specific (3)) plus localhost.
Environment=PASEO_HOSTNAMES=${FQDN},${FQDN}:${HTTPS_PORT},localhost
# Headless: no dictation/voice (avoids an unexpected ~600MB speech model download).
Environment=PASEO_DICTATION_ENABLED=false
Environment=PASEO_VOICE_MODE_ENABLED=false
# --foreground: Type=simple. --no-relay: no upstream relay outbound. --web-ui: the
# browser UI. --listen 127.0.0.1: loopback bind (the gate is the only ingress).
ExecStart=${PASEO_BIN} daemon start --foreground --no-relay --web-ui --listen 127.0.0.1:${BACKEND_PORT}
# always, not on-failure: the web UI's "restart daemon" is a websocket shutdown RPC
# that exits the worker cleanly (status 0) and expects a supervisor to bring it back.
# Under on-failure systemd reads that as an intended stop and leaves it dead — so the
# button permanently kills the daemon (the gate stays up, so it just looks hung).
# An explicit `systemctl --user stop` still stops it: always only covers self-exit.
Restart=always
RestartSec=3
# Backstop only (idle ~440M; runaway multi-session could OOM — watch in prod).
MemoryMax=8G
TasksMax=1024
NoNewPrivileges=yes

[Install]
WantedBy=default.target
UNITEOF
  then need_restart=1; fi
fi
airlock_run systemctl --user daemon-reload
airlock_run systemctl --user enable airlock-paseo.service
# Restart only when something changed (or the service is down / dry-run). An
# idempotent re-run with no changes must NOT restart — that would drop the owner's
# live paseo agent sessions.
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ] || [ "$need_restart" = 1 ] \
   || ! systemctl --user is-active --quiet airlock-paseo.service; then
  airlock_run systemctl --user restart airlock-paseo.service
else
  log "paseo unchanged and active — not restarting (preserves live sessions)"
fi

# Give the backend a bounded window to bind before the orchestrator renders nginx
# and smokes, so smoke doesn't race a still-booting daemon. Non-fatal: the
# orchestrator's smoke is the real gate.
if [ "${AIRLOCK_DRY_RUN:-0}" != 1 ]; then
  ready=0
  for _ in $(seq 1 30); do
    if ss -ltn 2>/dev/null | grep -qE "127\.0\.0\.1:${BACKEND_PORT}\b"; then ready=1; break; fi
    sleep 2
  done
  if [ "$ready" = 1 ]; then
    log "paseo backend listening on 127.0.0.1:${BACKEND_PORT}"
  else
    log "warning: paseo backend not listening after ~60s (smoke will verify; check: journalctl --user -u airlock-paseo)"
  fi
fi

# --- 5. nginx owner-gate fragment (written unconditionally; direct, +3 headers) ---
# Structure mirrors emit_owner_gate EXACTLY, plus the two gate-specific headers
# (X-Forwarded-Proto https + Host <fqdn>:<https_port>). $owner_ok and
# $connection_upgrade are the shared maps emitted at http level by render-nginx.sh.
frag="$CONFD/servers.d/paseo.conf"
install -d "$CONFD/servers.d"
{
  echo "# paseo owner gate — generated by apps/paseo/install.sh"
  echo "# Written directly (not via emit_owner_gate) so it can add the two headers"
  echo "# the paseo daemon requires behind TLS: X-Forwarded-Proto https and a Host"
  echo "# WITH the https port. See install.sh header + apps/paseo/README.md."
  sed -e "s/@@LISTEN@@/${GATE_PORT}/g" \
      -e "s|@@UPSTREAM@@|127.0.0.1:${BACKEND_PORT}|g" \
      -e "s|@@HOSTPORT@@|${FQDN}:${HTTPS_PORT}|g" \
      -e "s|@@WIDGET@@|${AIRLOCK_WEBROOT:-/opt/airlock/hub}/assets/airlock-return.js|g" <<'NGINX'
server {
    listen 127.0.0.1:@@LISTEN@@;
    server_name _;

    # paseo serves an upstream web UI we cannot edit, so the gate serves + injects
    # the shared "return to Airlock" widget (floating, bottom-right).
    location = /airlock-return.js { alias @@WIDGET@@; default_type application/javascript; add_header Cache-Control "no-cache" always; access_log off; }
@@BROWSE_LOC@@
    location / {
        if ($owner_ok = 0) { return 403; }
        proxy_pass http://@@UPSTREAM@@;
        proxy_http_version 1.1;
        # Host WITH the port — $host strips it and triggers a welcome-screen bug.
        proxy_set_header Host @@HOSTPORT@@;
        # This gate is a plain-http listener, so $scheme would be 'http'. Tell the
        # daemon it is behind TLS or the web UI opens ws:// and the socket dies.
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 86400s;
        # return-to-Airlock widget: uncompressed HTML so sub_filter applies (WS/JS
        # bundles are untouched — sub_filter only rewrites text/html).
        proxy_set_header Accept-Encoding "";
        sub_filter '</body>' '<script src="/airlock-return.js" data-anchor="bottom-right" defer></script></body>';
        sub_filter_once on;
    }
}
NGINX
} > "$frag"

# When browse-host is on, splice the owner-gated Level 2 live-view stream route in
# at the @@BROWSE_LOC@@ marker; otherwise the marker line is just removed. The route
# proxies the loopback stream server (browse-host sidecar). This gate guards
# per-location (not server-level), so the guard MUST be repeated here — without it
# the stream WS would be an unauthenticated hole. The static /browse-view-client.js
# (no trailing slash) is served by the daemon and does not collide with this prefix.
if [ "$BROWSE" = true ]; then
  bloc="$(mktemp)"
  sed -e "s|@@STREAM@@|127.0.0.1:${BROWSE_WS_PORT}|g" <<'BLOC' > "$bloc"

    location /browse-view/ {
        if ($owner_ok = 0) { return 403; }
        proxy_pass http://@@STREAM@@;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
    }
BLOC
  sed -i -e "/@@BROWSE_LOC@@/r $bloc" -e "/@@BROWSE_LOC@@/d" "$frag"
  rm -f "$bloc"
else
  sed -i "/@@BROWSE_LOC@@/d" "$frag"
fi
log "wrote nginx fragment: $frag${BROWSE:+ (browse=$BROWSE)}"

# --- 6. tailscale serve (https only — the web UI wants a secure context) ---
airlock_run sudo tailscale serve --bg --https="${HTTPS_PORT}" "http://127.0.0.1:${GATE_PORT}"

# --- 7. browse-host sidecar (config-gated; warn-only) ---
# Server-side browser panels for agents: a loopback WS client that registers a
# Playwright automation host with the daemon (Level 1 = agent browser_* tools) and
# a live-view stream + web-ui patch (Level 2 = the New-browser panel routed via the
# /browse-view/ gate location added above). Non-fatal on purpose: a chromium
# download or web-ui SHA-drift must never break the hub or the paseo daemon.
if [ "$BROWSE" = true ]; then
  BROWSE_INSTALL="$HERE/browse-host/install.sh"
  WEBUI_DIR="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/web-ui"
  if [ ! -f "$BROWSE_INSTALL" ]; then
    log "warning: browse=true but $BROWSE_INSTALL missing — skipped"
  elif [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
    log "[dry] bash $BROWSE_INSTALL (PASEO_WEBUI_DIR + FQDN + ports)"
  else
    log "installing browse-host sidecar (warn-only; downloads chromium on first run)"
    if PASEO_WEBUI_DIR="$WEBUI_DIR" \
       PASEO_BROWSE_FQDN="$FQDN" \
       PASEO_BACKEND_PORT="$BACKEND_PORT" \
       PASEO_BROWSE_STREAM_PORT="$BROWSE_WS_PORT" \
       PASEO_HTTPS_PORT="$HTTPS_PORT" \
       bash "$BROWSE_INSTALL"; then
      log "browse-host OK (agent browser_* + live-view panel)"
    else
      log "warning: browse-host install failed — agent browsing unavailable (hub + paseo daemon unaffected). Retry: bash $BROWSE_INSTALL"
    fi
  fi
fi

# NOTE: smoke runs from the orchestrator AFTER nginx is rendered + reloaded (the
# gate isn't live until then). See install/airlock-install.sh.
log "paseo installed (owner: ${AIRLOCK_OWNER}${BROWSE:+, browse=$BROWSE})"
