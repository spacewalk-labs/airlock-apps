#!/usr/bin/env bash
# dev-monitor smoke — against a live install (after orchestrator render + reload).
# Same-origin subpath, so the gate under test is the HUB nginx server.
set -uo pipefail
# ABI (D5): prefer the orchestrator-supplied AIRLOCK_ROOT/AIRLOCK_APP_ID,
# falling back to $0-relative computation for a standalone invocation.
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${AIRLOCK_ROOT:-$(cd "$HERE/../.." && pwd)}"
AIRLOCK_APP_ID="${AIRLOCK_APP_ID:-dev-monitor}"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load dev-monitor
BACKEND="$AIRLOCK_DEV_MONITOR_BACKEND_PORT"
airlock_load hub
HUB="$AIRLOCK_HUB_NGINX_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$@"; }
c_be=$(code                                    "http://127.0.0.1:${BACKEND}/api/overview")
c_ui=$(code   -H "${HDR}: ${OWNER}"            "http://127.0.0.1:${HUB}/monitor/")
c_api=$(code  -H "${HDR}: ${OWNER}"            "http://127.0.0.1:${HUB}/monitor/api/overview")
c_deny=$(code -H "${HDR}: nobody@example.com"  "http://127.0.0.1:${HUB}/monitor/api/overview")
c_no=$(code                                     "http://127.0.0.1:${HUB}/monitor/api/overview")

echo "[dev-monitor smoke] backend=${c_be}/200 ui=${c_ui}/200 api=${c_api}/200 deny=${c_deny}/403 no-header=${c_no}/403"
fail=0
[ "$c_be"   = 200 ] || { echo "FAIL backend overview"; fail=1; }
[ "$c_ui"   = 200 ] || { echo "FAIL dashboard UI"; fail=1; }
[ "$c_api"  = 200 ] || { echo "FAIL hub api overview"; fail=1; }
[ "$c_deny" = 403 ] || { echo "FAIL other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_no"   = 403 ] || { echo "FAIL missing header not denied (GATE HOLE)"; fail=1; }

# --- message/action console ---
# `messages` here is what the backend actually managed to start, not what the config
# asked for; a requested-but-unconfigured install reports "off" and is caught below.
state=$(curl -s --max-time 6 "http://127.0.0.1:${BACKEND}/api/health" \
        | python3 -c 'import sys,json; print(json.load(sys.stdin).get("messages","?"))' 2>/dev/null || echo '?')
want="${AIRLOCK_DEV_MONITOR_MESSAGES:-false}"
echo "[dev-monitor smoke] messages: configured=${want} running=${state}"
if [ "$want" = true ]; then
  [ "$state" = on ] || { echo "FAIL messages = true but the console did not start (see journalctl --user -u airlock-dev-monitor)"; fail=1; }
  # The whole point of the proxy secret: reaching the loopback port directly must not be
  # enough, even while carrying a correct-looking owner header. If this returns 200 the
  # nginx fragment and the running backend disagree about the secret, or the gate is off.
  c_direct=$(code -H 'X-Devmon-Owner: '"${OWNER}" "http://127.0.0.1:${BACKEND}/api/owner/messages/preview")
  c_owner=$(code  -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/monitor/api/owner/messages/preview")
  c_other=$(code  -H "${HDR}: nobody@example.com" "http://127.0.0.1:${HUB}/monitor/api/owner/messages/preview")
  # Client-supplied X-Devmon-* must not survive nginx, which REPLACES both headers.
  # Sent with the owner's own identity on purpose: a non-owner identity is rejected by the
  # hub's server-level gate before any location is chosen, so that probe would prove the hub
  # gate works and say nothing about the override. Here nginx must overwrite the forged
  # owner with the real one and the forged secret with the real one — so a 200 is the pass.
  # If either header were passed through, the backend would see owner=nobody and answer 403.
  c_forge=$(code  -H "${HDR}: ${OWNER}" -H 'X-Devmon-Owner: nobody@example.com' \
                  -H 'X-Devmon-Proxy-Secret: forged' "http://127.0.0.1:${HUB}/monitor/api/owner/messages/preview")
  echo "[dev-monitor smoke] owner routes: direct=${c_direct}/403 owner=${c_owner}/200 other=${c_other}/403 forged=${c_forge}/200"
  [ "$c_direct" = 403 ] || { echo "FAIL loopback bypassed the proxy secret (GATE HOLE)"; fail=1; }
  [ "$c_owner"  = 200 ] || { echo "FAIL owner cannot read the console through the hub"; fail=1; }
  [ "$c_other"  = 403 ] || { echo "FAIL a non-owner reached the console (GATE HOLE)"; fail=1; }
  [ "$c_forge"  = 200 ] || { echo "FAIL nginx did not replace a client-supplied X-Devmon-* header (GATE HOLE)"; fail=1; }
  command -v tmux >/dev/null || echo "WARN tmux is absent — cards still arrive, but approved actions cannot run"
else
  c_off=$(code -H "${HDR}: ${OWNER}" "http://127.0.0.1:${HUB}/monitor/api/owner/messages/preview")
  echo "[dev-monitor smoke] console off: owner route=${c_off}/404"
  [ "$c_off" = 404 ] || { echo "FAIL console is off but its route answered ${c_off}"; fail=1; }
fi
[ "$fail" = 0 ]
