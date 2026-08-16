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
# ABI (D5): prefer the orchestrator-supplied AIRLOCK_ROOT/AIRLOCK_APP_DIR/
# AIRLOCK_APP_ID, falling back to $0-relative computation for a standalone
# invocation (a test harness that runs this script directly).
ROOT="${AIRLOCK_ROOT:-$(cd "$HERE/../.." && pwd)}"
HERE="${AIRLOCK_APP_DIR:-$HERE}"
AIRLOCK_APP_ID="${AIRLOCK_APP_ID:-paseo}"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"
# shellcheck source=/dev/null
. "$HERE/render.sh"
# shellcheck source=/dev/null
. "$HERE/state.sh"

airlock_load paseo
# Return-widget menu attributes. With devterm installed the widget's tap opens a small
# menu (return to Airlock / subscription accounts) instead of navigating straight away —
# this app owns the whole screen, so the account panel has no other way in. Without
# devterm there is nothing to open, so the attributes stay empty and a tap navigates.
WIDGET_MENU_ATTRS=""
PANEL_URL="$(airlock_panel_url || true)"
if [ -n "$PANEL_URL" ]; then
  WIDGET_MENU_ATTRS=" data-menu=\"1\" data-panel=\"${PANEL_URL}\""
fi

GATE_PORT="${AIRLOCK_PASEO_GATE_PORT:?}"
BACKEND_PORT="${AIRLOCK_PASEO_BACKEND_PORT:?}"
HTTPS_PORT="${AIRLOCK_PASEO_HTTPS_PORT:?}"
CONFD="${AIRLOCK_CONFD:-/etc/airlock/nginx}"
# browse-host (config-gated). When BROWSE=true we add the /browse-view/ stream
# route to the gate and run browse-host/install.sh at the end (warn-only).
BROWSE="${AIRLOCK_PASEO_BROWSE:-false}"
BROWSE_WS_PORT="${AIRLOCK_PASEO_BROWSE_WS_PORT:-6768}"

# ---- Resource backstop, sized from this box's RAM ----
# The unit used to carry a flat MemoryMax=8G with no MemoryHigh. On a big box that
# is a silent ceiling (sessions die at 8G on a 32GiB machine); on a small one the
# same number is most of the machine. Derive it instead: cgroup memory.max first
# (a container's own limit — /proc/meminfo leaks the host's total inside LXC and
# would over-size the cap), MemTotal as the fallback.
# Reserve = max(4GiB, 15%) for the OS and every other app on the box; MemoryHigh
# = ~89% of max so there is a throttle band below the cliff (see render.sh).
# AIRLOCK_PASEO_MEM_CAP_BYTES is a test seam (install/test-render-parity.sh pins
# it so the golden does not bake in the RAM of whichever box ran the suite). It is
# not a supported knob — the point of this block is that no box has to be told.
_cap="${AIRLOCK_PASEO_MEM_CAP_BYTES:-$(cat /sys/fs/cgroup/memory.max 2>/dev/null || true)}"
case "$_cap" in ''|max|*[!0-9]*) _cap=$(( $(awk '/^MemTotal:/{print $2}' /proc/meminfo) * 1024 )) ;; esac
_cap_gib=$(( _cap / 1024 / 1024 / 1024 ))
_reserve_gib=$(( (_cap_gib * 15 + 99) / 100 ))
[ "$_reserve_gib" -lt 4 ] && _reserve_gib=4
_memmax_gib=$(( _cap_gib - _reserve_gib ))
# The pids backstop defaults to the box maximum (owner decision, 2026-08-07):
# `infinity` on the unit defers to the enclosing user slice, which is the real
# ceiling and differs per box. A finite value here puts a unit-level backstop
# back — see the comment above TasksMax in render.sh for what that trades.
PASEO_TASKSMAX="${AIRLOCK_PASEO_TASKS_MAX:-infinity}"
# Below the reserve there is nothing left to back off to, and the derivation
# inverts: at 4 GiB the reserve is the whole box and `usable` is 0. This used to
# be papered over with `[ "$_memmax_gib" -lt 2 ] && _memmax_gib=2`, which handed
# a 4 GiB box half of itself and a 2 GiB box all of itself — a number that reads
# as a limit and is not one. Owner decision (2026-08-06): say why and refuse,
# and let an operator who means it override explicitly. The override renders
# `infinity` rather than a flattering figure, because "no memory backstop" is
# what is true. TasksMax is unaffected by the memory decision, but note that it
# now defaults to infinity too, so an overridden box has no unit-level backstop
# of either kind — only the enclosing user slice.
_min_memmax_gib=2
if [ "$_memmax_gib" -lt "$_min_memmax_gib" ]; then
  if [ "${AIRLOCK_PASEO_ALLOW_UNBACKED_MEM:-0}" = 1 ]; then
    log "WARNING: paseo memory backstop disabled by explicit override AIRLOCK_PASEO_ALLOW_UNBACKED_MEM=1 \
— this unit gets no memory limit at all: cap=${_cap} bytes (${_cap_gib} GiB), reserve=${_reserve_gib} GiB, \
usable=${_memmax_gib} GiB; rendering MemoryMax=infinity and MemoryHigh=infinity. TasksMax=${PASEO_TASKSMAX} \
— with the default that leaves the enclosing user slice as the only limit of any kind on this unit."
    PASEO_MEMMAX=infinity
    PASEO_MEMHIGH=infinity
  else
    die "paseo install refused: this box is too small to give paseo a memory slice that means anything. \
cap=${_cap} bytes (${_cap_gib} GiB), reserve=${_reserve_gib} GiB, usable=${_memmax_gib} GiB, \
minimum usable=${_min_memmax_gib} GiB. Writing a MemoryMax here would name a limit the unit does not have. \
To install anyway with no memory backstop (TasksMax still applies), set AIRLOCK_PASEO_ALLOW_UNBACKED_MEM=1."
  fi
else
  _memhigh_gib=$(( _memmax_gib * 8 / 9 ))
  PASEO_MEMMAX="${_memmax_gib}G"
  PASEO_MEMHIGH="${_memhigh_gib}G"
fi

PASEO_PKG="@getpaseo/cli"
# Version PIN — do NOT track latest. paseo is pre-1.0; a floating install would
# drift the web-ui bundle and the depth4 anchor out from under us.
PASEO_VER="${AIRLOCK_PASEO_VERSION:-0.2.5}"

# nvm (if present) puts node/npm on PATH; the unit PATH is derived from what we
# resolve here, so per-box node locations never need to be hardcoded.
airlock_load_nvm
require_cmd node npm systemctl tailscale python3 ss sudo

# The paseo daemon (and its node-pty) require node >= 20; node 18 fails at npm
# engine + runtime. Block older boxes explicitly (no silent failure).
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
[ "${NODE_MAJOR:-0}" -ge 20 ] 2>/dev/null \
  || die "paseo needs node >= 20 (found $(node --version 2>/dev/null)). Upgrade node on this box, then re-run."

# --- snap-wrapped node vs NoNewPrivileges (owner decision, 2026-08-07) ---
#
# /snap/bin/node is a symlink to /usr/bin/snap, which re-executes the real
# interpreter through the setuid-root snap-confine. `NoNewPrivileges=yes` neuters
# setuid; snap swallows the failure. The unit then dies with status=1 and writes
# nothing at all — 4,242 restarts of airlock-paseo on 2026-08-07 with a journal
# containing only the restart lines. #77 did not cause this, it revealed it:
# before /snap/bin was on the unit PATH the same unit died at exit 127 instead.
#
# So: detect it, refuse, and say what was measured rather than what was assumed.
# The escape hatch turns the directive off FOR THIS UNIT and renders why, in the
# unit, where the next person to read it will be. It does not weaken code-server
# or orca, which never see this variable.
#
# Placed here and not in install/preflight.sh on purpose: packaged paseo's
# preflight deliberately does not load nvm and leaves runtime selection to this
# script (install/preflight.sh:193-199), so a central check would fire on boxes
# where nvm supplies a perfectly good native node. This runs after
# airlock_load_nvm and the version gate, and before the first npm call, file
# write or systemctl — the same position, and the same shape, as the memory
# refusal above.
PASEO_NNP_BLOCK="NoNewPrivileges=yes"
_node_found="$(command -v node 2>/dev/null || true)"
_node_real="$(readlink -f -- "$_node_found" 2>/dev/null || true)"
_node_runtime="$(node -p 'process.execPath' 2>/dev/null || true)"
_snap_probes="$(airlock_snap_probe "$_node_found" "$_node_real" "$_node_runtime")" || true
if [ -n "$_snap_probes" ]; then
  _snap_detail="probes=[${_snap_probes}] found=${_node_found:-<none>} \
resolved=${_node_real:-<none>} runtime=${_node_runtime:-<unreadable>}"
  if [ "${AIRLOCK_ALLOW_SNAP_NODE:-0}" = 1 ]; then
    log "WARNING: paseo is being installed against a snap-wrapped node by explicit override \
AIRLOCK_ALLOW_SNAP_NODE=1 — ${_snap_detail}. NoNewPrivileges is being turned OFF for the \
airlock-paseo unit only, because snap's setuid-root re-exec cannot survive it. Nothing else \
on this box changes; code-server and orca keep the directive."
    # printf -v, not a heredoc: this text ends up inside apps/paseo/render.sh's
    # UNITEOF body, which is unquoted. Assembling it there would put a shell
    # command in prose back where command substitution happens. A variable's
    # value is not re-scanned, so built here it arrives literally.
    printf -v PASEO_NNP_BLOCK '%s\n%s\n%s\n%s\n%s' \
      "# NoNewPrivileges is deliberately OFF for this unit." \
      "# node on this box is behind a snap wrapper (${_snap_detail})." \
      "# snap re-executes through the setuid-root snap-confine, which NoNewPrivileges" \
      "# neuters; the unit then fails with status=1 and no output at all." \
      "NoNewPrivileges=no"
  else
    die "paseo install refused: node on this box is behind a snap wrapper, and this unit \
sets NoNewPrivileges=yes. ${_snap_detail}. snap re-executes the real interpreter through the \
setuid-root snap-confine, which NoNewPrivileges neuters, and snap reports nothing — the unit \
crash-loops with status=1 and an empty journal (measured 2026-08-07, 4,242 restarts). \
Install node from a non-snap source (nvm, or the NodeSource apt repository) and re-run. \
To install anyway with NoNewPrivileges turned off for the airlock-paseo unit only, set \
AIRLOCK_ALLOW_SNAP_NODE=1."
  fi
fi

# Every directory node can be found through — see airlock_cmd_dirs in
# install/lib.sh for why the resolved path alone is not enough (snap).
NODE_DIRS="$(airlock_cmd_dirs node)"

# Fixed, user-writable npm prefix owned by this installer. A box's default npm
# global prefix varies wildly (/usr = non-root EACCES; a private nvm/npm-global);
# pinning our own prefix makes the install deterministic and the daemon's paseo
# binary + module paths self-contained regardless of the box.
PASEO_PREFIX="$HOME/.npm-global"
NPM_GBIN="$PASEO_PREFIX/bin"
NPM_ROOT="$PASEO_PREFIX/lib/node_modules"
PASEO_BIN="$NPM_GBIN/paseo"
export PATH="$NPM_GBIN:$PATH"

# ExecStartPre stale-pidfile guard (apps/paseo/paseo-clear-stale-pid.py) — see that
# script's header. In-repo path, same convention as devterm's GATE_PY.
STALE_PID_GUARD="$HERE/paseo-clear-stale-pid.py"
PY="$(command -v python3)"

# Unit PATH — npm global bin + provider CLI locations (claude=~/.local/bin,
# codex=~/.npm-global/bin) + node bin + system. The daemon spawns provider CLIs
# against this PATH — a mismatch here is the #1 pilot gotcha (provider "not found").
#
# Every entry is added whether or not it exists YET, and that "yet" is the whole
# point. This used to filter on [ -d "$d" ], but $NPM_GBIN is created by the
# `npm i -g` further down, and the agent CLIs land in these directories only when
# the user installs them — which is normally AFTER Airlock. So on a first install
# the unit's PATH silently dropped the very directory this installer was about to
# populate, plus wherever claude/codex would arrive, and paseo came up with a UI and
# no working providers. A directory that does not exist costs a PATH entry nothing;
# a missing one costs the gotcha the comment above warns about.
UNIT_PATH=""
# shellcheck disable=SC2086  # NODE_DIRS is newline-separated and deliberately split
for d in "$NPM_GBIN" "$HOME/.local/bin" "$HOME/.npm-global/bin" $NODE_DIRS; do
  case ":${UNIT_PATH}:" in *":${d}:"*) continue ;; esac   # de-dupe
  UNIT_PATH="${UNIT_PATH}${d}:"
done
UNIT_PATH="${UNIT_PATH}/usr/local/bin:/usr/bin:/bin"

UNIT_DIR="$HOME/.config/systemd/user"
# AIRLOCK_RENDER_DIR: harness-only destination-root override (highest
# priority). Redirects only where render output lands — install/lib.sh
# fail-closes if this is set without AIRLOCK_DRY_RUN=1, since real system
# mutations (systemctl, sudo tailscale serve, and orca's own sudo nft/
# systemctl calls) are gated on dry-run alone, not on this variable.
if [ -n "${AIRLOCK_RENDER_DIR:-}" ]; then
  CONFD="$AIRLOCK_RENDER_DIR/confd"
  UNIT_DIR="$AIRLOCK_RENDER_DIR/units"
fi
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
  # Both streams used to go to /dev/null, so this die() named the package and
  # nothing else — the operator got a fatal error with no cause. See install/lib.sh.
  airlock_quiet env npm_config_prefix="$PASEO_PREFIX" npm i -g "${PASEO_PKG}@${PASEO_VER}" \
    || die "npm install failed: ${PASEO_PKG}@${PASEO_VER} (prefix=$PASEO_PREFIX) — npm output above"
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

# The pinned manifest — the file the prune step below edits. Declared here rather
# than beside its only user because it has already outlived one: an Opus 5 backport
# step owned this declaration until the pin reached a version whose manifest ships
# Opus 5, and under `set -u` removing that step would have taken the prune with it.
CLAUDE_MANIFEST_JS="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/server/agent/providers/claude/model-manifest.js"

# --- 2c. prune superseded models (idempotent) ---
# The pinned manifest still lists Opus 4.7/4.6 and Sonnet 4.6; drop them so the
# picker is the handful people actually choose. Picker-only: the manifest is not
# on the execution path, so sessions pinned to a removed model keep running.
# No CLI version gate here — removing an entry cannot break a spawn.
PRUNE_PATCHER="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/claude-model-prune.mjs"
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] prune superseded models from $CLAUDE_MANIFEST_JS"
elif [ ! -f "$CLAUDE_MANIFEST_JS" ]; then
  # This used to be a bare `:` because the Opus 5 step above warned for the same
  # condition. That step is gone, and a missing manifest is the signal that upstream
  # moved its dist layout — the last thing to swallow.
  log "warning: model-manifest.js not found ($CLAUDE_MANIFEST_JS) — model prune skipped (paseo dist layout changed?)"
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

# --- 2d. persist pasted images (idempotent) ---
# An image pasted into the web UI reaches the model only as an inline base64 vision block:
# the model can see it, but there is no file, so the agent's Read tool has no path to open
# and "look at this screenshot, then fix the file" dead-ends. The patch keeps the inline
# block and additionally writes the bytes under the session cwd, naming the path in a
# sibling text block. No CLI version gate: this changes what the provider sends, not which
# model runs.
IMGPERSIST_PATCHER="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/image-attachments-persist.mjs"
CLAUDE_AGENT_JS="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/server/agent/providers/claude/agent.js"
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] apply pasted-image persistence to $CLAUDE_AGENT_JS"
elif [ ! -f "$CLAUDE_AGENT_JS" ]; then
  log "warning: claude agent.js not found ($CLAUDE_AGENT_JS) — pasted-image persistence skipped"
elif [ ! -f "$IMGPERSIST_PATCHER" ]; then
  log "warning: pasted-image patcher not found ($IMGPERSIST_PATCHER) — skipped"
else
  ip_rc=0
  ip_out="$(node "$IMGPERSIST_PATCHER" "$CLAUDE_AGENT_JS")" || ip_rc=$?
  case "$ip_rc" in
    10) log "pasted-image persistence already applied" ;;
    20) log "pasted-image anchors not found (paseo version drift) — skipped" ;;
    0)
      IP_TMP="${CLAUDE_AGENT_JS}.paseo-new.mjs"
      if node --check "$IP_TMP"; then
        mv "$IP_TMP" "$CLAUDE_AGENT_JS" || die "pasted-image persistence mv failed"
        need_restart=1   # bundle changed -> restart so the daemon runs the patched provider
        log "pasted-image persistence applied (saves under <cwd>/.paseo-attachments/)"
      else
        rm -f "$IP_TMP"
        die "pasted-image persistence produced invalid JS — not applied"
      fi
      ;;
    *) die "pasted-image patcher error (rc=$ip_rc): $ip_out" ;;
  esac
fi

# --- 2e. orphan process guard (idempotent; claude + codex providers) ---
# paseo leaks the agent processes it spawns. Both providers track exactly one live
# child (`this.childProcess` / `this.client`) and kill it behind an `if (handle)`
# with no else branch, and neither honours the closed flag on its spawn entry point
# (ensureQuery / connect). So a control-plane call landing during or after close —
# setMode, setModel, listCommands, revertFiles, a codex reconnect, or just the
# in-flight spawn finishing late — starts a REPLACEMENT process on a session nothing
# will ever close again. It then runs until the box is rebooted, and close() reports
# success because at that instant there genuinely was nothing to kill. Measured on
# Pilot box 2026-08-05: 18 orphans, 2.9G RSS + 1.9G swap.
# The patch makes ownership a Set (so a replaced handle is still terminated), gates
# both spawn entry points on the closed flag, terminates late arrivals on the spot,
# and warns at level 40 — the surrounding session_close lines are logger.trace, which
# the daemon's info-level logger never emits, so this class of leak was unobservable.
ORPHANGUARD_PATCHER="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/orphan-process-guard.mjs"
ORPHANGUARD_TEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/orphan-process-guard.test.mjs"
CODEX_AGENT_JS="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/server/agent/providers/codex-app-server-agent.js"
apply_orphan_guard() {  # <mode> <target-js>
  local mode="$1" target="$2" og_rc=0 og_out og_tmp
  if [ ! -f "$target" ]; then
    log "warning: $mode provider not found ($target) — orphan guard skipped"
    return 0
  fi
  og_out="$(node "$ORPHANGUARD_PATCHER" "$mode" "$target")" || og_rc=$?
  case "$og_rc" in
    10) log "orphan guard already applied ($mode)" ;;
    20) log "orphan guard anchors missing or ambiguous for $mode (paseo version drift) — skipped" ;;
    0)
      og_tmp="${target}.paseo-new.mjs"
      if node --check "$og_tmp"; then
        mv "$og_tmp" "$target" || die "orphan guard mv failed ($mode)"
        need_restart=1   # bundle changed -> restart so the daemon runs the patched provider
        log "orphan guard applied ($mode)"
      else
        rm -f "$og_tmp"
        die "orphan guard produced invalid JS ($mode) — not applied"
      fi
      ;;
    *) die "orphan guard patcher error ($mode rc=$og_rc): $og_out" ;;
  esac
}
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] apply orphan process guard to $CLAUDE_AGENT_JS and $CODEX_AGENT_JS"
elif [ ! -f "$ORPHANGUARD_PATCHER" ]; then
  log "warning: orphan guard patcher not found ($ORPHANGUARD_PATCHER) — skipped"
else
  apply_orphan_guard claude "$CLAUDE_AGENT_JS"
  apply_orphan_guard codex  "$CODEX_AGENT_JS"
  # Syntax-valid is not the same as behaving. This check slices the two guard methods
  # back out of the installed bundle and drives them against fake children, so a patch
  # that applied but reassembled wrongly fails the install instead of shipping quietly.
  if [ -f "$ORPHANGUARD_TEST" ] && grep -q 'paseo-orphan-guard' "$CLAUDE_AGENT_JS" 2>/dev/null; then
    node "$ORPHANGUARD_TEST" "$CLAUDE_AGENT_JS" >/dev/null 2>&1 \
      || die "orphan guard behaviour check failed — the patched bundle does not behave as intended"
    log "orphan guard behaviour check passed"
  fi
fi

# --- 2f. process-group sweep (idempotent; layers on 2e — order matters) ---
# The one leak 2e deliberately left open: when the agent LEADER exits before we
# terminate it, terminateWithTreeKill returns "already-exited" and stops — and by then
# the leader's MCP children have been reparented, so a ppid-walking tree-kill can no
# longer find them. They survive as orphans.
# A process group outlives its leader, so killing the GROUP reaches them. Controlled
# experiment (pilot box, 2026-08-06): detached=false -> grandchild orphaned and
# kill(-pid) returns ESRCH (harmless); detached=true -> kill(-pgid) kills it. In both
# cases the child stays in airlock-paseo.service's cgroup, so KillMode=control-group still
# sweeps everything on restart. codex already spawns its app-server detached upstream
# and merely never killed the group; claude needed both halves.
# 🔴 This must run AFTER 2e: its claude-agent anchors are text 2e introduces. If 2e was
# skipped, this exits 20 and skips too — never half a fix.
PGROUP_PATCHER="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/orphan-process-group.mjs"
PGROUP_TEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/orphan-process-group.test.mjs"
CLAUDE_QUERY_JS="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/server/agent/providers/claude/query.js"
CODEX_TRANSPORT_JS="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/server/agent/providers/codex/app-server-transport.js"
apply_pgroup() {  # <mode> <target-js>
  local mode="$1" target="$2" pg_rc=0 pg_out pg_tmp
  if [ ! -f "$target" ]; then
    log "warning: $mode target not found ($target) — process-group sweep skipped"
    return 0
  fi
  pg_out="$(node "$PGROUP_PATCHER" "$mode" "$target")" || pg_rc=$?
  case "$pg_rc" in
    10) log "process-group sweep already applied ($mode)" ;;
    20) log "process-group sweep anchors missing for $mode (drift, or 2e skipped) — skipped" ;;
    0)
      pg_tmp="${target}.paseo-new.mjs"
      if node --check "$pg_tmp"; then
        mv "$pg_tmp" "$target" || die "process-group sweep mv failed ($mode)"
        need_restart=1
        log "process-group sweep applied ($mode)"
      else
        rm -f "$pg_tmp"
        die "process-group sweep produced invalid JS ($mode) — not applied"
      fi
      ;;
    *) die "process-group patcher error ($mode rc=$pg_rc): $pg_out" ;;
  esac
}
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] apply process-group sweep to claude agent/query and codex transport"
elif [ ! -f "$PGROUP_PATCHER" ]; then
  log "warning: process-group patcher not found ($PGROUP_PATCHER) — skipped"
else
  apply_pgroup claude-agent    "$CLAUDE_AGENT_JS"
  apply_pgroup claude-query    "$CLAUDE_QUERY_JS"
  apply_pgroup codex-transport "$CODEX_TRANSPORT_JS"
  # Drives the shipped sweep against REAL detached processes: spawns a leader with a
  # child, kills only the leader, and asserts the sweep reaps the survivor. A syntax
  # check cannot tell us that, and this is the half of the fix that signals other
  # processes — it should never ship unverified.
  if [ -f "$PGROUP_TEST" ] && grep -q 'paseo-process-group' "$CLAUDE_AGENT_JS" 2>/dev/null; then
    node "$PGROUP_TEST" "$CLAUDE_AGENT_JS" >/dev/null 2>&1 \
      || die "process-group behaviour check failed — the patched bundle does not reap descendants as intended"
    log "process-group behaviour check passed"
  fi
fi

# --- 2g. credential key preservation (idempotent) ---
# The quota fetchers refresh the OAuth token when the usage API answers 401/403 and
# write it back through a zod z.object — which STRIPS unknown keys at every level. So
# the write-back does not update the credential file, it replaces it with the four
# fields the schema names. ~/.claude/.credentials.json loses claudeAiOauth.expiresAt /
# refreshTokenExpiresAt / scopes and the top-level _meta block (email/org/kind) our
# account switcher reads; ~/.codex/auth.json loses tokens.id_token and the top-level
# auth_mode / OPENAI_API_KEY / last_refresh (the field that says whether a green Codex
# panel is backed by a live token). Both write paths sit inside a bare `catch {}`, so
# the loss is silent — the next reader just finds a record with holes in it.
# The patch merges the refreshed token fields into the object parsed from disk instead
# of into zod's output. Data preservation only: refresh timing is untouched.
CREDPRESERVE_PATCHER="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/credential-key-preservation.mjs"
CREDPRESERVE_TEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/patches" 2>/dev/null && pwd || true)/credential-key-preservation.test.mjs"
QUOTA_PROVIDERS="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/services/quota-fetcher/providers"
apply_cred_preserve() {  # <mode> <target-js>
  local mode="$1" target="$2" cp_rc=0 cp_out cp_tmp
  if [ ! -f "$target" ]; then
    log "warning: $mode quota provider not found ($target) — credential key preservation skipped"
    return 0
  fi
  cp_out="$(node "$CREDPRESERVE_PATCHER" "$mode" "$target")" || cp_rc=$?
  case "$cp_rc" in
    10) log "credential key preservation already applied ($mode)" ;;
    20) log "credential key preservation anchors missing or ambiguous for $mode (paseo version drift) — skipped" ;;
    0)
      cp_tmp="${target}.paseo-new.mjs"
      if node --check "$cp_tmp"; then
        mv "$cp_tmp" "$target" || die "credential key preservation mv failed ($mode)"
        need_restart=1   # bundle changed -> restart so the daemon runs the patched fetcher
        log "credential key preservation applied ($mode)"
      else
        rm -f "$cp_tmp"
        die "credential key preservation produced invalid JS ($mode) — not applied"
      fi
      ;;
    *) die "credential key preservation patcher error ($mode rc=$cp_rc): $cp_out" ;;
  esac
}
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] apply credential key preservation to $QUOTA_PROVIDERS/{claude,codex}.js"
elif [ ! -f "$CREDPRESERVE_PATCHER" ]; then
  log "warning: credential key preservation patcher not found ($CREDPRESERVE_PATCHER) — skipped"
else
  apply_cred_preserve claude "$QUOTA_PROVIDERS/claude.js"
  apply_cred_preserve codex  "$QUOTA_PROVIDERS/codex.js"
  # Syntax-valid is not the same as key-preserving. This check slices each save method
  # back out of the installed bundle and drives it against an in-memory fs and invented
  # credential fixtures, so a patch that applied but reassembled wrongly fails the install
  # instead of quietly shipping a writer that still eats fields. It never reads a real
  # credential file.
  if [ -f "$CREDPRESERVE_TEST" ]; then
    for cp_mode in claude codex; do
      if grep -q 'paseo-cred-preserve' "$QUOTA_PROVIDERS/${cp_mode}.js" 2>/dev/null; then
        node "$CREDPRESERVE_TEST" "$cp_mode" "$QUOTA_PROVIDERS/${cp_mode}.js" >/dev/null 2>&1 \
          || die "credential key preservation behaviour check failed ($cp_mode) — the patched bundle still drops fields"
        log "credential key preservation behaviour check passed ($cp_mode)"
      fi
    done
  fi
fi

# --- 2h. strip ambient OPENAI_API_KEY from Codex spawns (idempotent) ---
# The unit boundary below removes a manager/session-wide OPENAI_API_KEY from the
# daemon. Defense in depth is still required at the actual Codex spawn because
# Paseo composes runtime and launch overlays there. The patch adds a final
# undefined overlay unless runtimeSettings explicitly carries a non-empty key;
# custom OpenAI-compatible runtimes therefore keep their intentional key while
# an ambient or incidental launch overlay cannot silently switch Codex to billing.
CODEX_KEY_PATCHER="$HERE/patches/codex-strip-ambient-openai-key.mjs"
CODEX_KEY_TEST="$HERE/patches/codex-strip-ambient-openai-key.test.mjs"
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] strip ambient OPENAI_API_KEY at Codex spawn in $CODEX_AGENT_JS"
elif [ ! -f "$CODEX_AGENT_JS" ]; then
  die "Codex provider not found ($CODEX_AGENT_JS) — cannot enforce ambient OPENAI_API_KEY isolation"
elif [ ! -f "$CODEX_KEY_PATCHER" ]; then
  die "Codex ambient-key patcher not found ($CODEX_KEY_PATCHER) — cannot enforce ambient OPENAI_API_KEY isolation"
else
  ck_rc=0
  ck_out="$(node "$CODEX_KEY_PATCHER" "$CODEX_AGENT_JS")" || ck_rc=$?
  case "$ck_rc" in
    10) log "Codex ambient OPENAI_API_KEY spawn guard already applied" ;;
    20) die "Codex ambient-key anchors missing or ambiguous (paseo version drift) — refusing an unguarded install" ;;
    0)
      CK_TMP="${CODEX_AGENT_JS}.paseo-new.mjs"
      if node --check "$CK_TMP"; then
        mv "$CK_TMP" "$CODEX_AGENT_JS" || die "Codex ambient-key guard mv failed"
        need_restart=1
        log "Codex ambient OPENAI_API_KEY spawn guard applied"
      else
        rm -f "$CK_TMP"
        die "Codex ambient-key guard produced invalid JS — not applied"
      fi
      ;;
    *) die "Codex ambient-key patcher error (rc=$ck_rc): $ck_out" ;;
  esac
  if [ -f "$CODEX_KEY_TEST" ] && grep -q 'paseo-codex-strip-ambient-openai-key' "$CODEX_AGENT_JS" 2>/dev/null; then
    node "$CODEX_KEY_TEST" "$CODEX_AGENT_JS" >/dev/null 2>&1 \
      || die "Codex ambient-key runtime check failed — patched spawn does not preserve only explicit runtime keys"
    log "Codex ambient-key runtime check passed"
  fi
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
# AIRLOCK_RENDER_DIR forces this write branch even under AIRLOCK_DRY_RUN=1 — see
# install/lib.sh's fail-closed guard (RENDER_DIR without DRY_RUN=1 never reaches
# this line) and apps/feedback/install.sh's identical comment.
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ] && [ -z "${AIRLOCK_RENDER_DIR:-}" ]; then
  # The PATH is printed because it is the thing that goes wrong: when a provider CLI
  # is "not found" at spawn time, this line is the answer, and a preview should show
  # it rather than make someone read the generated unit.
  log "[dry] write $UNIT (paseo daemon 127.0.0.1:${BACKEND_PORT}, PASEO_TRUSTED_PROXIES=127.0.0.1)"
  log "[dry]   unit PATH=${UNIT_PATH}"
else
  install -d "$UNIT_DIR"
  if render_paseo_unit "$UNIT_PATH" "$HOME" "$FQDN" "$HTTPS_PORT" "$PASEO_BIN" "$BACKEND_PORT" \
       "$PY" "$STALE_PID_GUARD" "$PASEO_MEMMAX" "$PASEO_MEMHIGH" "$PASEO_TASKSMAX" "$PASEO_NNP_BLOCK" \
     | write_if_changed "$UNIT"
  then need_restart=1; fi
fi
# Read this BEFORE daemon-reload clears it. NeedDaemonReload=yes means an earlier
# deployment wrote unit bytes but did not finish its restart transaction.
prior_daemon_reload=no
if [ "${AIRLOCK_DRY_RUN:-0}" != 1 ] \
   && paseo_unit_needs_daemon_reload airlock-paseo.service; then
  prior_daemon_reload=yes
  log "airlock-paseo.service reports NeedDaemonReload=yes — recovery restart required"
fi
airlock_run systemctl --user daemon-reload
airlock_run systemctl --user enable airlock-paseo.service
if [ "${AIRLOCK_DRY_RUN:-0}" != 1 ]; then
  warn_paseo_linger "${USER:-}"
fi
# Restart only when something changed (or the service is down / dry-run). An
# idempotent re-run with no changes must NOT restart — that would drop the owner's
# live paseo agent sessions.
unit_active=inactive
if [ "${AIRLOCK_DRY_RUN:-0}" != 1 ] \
   && systemctl --user is-active --quiet airlock-paseo.service; then
  unit_active=active
fi
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ] \
   || paseo_should_restart "$need_restart" "$prior_daemon_reload" "$unit_active"; then
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
WIDGET="${AIRLOCK_WEBROOT:-/opt/airlock/hub}/assets/airlock-return.js"

# [branding] icon_ring: paseo's web UI is upstream (we cannot edit its <link rel=icon>),
# so the gate answers /favicon.ico itself with a ringed copy of the paseo mark. Same
# per-location guard as every other route here — the server has no server-level `if`.
ICON_LOC_BODY=""
if [ -n "${AIRLOCK_ICON_RING:-}" ] && [ -f "$HERE/paseo.png" ]; then
  install -d "$CONFD/paseo"
  ring_icon_svg "$AIRLOCK_ICON_RING" "$HERE/paseo.png" > "$CONFD/paseo/favicon-ring.svg"
  chmod 644 "$CONFD/paseo/favicon-ring.svg"
  # /favicon.ico alone is invisible once the app boots: the web UI SWAPS the tab
  # icon at runtime (light|dark x idle|running|attention, each a hashed asset), so
  # the <link rel=icon> the browser ends up with is never the one above. Ring each
  # upstream variant under its own hashed name and serve those too — the state
  # signal (running/attention) survives, it just wears the ring. Regenerated every
  # install, so a paseo bump that rehashes the assets self-heals.
  WEBUI_IMG="$NPM_ROOT/${PASEO_PKG}/node_modules/@getpaseo/server/dist/server/web-ui/assets/assets/images"
  ring_n=0
  if [ -d "$WEBUI_IMG" ]; then
    install -d "$CONFD/paseo/icons"
    for f in "$WEBUI_IMG"/favicon-*.png; do
      [ -e "$f" ] || continue
      b="$(basename "$f" .png)"
      ring_icon_svg "$AIRLOCK_ICON_RING" "$f" > "$CONFD/paseo/icons/${b}.svg"
      chmod 644 "$CONFD/paseo/icons/${b}.svg"
      ring_n=$((ring_n + 1))
    done
  fi
  ICON_LOC_BODY="$(render_paseo_icon_favicon "$CONFD")"
  if [ "$ring_n" -gt 0 ]; then
    ICON_LOC_BODY="$ICON_LOC_BODY
$(render_paseo_icon_variants "$CONFD")"
  fi
  log "gate favicon ringed (${AIRLOCK_ICON_RING}; ${ring_n} runtime variant(s))"
fi

# When browse-host is on, the owner-gated Level 2 live-view stream route is
# spliced in; otherwise it is omitted. The route proxies the loopback stream
# server (browse-host sidecar). This gate guards per-location (not
# server-level), so the guard MUST be repeated there — without it the stream
# WS would be an unauthenticated hole.
render_paseo_nginx "$GATE_PORT" "$BACKEND_PORT" "$FQDN" "$HTTPS_PORT" "$WIDGET" "$WIDGET_MENU_ATTRS" \
  "$BROWSE" "$BROWSE_WS_PORT" "$ICON_LOC_BODY" > "$frag"
log "wrote nginx fragment: $frag${BROWSE:+ (browse=$BROWSE)}"

# --- 6. tailscale serve (https only — the web UI wants a secure context) ---
# The platform renders this now (manifest [serve.https]; child-4 P2b STEP 0
# — install/lib.sh's airlock_render_serve_https, called from
# install/airlock-install.sh right after this script returns) — byte-
# identical to the direct call this used to make
# (install/test-serve-https-parity.sh proved the two productions equal
# before this line was removed).

# --- 7. browse-host sidecar (config-gated; warn-only) ---
# Server-side browser panels for agents: a loopback WS client that registers a
# Playwright automation host with the daemon (Level 1 = agent browser_* tools) and
# a live-view stream + web-ui patch (Level 2 = the New-browser panel routed via the
# /browse-view/ gate location added above). Non-fatal on purpose: a chromium
# download or web-ui SHA-drift must never break the hub or the paseo daemon.
#
# Is the live-view patch actually in what the daemon serves? A live panel needs all
# THREE of the patcher's outputs, and checking only the bundle marker is a false green
# we measured: patch-web-ui.js repoints index.html before it injects the companion
# <script> or copies the companion file, so it can die leaving a patched, served
# bundle and no companion at all — the marker says yes, the panel is dead.
#
# Marker string kept in sync with PATCHED_MARKER in browse-host/bin/patch-web-ui.js.
webui_has_live_panel() {
  local webui="$1" html dir bundle b
  html="$webui/index.html"
  dir="$webui/_expo/static/js/web"
  [ -f "$html" ] || return 1

  # index.html is allowed to name more than one index-*.js; the served one is the
  # first that exists on disk (the patcher never removes a bundle it still points at).
  bundle=""
  for b in $(grep -o 'index-[0-9a-f]\{1,\}\.js' "$html" 2>/dev/null || true); do
    if [ -f "$dir/$b" ]; then bundle="$b"; break; fi
  done
  [ -n "$bundle" ] || return 1

  # We read plaintext, but the server prefers a .br/.gz sibling whenever the client
  # sends Accept-Encoding. The patcher deletes those siblings, so a surviving one means
  # the bytes just measured are not the bytes anyone is served.
  for b in "$dir/$bundle" "$html"; do
    if [ -e "$b.br" ] || [ -e "$b.gz" ]; then return 1; fi
  done

  grep -qF 'dataSet:{paseoBrowserId:' "$dir/$bundle" || return 1   # 1. bundle patched
  grep -qF 'browse-view-client.js' "$html"           || return 1   # 2. companion referenced
  [ -f "$webui/browse-view-client.js" ]                            # 3. companion present
}

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
      # Ask the served bundle whether the live panel is in it, rather than reading it
      # off the sidecar's exit code. The sidecar exits 0 after warning that the web-ui
      # patch failed — deliberately, so a chromium or SHA-drift problem cannot break
      # the hub — so this one line is the whole install log's only claim that could
      # otherwise be green while the panel is dead.
      if webui_has_live_panel "$WEBUI_DIR"; then
        log "browse-host OK (agent browser_* + live-view panel)"
      else
        log "browse-host OK (agent browser_* only) — live-view panel NOT in the served web-ui bundle; see the [browse-host] WARN above"
      fi
    else
      log "warning: browse-host install failed — agent browsing unavailable (hub + paseo daemon unaffected). Retry: bash $BROWSE_INSTALL"
    fi
  fi
fi

# NOTE: smoke runs from the orchestrator AFTER nginx is rendered + reloaded (the
# gate isn't live until then). See install/airlock-install.sh.
log "paseo installed (owner: ${AIRLOCK_OWNER}${BROWSE:+, browse=$BROWSE})"
