#!/usr/bin/env bash
# markwand — markdown/file viewer (markserv) + zero-login editor (filebrowser),
# served as a same-origin subpath under the hub (owner + collaborators).
#
#   browser --> hub (tailscale serve :443) --(identity)--> hub nginx
#     /markwand/       -> markserv 127.0.0.1:MS   (renders code_root as HTML)
#     /markwand/edit/  -> filebrowser 127.0.0.1:FB (baseURL=/markwand/edit)
#     /__mw/*          -> static assets from the hub webroot (tokens/enhance/editor)
#
# The hub gate ($hub_ok) is re-asserted in each location, so a non-owner identity
# gets the hub's wrong-owner page. markserv/filebrowser bind loopback only.
#
# Config from airlock.toml ([apps.markwand] + paths.code_root). Honors AIRLOCK_DRY_RUN=1.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load markwand
MS_PORT="${AIRLOCK_MARKWAND_MARKSERV_PORT:?}"
FB_PORT="${AIRLOCK_MARKWAND_FILEBROWSER_PORT:?}"
CODE_ROOT="${AIRLOCK_CODE_ROOT:-$HOME/code}"
CONFD="${AIRLOCK_CONFD:-/etc/airlock/nginx}"
WEBROOT="${AIRLOCK_WEBROOT:-/opt/airlock/hub}"

require_cmd node npm

MS_VER=1.17.4
FB_VER=2.63.18
FB_BIN="$HOME/.local/bin/filebrowser"
FB_DB="$HOME/.config/filebrowser/fb.db"
FB_BRANDING_DIR="$HOME/.config/filebrowser/branding"
MS_BIN="$HOME/.local/bin/markserv"
UNIT_DIR="$HOME/.config/systemd/user"

# markserv wants its code_root to exist before it starts.
airlock_run mkdir -p "$CODE_ROOT"

# --- 1. provision markserv (npm, no sudo — local prefix) ---
provision_markserv() {
  if [ -x "$MS_BIN" ] && "$MS_BIN" --version 2>/dev/null | grep -q "$MS_VER"; then
    log "markserv $MS_VER present"; return
  fi
  if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then log "[dry] npm install -g --prefix ~/.local markserv@$MS_VER"; return; fi
  # npm's own integrity check pins the tarball; we pin the version.
  npm install -g --prefix "$HOME/.local" "markserv@${MS_VER}" >/dev/null \
    || die "markserv npm install failed"
  [ -x "$MS_BIN" ] || die "markserv installed but $MS_BIN missing"
  log "markserv $MS_VER installed"
}
provision_markserv

# --- 2. provision filebrowser (sha256-pinned binary; no piped installer) ---
provision_filebrowser() {
  if [ -x "$FB_BIN" ] && "$FB_BIN" version 2>/dev/null | grep -q "$FB_VER"; then
    log "filebrowser $FB_VER present"; return
  fi
  local asset sha
  case "$(uname -m)" in
    x86_64)  asset=linux-amd64-filebrowser.tar.gz; sha=cd599c34afad0e8e61c577d1061c820bccb7feaa3c5a4477a12db586a1cd93ff ;;
    aarch64) asset=linux-arm64-filebrowser.tar.gz; sha=29b3935c222d91522874e98dfa33195ee7d2acdac5dfbf37c1361a73704a28de ;;
    *) die "filebrowser: unsupported arch $(uname -m)" ;;
  esac
  local url="https://github.com/filebrowser/filebrowser/releases/download/v${FB_VER}/${asset}"
  if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then log "[dry] download+verify filebrowser $FB_VER -> $FB_BIN"; return; fi
  local td; td="$(mktemp -d)"
  curl -fsSL --max-time 90 -o "$td/fb.tgz" "$url" || { rm -rf "$td"; die "filebrowser download failed: $url"; }
  local got; got="$(sha256sum "$td/fb.tgz" | cut -d' ' -f1)"
  [ "$got" = "$sha" ] || { rm -rf "$td"; die "filebrowser sha256 mismatch got=$got want=$sha"; }
  tar -xzf "$td/fb.tgz" -C "$td" filebrowser || { rm -rf "$td"; die "filebrowser extract failed"; }
  install -D -m755 "$td/filebrowser" "$FB_BIN"; rm -rf "$td"
  log "filebrowser sha256 verified ($FB_VER)"
}
provision_filebrowser

# --- 3. systemd user units (both bind loopback; nginx fronts them) ---
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] write $UNIT_DIR/airlock-markserv.service (127.0.0.1:$MS_PORT, root $CODE_ROOT)"
  log "[dry] write $UNIT_DIR/airlock-filebrowser.service (127.0.0.1:$FB_PORT, root $CODE_ROOT)"
else
  install -d "$UNIT_DIR" "$HOME/.config/filebrowser" "$FB_BRANDING_DIR"
  cat >"$UNIT_DIR/airlock-markserv.service" <<UNIT
[Unit]
Description=airlock markserv — markdown viewer for ${CODE_ROOT} (127.0.0.1:${MS_PORT})
After=network.target

[Service]
Type=simple
WorkingDirectory=${CODE_ROOT}
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
# --livereloadport false: no chokidar watcher (avoids EACCES on symlinked trees)
ExecStart=${MS_BIN} --address 127.0.0.1 --port ${MS_PORT} --livereloadport false --browser false --silent ${CODE_ROOT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
  cat >"$UNIT_DIR/airlock-filebrowser.service" <<UNIT
[Unit]
Description=airlock filebrowser — zero-login editor for ${CODE_ROOT} (127.0.0.1:${FB_PORT})
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/.config/filebrowser
ExecStart=${FB_BIN} --database ${FB_DB} --root ${CODE_ROOT} --address 127.0.0.1 --port ${FB_PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
fi

# --- 3.5. filebrowser first-run quickSetup (noauth), then persist baseURL/branding ---
# auth none is safe ONLY because the sole external path is the hub identity gate
# and filebrowser binds loopback (see SECURITY.md).
if [ "${AIRLOCK_DRY_RUN:-0}" != 1 ]; then
  install -m644 "$HERE/filebrowser/custom.css" "$FB_BRANDING_DIR/custom.css"
  # filebrowser's config get/set need an exclusive DB lock. On a re-run the
  # service is already up and holds it, so stop it first (step 4 restarts it).
  # No-op on first run (unit not loaded yet).
  systemctl --user stop airlock-filebrowser.service 2>/dev/null || true
  if [ ! -f "$FB_DB" ]; then
    log "filebrowser first-run quickSetup (--noauth)"
    "$FB_BIN" --database "$FB_DB" --root "$CODE_ROOT" --address 127.0.0.1 --port "$FB_PORT" --noauth &
    qs=$!; sleep 2; kill "$qs" 2>/dev/null || true; wait "$qs" 2>/dev/null || true
  fi
  cfg="$("$FB_BIN" config cat -d "$FB_DB" 2>/dev/null || true)"
  baseurl="$(printf '%s\n' "$cfg" | awk '/Base URL:/ {print $3; exit}' || true)"
  if [ "$baseurl" != "/markwand/edit" ] || ! printf '%s\n' "$cfg" | grep -Fq "$FB_BRANDING_DIR"; then
    log "filebrowser baseURL + branding migration"
    "$FB_BIN" config set --baseURL /markwand/edit -d "$FB_DB" >/dev/null
    "$FB_BIN" config set --branding.name "Markwand Editor" --branding.files "$FB_BRANDING_DIR" -d "$FB_DB" >/dev/null
  fi
fi

airlock_run systemctl --user daemon-reload
airlock_run systemctl --user enable airlock-markserv.service airlock-filebrowser.service
airlock_run systemctl --user restart airlock-markserv.service airlock-filebrowser.service

# --- 4. static assets into the hub webroot (served by the hub's guarded location /) ---
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] install markwand static assets -> $WEBROOT/__mw/"
else
  install -d "$WEBROOT/__mw"
  install -m644 "$HERE/static/markwand-tokens.css"  "$WEBROOT/__mw/markwand-tokens.css"
  install -m644 "$HERE/static/markwand-enhance.js"  "$WEBROOT/__mw/markwand-enhance.js"
  install -m644 "$HERE/static/markwand-editor.js"   "$WEBROOT/__mw/markwand-editor.js"
  install -m644 "$HERE/static/edit-button.js"       "$WEBROOT/__mw/edit-button.js"
fi

# --- 5. nginx subpath fragment (included inside the hub server block) ---
# Quoted heredoc + sed placeholders so nginx runtime vars ($hub_ok, $host, ...)
# are never touched by the shell; only ports are substituted.
frag="$CONFD/hub-locations.d/markwand.conf"
install -d "$CONFD/hub-locations.d"
{
  echo "# markwand subpath — generated by apps/markwand/install.sh"
  sed -e "s/@@MS@@/${MS_PORT}/g" -e "s/@@FB@@/${FB_PORT}/g" <<'NGINX'
# These locations are included inside the hub server, which gates every request
# at the server level ($hub_ok) — so they are plain proxies, no per-location guard.
# filebrowser editor (baseURL=/markwand/edit) — longest prefix wins over /markwand/
location /markwand/edit/ {
    proxy_pass http://127.0.0.1:@@FB@@;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 86400s;
    proxy_set_header Accept-Encoding "";
    # save -> jump back to the markserv viewer (filebrowser has no custom.js hook)
    sub_filter '</body>' '<script src="/__mw/markwand-editor.js"></script></body>';
    sub_filter_once off;
    add_header Cache-Control "no-cache, no-store, must-revalidate" always;
}

# markserv viewer — strip the /markwand/ prefix, inject tokens + enhance + edit button
location /markwand/ {
    rewrite ^/markwand/(.*)$ /$1 break;
    proxy_pass http://127.0.0.1:@@MS@@;
    proxy_set_header Host $host;
    proxy_set_header Accept-Encoding "";
    sub_filter '</head>' '<link rel="stylesheet" href="/__mw/markwand-tokens.css"></head>';
    sub_filter '</body>' '<script src="/__mw/markwand-enhance.js"></script><script src="/__mw/edit-button.js"></script><script src="/airlock-return.js" data-mode="corner" defer></script></body>';
    sub_filter 'href="/'  'href="/markwand/';
    sub_filter_once off;
    # sub_filter_types defaults to text/html — leaving it implicit avoids a
    # "duplicate MIME type" warning at nginx -t.
    add_header Cache-Control "no-cache, no-store, must-revalidate" always;
}
NGINX
} > "$frag"
log "wrote nginx fragment: $frag"

# NOTE: smoke runs from the orchestrator AFTER nginx reload (gate not live before).
log "markwand installed (owner: ${AIRLOCK_OWNER})"
