#!/usr/bin/env bash
# publish — static-share manager (+ optional pluggable external publish), served
# as a same-origin subpath under the hub (owner + collaborators).
#
#   browser --> hub (tailscale serve) --(identity)--> hub nginx
#     /publish/        -> manager UI (static, from the hub webroot)
#     /publish/api/    -> airlock-publish backend 127.0.0.1:BACKEND (loopback)
#     /publish/files/  -> the static-share directory (served by nginx)
#
# The backend also accepts clipboard/file uploads into ~/uploads (the notepad
# drop). External publishing is enabled only if [apps.publish.public_target] is
# configured. Config from airlock.toml. Honors AIRLOCK_DRY_RUN=1.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

require_cmd python3

airlock_load publish
BACKEND_PORT="${AIRLOCK_PUBLISH_BACKEND_PORT:?}"
CONFD="${AIRLOCK_CONFD:-/etc/airlock/nginx}"
WEBROOT="${AIRLOCK_WEBROOT:-/opt/airlock/hub}"
IDENTITY_HEADER="${AIRLOCK_IDENTITY_HEADER:?}"
# tilde-expand share_dir (may be "~/..."); default is an /opt path nginx can read.
SHARE_DIR="${AIRLOCK_PUBLISH_SHARE_DIR:-/opt/airlock/share}"
SHARE_DIR="${SHARE_DIR/#\~/$HOME}"
UPLOADS_DIR="$HOME/uploads"
BACKEND_PY="$ROOT/apps/publish/backend/airlock-publish.py"
UNIT_DIR="$HOME/.config/systemd/user"

# Optional pluggable external-publish target (absent = share-manager only).
#   mode=remote (default) -> POST snapshots to an ingest service you host
#   mode=local            -> write snapshots into PUBLIC_DIR, served by this box
INGEST_URL="$(airlock_config get apps.publish.public_target.ingest_url 2>/dev/null || true)"
BASE_URL="$(airlock_config get apps.publish.public_target.base_url 2>/dev/null || true)"
TOKEN_ENV="$(airlock_config get apps.publish.public_target.token_env 2>/dev/null || true)"
[ -n "$TOKEN_ENV" ] || TOKEN_ENV=AIRLOCK_PUBLISH_TOKEN
PUBLIC_MODE="$(airlock_config get apps.publish.public_target.mode 2>/dev/null || true)"
[ -n "$PUBLIC_MODE" ] || PUBLIC_MODE=remote
PUBLIC_DIR="$(airlock_config get apps.publish.public_target.public_dir 2>/dev/null || true)"
STATE_DIR="$HOME/.local/state/airlock"
if [ "$PUBLIC_MODE" = local ]; then
  [ -n "$PUBLIC_DIR" ] || PUBLIC_DIR=/opt/airlock/share-public
  PUBLIC_DIR="${PUBLIC_DIR/#\~/$HOME}"
  # Hard refusal: the public dir must not be (or contain, or sit inside) the
  # tailnet-internal share — that is how the internal share leaks to the world.
  rp="$(readlink -f "$PUBLIC_DIR" 2>/dev/null || echo "$PUBLIC_DIR")"
  rs="$(readlink -f "$SHARE_DIR" 2>/dev/null || echo "$SHARE_DIR")"
  case "$rp/" in "$rs"/*) die "public_dir ($rp) is inside share_dir ($rs) — refusing: that would publish the internal share";; esac
  case "$rs/" in "$rp"/*) die "public_dir ($rp) contains share_dir ($rs) — refusing: that would publish the internal share";; esac
fi

# --- 1. directories ---
# share_dir under /opt is world-readable so nginx can serve /publish/files/.
if [ "${SHARE_DIR#/opt/}" != "$SHARE_DIR" ]; then
  airlock_run sudo mkdir -p "$SHARE_DIR"
  airlock_run sudo chown "$(id -un):$(id -gn)" "$SHARE_DIR"
else
  airlock_run mkdir -p "$SHARE_DIR"        # user-owned path (e.g. ~/public_html)
fi
airlock_run mkdir -p "$UPLOADS_DIR"
# local public target: the backend (systemd --user) writes it, nginx only reads.
# 0755 so the nginx worker can traverse/read regardless of the service umask.
if [ "$PUBLIC_MODE" = local ]; then
  if [ "${PUBLIC_DIR#/opt/}" != "$PUBLIC_DIR" ]; then
    airlock_run sudo mkdir -p "$PUBLIC_DIR"
    airlock_run sudo chown "$(id -un):$(id -gn)" "$PUBLIC_DIR"
  else
    airlock_run mkdir -p "$PUBLIC_DIR"
  fi
  airlock_run chmod 755 "$PUBLIC_DIR"
  airlock_run mkdir -p "$STATE_DIR"        # owner identities live here — not in a web root
  airlock_run chmod 700 "$STATE_DIR"
fi

# --- 2. systemd user unit (loopback backend) + TTL cleanup timer ---
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] write $UNIT_DIR/airlock-publish.service (127.0.0.1:$BACKEND_PORT, share=$SHARE_DIR)"
else
  install -d "$UNIT_DIR"
  cat >"$UNIT_DIR/airlock-publish.service" <<UNIT
[Unit]
Description=airlock publish — static-share manager + uploads (127.0.0.1:${BACKEND_PORT})
After=network.target

[Service]
Type=simple
# Optional secret (the external-publish token) — safe if the file is absent.
EnvironmentFile=-%h/.config/airlock-publish.env
Environment=AIRLOCK_PUBLISH_BACKEND_PORT=${BACKEND_PORT}
Environment=AIRLOCK_PUBLISH_SHARE_DIR=${SHARE_DIR}
Environment=AIRLOCK_PUBLISH_UPLOADS_DIR=${UPLOADS_DIR}
Environment=AIRLOCK_IDENTITY_HEADER=${IDENTITY_HEADER}
Environment=AIRLOCK_PUBLISH_INGEST_URL=${INGEST_URL}
Environment=AIRLOCK_PUBLISH_BASE_URL=${BASE_URL}
Environment=AIRLOCK_PUBLISH_TOKEN_ENV=${TOKEN_ENV}
Environment=AIRLOCK_PUBLISH_PUBLIC_MODE=${PUBLIC_MODE}
Environment=AIRLOCK_PUBLISH_PUBLIC_DIR=${PUBLIC_DIR}
Environment=AIRLOCK_PUBLISH_STATE_DIR=${STATE_DIR}
ExecStart=$(command -v python3) ${BACKEND_PY}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
  cat >"$UNIT_DIR/airlock-publish-cleanup.service" <<UNIT
[Unit]
Description=airlock publish — uploads TTL sweep (24h) + public snapshot expiry

[Service]
Type=oneshot
# MUST mirror the service's public env — the sweep and the writer have to agree
# on which directory and state file they are talking about.
Environment=AIRLOCK_PUBLISH_UPLOADS_DIR=${UPLOADS_DIR}
Environment=AIRLOCK_PUBLISH_PUBLIC_MODE=${PUBLIC_MODE}
Environment=AIRLOCK_PUBLISH_PUBLIC_DIR=${PUBLIC_DIR}
Environment=AIRLOCK_PUBLISH_STATE_DIR=${STATE_DIR}
ExecStart=$(command -v python3) ${BACKEND_PY} --cleanup
UNIT
  cat >"$UNIT_DIR/airlock-publish-cleanup.timer" <<'UNIT'
[Unit]
Description=airlock publish — run uploads TTL sweep hourly

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
fi
airlock_run systemctl --user daemon-reload
airlock_run systemctl --user enable airlock-publish.service airlock-publish-cleanup.timer
airlock_run systemctl --user restart airlock-publish.service
airlock_run systemctl --user restart airlock-publish-cleanup.timer

# --- 3. manager UI into the hub webroot (served by the hub's static location /) ---
if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
  log "[dry] install publish.html -> $WEBROOT/publish/index.html"
else
  install -d "$WEBROOT/publish"
  install -m644 "$HERE/frontend/publish.html" "$WEBROOT/publish/index.html"
fi

# --- 4. nginx subpath fragment (included inside the hub server = server-level gate) ---
frag="$CONFD/hub-locations.d/publish.conf"
install -d "$CONFD/hub-locations.d"
{
  echo "# publish subpath — generated by apps/publish/install.sh"
  sed -e "s/@@BACKEND@@/${BACKEND_PORT}/g" -e "s|@@SHARE@@|${SHARE_DIR}|g" <<'NGINX'
# API backend (backend strips the /publish/ prefix itself). Uploads need a body cap.
location /publish/api/ {
    proxy_pass http://127.0.0.1:@@BACKEND@@;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    client_max_body_size 60m;
    add_header Cache-Control "no-cache" always;
}
# Served static-share directory (owner-gated by the hub server-level guard).
location /publish/files/ {
    alias @@SHARE@@/;
    autoindex on;
    add_header Cache-Control "no-cache" always;
}
NGINX
} > "$frag"
log "wrote nginx fragment: $frag"

# NOTE: smoke runs from the orchestrator AFTER nginx reload (gate not live before).
if [ "$PUBLIC_MODE" = local ]; then
  log "publish installed (owner: ${AIRLOCK_OWNER}; external target: local -> ${PUBLIC_DIR} at ${BASE_URL:-<base_url MISSING>})"
else
  log "publish installed (owner: ${AIRLOCK_OWNER}; external target: ${INGEST_URL:-<none, share-manager only>})"
fi
