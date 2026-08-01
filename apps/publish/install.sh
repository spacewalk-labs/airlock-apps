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

require_cmd python3 systemctl sudo

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
PUBLIC_MODE="$(python3 -c 'import sys; print(sys.argv[1].strip().lower())' "$PUBLIC_MODE")"
PUBLIC_DIR="$(airlock_config get apps.publish.public_target.public_dir 2>/dev/null || true)"
STATE_DIR="$HOME/.local/state/airlock"
PUBLIC_STATE_FILE="$STATE_DIR/publish-public.json"
# The local backend owns this state. A remote reinstall must not strand an
# unexpired local URL after it removes the local-only nginx gate.
local_state_active="$(python3 -c 'import json,sys,time; d=json.load(open(sys.argv[1])); items=d.get("items", {}) if isinstance(d, dict) else {}; print("yes" if isinstance(items, dict) and any(isinstance(item, dict) and isinstance(item.get("expiry"), (int, float)) and item["expiry"] > time.time() for item in items.values()) else "no")' "$PUBLIC_STATE_FILE" 2>/dev/null || true)"
if [ "$PUBLIC_MODE" = remote ] && [ "$local_state_active" = yes ]; then
  die "cannot switch to remote mode while local publications are still active in $PUBLIC_STATE_FILE — reinstall in local mode to revoke them, or wait for expiry before switching to remote"
fi
GATED_DIR="$(airlock_config get apps.publish.public_target.gated_dir 2>/dev/null || true)"
[ -n "$GATED_DIR" ] || GATED_DIR=/opt/airlock/share-gated
GATED_DIR="${GATED_DIR/#\~/$HOME}"
HTPASSWD_DIR="$(airlock_config get apps.publish.public_target.htpasswd_dir 2>/dev/null || true)"
[ -n "$HTPASSWD_DIR" ] || HTPASSWD_DIR=/opt/airlock/publish-gated-auth
HTPASSWD_DIR="${HTPASSWD_DIR/#\~/$HOME}"
HTPASSWD_BIN="$(airlock_config get apps.publish.public_target.htpasswd_bin 2>/dev/null || true)"
[ -n "$HTPASSWD_BIN" ] || HTPASSWD_BIN=htpasswd
if [ "$PUBLIC_MODE" = local ]; then
  [ -n "$PUBLIC_DIR" ] || PUBLIC_DIR=/opt/airlock/share-public
  PUBLIC_DIR="${PUBLIC_DIR/#\~/$HOME}"
  case "$PUBLIC_DIR" in
    /*) ;;
    *) die "public_dir ($PUBLIC_DIR) must be an absolute path after '~' expansion — refusing: the installer, systemd user service, and nginx resolve relative paths from different working directories" ;;
  esac
  case "$GATED_DIR" in
    /*) ;;
    *) die "gated_dir ($GATED_DIR) must be an absolute path after '~' expansion — refusing: the installer, systemd user service, and nginx resolve relative paths from different working directories" ;;
  esac
  case "$HTPASSWD_DIR" in
    /*) ;;
    *) die "htpasswd_dir ($HTPASSWD_DIR) must be an absolute path after '~' expansion — refusing: the installer, systemd user service, and nginx resolve relative paths from different working directories" ;;
  esac
  rp="$(readlink -m "$PUBLIC_DIR" 2>/dev/null)" \
    || die "could not canonicalize public_dir $PUBLIC_DIR — refusing"
  rs="$(readlink -m "$SHARE_DIR" 2>/dev/null)" \
    || die "could not canonicalize share_dir $SHARE_DIR — refusing"
  rg="$(readlink -m "$GATED_DIR" 2>/dev/null)" \
    || die "could not canonicalize gated_dir $GATED_DIR — refusing"
  rh="$(readlink -m "$HTPASSWD_DIR" 2>/dev/null)" \
    || die "could not canonicalize htpasswd_dir $HTPASSWD_DIR — refusing"
  rt="$(readlink -m "$STATE_DIR" 2>/dev/null)" \
    || die "could not canonicalize state_dir $STATE_DIR — refusing"
  rp_prefix="$rp/"; [ "$rp" = / ] && rp_prefix=/
  rs_prefix="$rs/"; [ "$rs" = / ] && rs_prefix=/
  rg_prefix="$rg/"; [ "$rg" = / ] && rg_prefix=/
  rh_prefix="$rh/"; [ "$rh" = / ] && rh_prefix=/
  rt_prefix="$rt/"; [ "$rt" = / ] && rt_prefix=/
  case "$rp_prefix" in "$rt_prefix"*) die "public_dir ($rp) is inside state_dir ($rt) — refusing: publish state contains owner identities and must stay outside served roots";; esac
  case "$rt_prefix" in "$rp_prefix"*) die "public_dir ($rp) contains state_dir ($rt) — refusing: publish state contains owner identities and must stay outside served roots";; esac
  # `test -x` asks whether this installer user can traverse; an owner can pass
  # 0700 even though the nginx worker cannot. Check the other-execute bit from
  # stat instead, and only inspect path components that already exist.
  for dir in "$PUBLIC_DIR" "$GATED_DIR" "$HTPASSWD_DIR"; do
    # `-m` also normalizes `..` through directories that will be created later;
    # `-f` would fall back to the raw spelling and let an overlap bypass this gate.
    ancestor="$(readlink -m "$dir" 2>/dev/null)" \
      || die "could not canonicalize publish path $dir — refusing"
    while [ ! -d "$ancestor" ]; do
      parent="${ancestor%/*}"
      [ "$parent" != "$ancestor" ] || break
      ancestor="${parent:-/}"
    done
    while [ -d "$ancestor" ]; do
      mode="$(stat -c '%A' "$ancestor" 2>/dev/null)" \
        || die "could not stat publish path ancestor $ancestor — refusing"
      case "${mode:9:1}" in
        x|t) ;;
        *) die "publish path ancestor $ancestor blocks nginx traversal (o+x is required here; 0750 root:www-data also works when nginx runs with group www-data) — refusing" ;;
      esac
      [ "$ancestor" = / ] && break
      ancestor="${ancestor%/*}"
      [ -n "$ancestor" ] || ancestor=/
    done
  done
  # Hard refusal: the public dir must not be (or contain, or sit inside) the
  # tailnet-internal share — that is how the internal share leaks to the world.
  case "$rp_prefix" in "$rs_prefix"*) die "public_dir ($rp) is inside share_dir ($rs) — refusing: that would publish the internal share";; esac
  case "$rs_prefix" in "$rp_prefix"*) die "public_dir ($rp) contains share_dir ($rs) — refusing: that would publish the internal share";; esac
  # These are exposure boundaries, not optional-feature checks: disabling the
  # gate leaves already-published files behind, and an auth directory can make
  # its bcrypt records downloadable through a served root.
  case "$rg_prefix" in "$rs_prefix"*) die "gated_dir ($rg) is inside share_dir ($rs) — refusing: that would expose gated content through the internal share";; esac
  case "$rs_prefix" in "$rg_prefix"*) die "gated_dir ($rg) contains share_dir ($rs) — refusing: that would expose the internal share through the gated root";; esac
  case "$rg_prefix" in "$rp_prefix"*) die "gated_dir ($rg) is inside public_dir ($rp) — refusing: that would expose gated content without authentication";; esac
  case "$rp_prefix" in "$rg_prefix"*) die "gated_dir ($rg) contains public_dir ($rp) — refusing: that would mix open public content into the gated root";; esac
  case "$rh_prefix" in "$rs_prefix"*) die "htpasswd_dir ($rh) is inside share_dir ($rs) — refusing: that would expose password hashes through a served root";; esac
  case "$rs_prefix" in "$rh_prefix"*) die "htpasswd_dir ($rh) contains share_dir ($rs) — refusing: credential storage must be separate from served roots";; esac
  case "$rh_prefix" in "$rp_prefix"*) die "htpasswd_dir ($rh) is inside public_dir ($rp) — refusing: that would expose password hashes through a served root";; esac
  case "$rp_prefix" in "$rh_prefix"*) die "htpasswd_dir ($rh) contains public_dir ($rp) — refusing: credential storage must be separate from served roots";; esac
  case "$rh_prefix" in "$rg_prefix"*) die "htpasswd_dir ($rh) is inside gated_dir ($rg) — refusing: that would expose password hashes through a served root";; esac
  case "$rg_prefix" in "$rh_prefix"*) die "htpasswd_dir ($rh) contains gated_dir ($rg) — refusing: credential storage must be separate from served roots";; esac
  case "$rs_prefix" in "$rt_prefix"*) die "share_dir ($rs) is inside state_dir ($rt) — refusing: publish state contains owner identities and must stay outside served roots";; esac
  case "$rt_prefix" in "$rs_prefix"*) die "share_dir ($rs) contains state_dir ($rt) — refusing: publish state contains owner identities and must stay outside served roots";; esac
  case "$rg_prefix" in "$rt_prefix"*) die "gated_dir ($rg) is inside state_dir ($rt) — refusing: publish state contains owner identities and must stay outside served roots";; esac
  case "$rt_prefix" in "$rg_prefix"*) die "gated_dir ($rg) contains state_dir ($rt) — refusing: publish state contains owner identities and must stay outside served roots";; esac
  case "$rh_prefix" in "$rt_prefix"*) die "htpasswd_dir ($rh) is inside state_dir ($rt) — refusing: publish state contains owner identities and must stay outside served roots";; esac
  case "$rt_prefix" in "$rh_prefix"*) die "htpasswd_dir ($rh) contains state_dir ($rt) — refusing: publish state contains owner identities and must stay outside served roots";; esac
fi

# --- 1. directories ---
mkdir_nginx_path() {
  local path="${1%/}" elevated="${2:-no}" ancestor parent mode
  local -a created=()
  [ -n "$path" ] || path=/
  ancestor="$path"
  while [ ! -d "$ancestor" ]; do
    created+=("$ancestor")
    parent="${ancestor%/*}"
    [ "$parent" != "$ancestor" ] || break
    ancestor="${parent:-/}"
  done
  # mkdir -p follows umask; only directories created by this call may be
  # changed, so an existing operator-owned ancestor keeps its permissions.
  if [ "$elevated" = yes ]; then
    airlock_run sudo mkdir -p "$path"
  else
    airlock_run mkdir -p "$path"
  fi
  for ancestor in "${created[@]}"; do
    [ "$ancestor" = "$path" ] && mode=755 || mode=o+x
    if [ "$elevated" = yes ]; then
      airlock_run sudo chmod "$mode" "$ancestor"
    else
      airlock_run chmod "$mode" "$ancestor"
    fi
  done
}

# share_dir under /opt is world-readable so nginx can serve /publish/files/.
if [ "${SHARE_DIR#/opt/}" != "$SHARE_DIR" ]; then
  mkdir_nginx_path "$SHARE_DIR" yes
  airlock_run sudo chown "$(id -un):$(id -gn)" "$SHARE_DIR"
else
  mkdir_nginx_path "$SHARE_DIR" no        # user-owned path (e.g. ~/public_html)
fi
airlock_run mkdir -p "$UPLOADS_DIR"
# local public target: the backend (systemd --user) writes it, nginx only reads.
# 0755 so the nginx worker can traverse/read regardless of the service umask.
if [ "$PUBLIC_MODE" = local ]; then
  if [ "${PUBLIC_DIR#/opt/}" != "$PUBLIC_DIR" ]; then
    mkdir_nginx_path "$PUBLIC_DIR" yes
    airlock_run sudo chown "$(id -un):$(id -gn)" "$PUBLIC_DIR"
  else
    mkdir_nginx_path "$PUBLIC_DIR" no
  fi
  if [ "${GATED_DIR#/opt/}" != "$GATED_DIR" ]; then
    mkdir_nginx_path "$GATED_DIR" yes
    airlock_run sudo chown "$(id -un):$(id -gn)" "$GATED_DIR"
  else
    mkdir_nginx_path "$GATED_DIR" no
  fi
  airlock_run mkdir -p "$STATE_DIR"        # owner identities live here — not in a web root
  airlock_run chmod 700 "$STATE_DIR"
  if [ "${HTPASSWD_DIR#/opt/}" != "$HTPASSWD_DIR" ]; then
    mkdir_nginx_path "$HTPASSWD_DIR" yes
    airlock_run sudo chown "$(id -un):$(id -gn)" "$HTPASSWD_DIR"
  else
    mkdir_nginx_path "$HTPASSWD_DIR" no
  fi
  # nginx reads one bcrypt record on every gated request. Local users can
  # already read the 0755 gated_dir, so 0644 records are preferable to a dead gate.
  if ! command -v "$HTPASSWD_BIN" >/dev/null 2>&1; then
    # Not a preflight row: preflight is per-app and fails the whole install, and gated is an
    # opt-in half of an optional target. Open publishing is unaffected; a gated publish is
    # refused with this reason rather than quietly downgraded to open.
    log "WARN: gated publish is unavailable — '$HTPASSWD_BIN' not found. Install it (sudo apt-get install -y apache2-utils) or publish open links only."
  fi
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
Environment=AIRLOCK_PUBLISH_GATED_DIR=${GATED_DIR}
Environment=AIRLOCK_PUBLISH_HTPASSWD_DIR=${HTPASSWD_DIR}
Environment=AIRLOCK_PUBLISH_HTPASSWD_BIN=${HTPASSWD_BIN}
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
Environment=AIRLOCK_PUBLISH_GATED_DIR=${GATED_DIR}
Environment=AIRLOCK_PUBLISH_HTPASSWD_DIR=${HTPASSWD_DIR}
Environment=AIRLOCK_PUBLISH_HTPASSWD_BIN=${HTPASSWD_BIN}
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
sed_replacement() { printf '%s' "$1" | sed 's/[\\&|]/\\&/g'; }
BACKEND_PORT_SED="$(sed_replacement "$BACKEND_PORT")"
SHARE_DIR_SED="$(sed_replacement "$SHARE_DIR")"
GATED_DIR_SED="$(sed_replacement "$GATED_DIR")"
HTPASSWD_DIR_SED="$(sed_replacement "$HTPASSWD_DIR")"
{
  echo "# publish subpath — generated by apps/publish/install.sh"
  sed -e "s|@@BACKEND@@|${BACKEND_PORT_SED}|g" -e "s|@@SHARE@@|${SHARE_DIR_SED}|g" <<'NGINX'
# API backend (backend strips the /publish/ prefix itself). Uploads need a body cap.
location /publish/api/ {
    proxy_pass http://127.0.0.1:@@BACKEND@@;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    client_max_body_size 60m;
    add_header Cache-Control "no-cache" always;
}
# Served static-share directory (hub gate = owner + collaborators, server level).
location /publish/files/ {
    alias @@SHARE@@/;
    autoindex on;
    add_header Cache-Control "no-cache" always;
}
NGINX
} > "$frag"
log "wrote nginx fragment: $frag"

if [ "$PUBLIC_MODE" = local ]; then
  # Include this fragment inside the operator's public server block. Publishing
  # updates one slug-specific credential file, so nginx does not need a reload.
  gated_frag="$CONFD/public-includes.d/publish-gated.conf"
  install -d "$CONFD/public-includes.d"
  {
    echo "# gated public snapshots — include inside the public nginx server"
    sed -e "s|@@GATED@@|${GATED_DIR_SED}|g" -e "s|@@AUTHDIR@@|${HTPASSWD_DIR_SED}|g" <<'NGINX'
location ~ "^/g/(?<gslug>[a-z0-9][a-z0-9-]{2,63})(?<gpath>/.*)?$" {
    auth_basic "Restricted document";
    auth_basic_user_file @@AUTHDIR@@/$gslug.htpasswd;
    alias @@GATED@@/$gslug$gpath;
    index index.html;
    add_header Cache-Control "no-store" always;
}
NGINX
  } > "$gated_frag"
  # The former top-level location was generated by an older release. Remove
  # it after writing the replacement under the normal includes directory.
  if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
    log "[dry] remove legacy nginx fragment: $CONFD/publish-public-gated.conf"
  else
    rm -f "$CONFD/publish-public-gated.conf"
  fi
  log "wrote nginx gated-public fragment: $gated_frag"
else
  # A mode change must retract the generated gate; otherwise an operator's
  # existing include keeps serving stale gated content in remote mode.
  if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then
    log "[dry] remove disabled nginx gated fragments"
  else
    rm -f "$CONFD/public-includes.d/publish-gated.conf" "$CONFD/publish-public-gated.conf"
  fi
fi

# NOTE: smoke runs from the orchestrator AFTER nginx reload (gate not live before).
if [ "$PUBLIC_MODE" = local ]; then
  log "publish installed (owner: ${AIRLOCK_OWNER}; external target: local -> ${PUBLIC_DIR} at ${BASE_URL:-<base_url MISSING>})"
else
  log "publish installed (owner: ${AIRLOCK_OWNER}; external target: ${INGEST_URL:-<none, share-manager only>})"
fi
