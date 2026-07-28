#!/usr/bin/env bash
# publish smoke — against a live install (after orchestrator render + reload).
# Same-origin subpath, so the gate under test is the HUB nginx server.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load publish
BACKEND="$AIRLOCK_PUBLISH_BACKEND_PORT"
airlock_load hub
HUB="$AIRLOCK_HUB_NGINX_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$@"; }
c_be=$(code   "http://127.0.0.1:${BACKEND}/api/health")
c_ui=$(code   -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/publish/")
c_list=$(code -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/publish/api/list")
c_files=$(code -H "${HDR}: ${OWNER}"          "http://127.0.0.1:${HUB}/publish/files/")
c_deny=$(code -H "${HDR}: nobody@example.com" "http://127.0.0.1:${HUB}/publish/api/list")
c_no=$(code                                    "http://127.0.0.1:${HUB}/publish/api/list")
# the list endpoint must return valid JSON with ok:true for the owner
okjson=no; curl -s --max-time 6 -H "${HDR}: ${OWNER}" "http://127.0.0.1:${HUB}/publish/api/list" | grep -q '"ok": *true' && okjson=yes

# local public target (if configured): the public dir must exist, be writable by
# us, and must NOT be the tailnet-internal share — that overlap is the leak.
PUB_MODE="$(airlock_config get apps.publish.public_target.mode 2>/dev/null || true)"
localpub=n/a
if [ "$PUB_MODE" = local ]; then
  PUB_DIR="$(airlock_config get apps.publish.public_target.public_dir 2>/dev/null || true)"
  [ -n "$PUB_DIR" ] || PUB_DIR=/opt/airlock/share-public
  SH="$(readlink -f "${AIRLOCK_PUBLISH_SHARE_DIR:-/opt/airlock/share}" 2>/dev/null)"
  PD="$(readlink -f "$PUB_DIR" 2>/dev/null)"
  localpub=ok
  [ -d "$PUB_DIR" ] && [ -w "$PUB_DIR" ] || localpub="not-writable:$PUB_DIR"
  [ "$PD" != "$SH" ] || localpub="OVERLAPS-SHARE:$PD"
  # the backend must actually report local mode (i.e. it did not refuse at startup)
  curl -s --max-time 6 "http://127.0.0.1:${BACKEND}/api/health" | grep -q '"public_enabled": *true' \
    || localpub="backend-disabled (check: journalctl --user -u airlock-publish)"
fi

echo "[publish smoke] backend=${c_be}/200 ui=${c_ui}/200 list=${c_list}/200 files=${c_files}/200 deny=${c_deny}/403 no-header=${c_no}/403 list-json=${okjson}/yes local-public=${localpub}"
fail=0
[ "$c_be"   = 200 ] || { echo "FAIL backend health"; fail=1; }
[ "$c_ui"   = 200 ] || { echo "FAIL manager UI"; fail=1; }
[ "$c_list" = 200 ] || { echo "FAIL list endpoint"; fail=1; }
{ [ "$c_files" = 200 ] || [ "$c_files" = 403 ] || [ "$c_files" = 404 ]; } || { echo "FAIL files location broken ($c_files)"; fail=1; }
[ "$c_deny" = 403 ] || { echo "FAIL other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_no"   = 403 ] || { echo "FAIL missing header not denied (GATE HOLE)"; fail=1; }
[ "$okjson" = yes ] || { echo "FAIL list did not return ok:true json"; fail=1; }
{ [ "$localpub" = n/a ] || [ "$localpub" = ok ]; } || { echo "FAIL local public target: $localpub"; fail=1; }
[ "$fail" = 0 ]
