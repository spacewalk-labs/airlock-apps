#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$APP/../.." && pwd)"
fail() { echo "FAIL orca parity: $*" >&2; exit 1; }
contains() { grep -Fq -- "$2" "$1" || fail "${1#"$APP/"} missing: $2"; }

bash -n "$APP/install.sh" "$APP/render.sh" "$APP/state.sh" \
  "$APP/deactivate.sh" "$APP/smoke.sh" "$APP/release-pin.sh" \
  "$APP/bin/verify-web-bundle.sh" \
  "$APP/bin/refresh-web-bundle.sh"
"$APP/bin/verify-web-bundle.sh" --quiet

# OR-C4/OR-S4 selected: complete ledger ownership and public canonical paths.
APP="$APP" python3 - <<'PY'
import os, pathlib, re, subprocess, tomllib
app = pathlib.Path(os.environ['APP'])
m = tomllib.loads((app / 'airlock-app.toml').read_text())
assert m['artifacts']['rooted'] == ['/etc/airlock/orca-loopback.nft', '${webroot_parent}/orca-web/']
assert m['artifacts']['serve_ports'] == ['https_port']
assert m['serve'] == {'https': {'https_port': 'gate_port'}}
assert m['artifacts']['units'] == [
    'airlock-orca-xvfb.service', 'airlock-orca.service',
    {'name': 'airlock-orca-firewall.service', 'scope': 'system'}]

abi = tomllib.loads((app.parents[1] / 'abi/apps/orca.toml').read_text())
assert abi['capabilities'] == ['rooted-artifact', 'system-unit']

firewall = subprocess.check_output([
    'bash', '-c', 'source "$1/render.sh"; render_orca_unit_firewall 18821 /etc/airlock/orca-loopback.nft',
    '_', str(app)], text=True)
assert 'ExecStart=/bin/sh -c \'/usr/sbin/nft delete table inet airlock_orca 2>/dev/null; /usr/sbin/nft -f /etc/airlock/orca-loopback.nft\'' in firewall
assert 'ExecStop=/usr/sbin/nft delete table inet airlock_orca' in firewall

# The app declares ownership; generic ledger preflight/removal remains the one
# cleanup engine. No app-local privileged delete path may race or bypass it.
deactivate = (app / 'deactivate.sh').read_text()
executable = [line.strip() for line in deactivate.splitlines()
              if line.strip() and not line.lstrip().startswith('#')]
assert executable == ['set -euo pipefail', 'exit 0']

operational = '\n'.join((app / name).read_text() for name in (
    'airlock-app.toml', 'install.sh', 'render.sh', 'deactivate.sh', 'smoke.sh'))
for legacy in ('/etc/dev-hub/orca-firewall.nft',
               '/etc/nginx/devhub-orca-card.html', 'swk-orca'):
    assert legacy not in operational
assert 'NFT_FILE="/etc/airlock/orca-loopback.nft"' in operational
assert 'ORCA_SERVE_ROOT="$(dirname "$WEBROOT")/orca-web"' in operational

# A clean uninstall can be recovered from immutable package inputs.
install = (app / 'install.sh').read_text()
pin_values = subprocess.check_output([
    'bash', '-c', 'source "$1/release-pin.sh"; printf "%s\\n%s\\n" "$VER" "$SHA256"',
    '_', str(app)], text=True).splitlines()
assert pin_values == [
    '1.4.139',
    '35ab8dc3b1427544ea1fc67f8c54a337f0b9b4d315abee4eedd9306006b43fb2',
]
assert install.count('. "$HERE/release-pin.sh"') == 1
assert not re.search(r'(?m)^\s*(?:export\s+|readonly\s+|declare(?:\s+-\S+)*\s+)?(?:VER|SHA256)\s*(?:\+?=)', install)
assert 'URL="https://github.com/stablyai/orca/releases/download/v${VER}/${ASSET}"' in install
assert 'APPIMAGE="$ORCA_DIR/orca-${VER}.AppImage"' in install
assert '[ "$got" = "$SHA256" ]' in install
pin = dict(line.split(': ', 1) for line in (app / 'web-bundle/VERSION').read_text().splitlines()
           if ': ' in line and not line.startswith('#'))
assert pin == {
    'orca-appimage-version': '1.4.139',
    'web-source-commit': '5f2818525ff41e7d99345b788a1b5ae13d5bd5c2',
    'web-index-asset': 'assets/web-index-7YTHIMhi.js',
    'dist-file-count': '385',
    'dist-tree-sha256': '14f5c2087f1996b5d9d6397387e323c8bccedf242406bd26d3c547688112f052',
}
assert pin_values[0] == pin['orca-appimage-version']
PY

# OR-N3: pure targeted restart matrix; an Orca-only edit never bounces Xvfb.
# shellcheck source=/dev/null
source "$APP/state.sh"
[ -z "$(orca_restart_plan 0 1 1 0 0 0 1)" ]
[ "$(orca_restart_plan 0 1 1 1 0 0 1)" = airlock-orca.service ]
[ "$(orca_restart_plan 0 1 1 0 1 0 1)" = airlock-orca.service ]
[ "$(orca_restart_plan 0 1 1 0 0 1 1)" = airlock-orca.service ]
[ "$(orca_restart_plan 1 1 1 0 0 0 1)" = $'airlock-orca-xvfb.service\nairlock-orca.service' ]
[ "$(orca_restart_plan 0 1 0 0 0 0 1)" = $'airlock-orca-xvfb.service\nairlock-orca.service' ]

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/cgroup/fixture/live" "$tmp/cgroup/fixture/orphan" \
  "$tmp/cgroup/fixture/unknown" "$tmp/proc/101" "$tmp/proc/202"
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$ORCA_SYSTEMCTL_LOG"
case "$*" in
  '--user show airlock-orca-xvfb.service -p NeedDaemonReload --value') printf 'yes\n' ;;
  '--user show airlock-orca.service -p NeedDaemonReload --value') printf 'no\n' ;;
  '--user is-active --quiet airlock-orca.service') exit 0 ;;
  '--user show airlock-orca.service -p ActiveEnterTimestamp --value') printf '2026-01-01 00:00:00 UTC\n' ;;
  "--user list-units --all --no-legend --plain app-orca-*.scope")
    printf 'app-orca-live.scope loaded active running\napp-orca-orphan.scope loaded active running\napp-orca-unknown.scope loaded active running\n' ;;
  '--user show app-orca-live.scope -p ControlGroup --value') printf '/fixture/live\n' ;;
  '--user show app-orca-orphan.scope -p ControlGroup --value') printf '/fixture/orphan\n' ;;
  '--user show app-orca-unknown.scope -p ControlGroup --value') printf '/fixture/unknown\n' ;;
  '--user stop app-orca-orphan.scope') exit 0 ;;
  '--user stop '*) exit 92 ;;
  *) exit 93 ;;
esac
SH
cat > "$tmp/bin/loginctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$ORCA_LOGINCTL_LOG"
[ "$*" = 'show-user fixture-user -p Linger --value' ] || exit 91
printf 'no\n'
SH
chmod +x "$tmp/bin/systemctl" "$tmp/bin/loginctl"
export ORCA_SYSTEMCTL_LOG="$tmp/systemctl.log" ORCA_LOGINCTL_LOG="$tmp/loginctl.log"
export PATH="$tmp/bin:$PATH"

# NeedDaemonReload is an explicit pre-reload query; stale AppRun uses service age.
orca_unit_needs_reload airlock-orca-xvfb.service
if orca_unit_needs_reload airlock-orca.service; then fail "false NeedDaemonReload accepted"; fi
apprun="$tmp/AppRun"
printf '#!/bin/sh\n' >"$apprun"
touch -d '2026-01-02 00:00:00 UTC' "$apprun"
orca_apprun_is_stale airlock-orca.service "$apprun"

# OR-N4: observe/warn only. The fake rejects every verb except show-user.
messages="$(warn_orca_linger fixture-user 2>&1)"
[[ "$messages" == *'observe only'* ]]
[ "$(cat "$ORCA_LOGINCTL_LOG")" = 'show-user fixture-user -p Linger --value' ]
if rg -n 'enable-linger' "$APP/install.sh" "$APP/state.sh"; then fail "install enables linger"; fi

# OR-S3: preserve live --serve and unreadable evidence; stop only proven orphan.
printf '101\n' >"$tmp/cgroup/fixture/live/cgroup.procs"
printf '202\n' >"$tmp/cgroup/fixture/orphan/cgroup.procs"
printf '303\n' >"$tmp/cgroup/fixture/unknown/cgroup.procs"
printf '%s\0' '/opt/orca/AppRun' 'serve' '--port' '18821' >"$tmp/proc/101/cmdline"
printf '%s\0' '/opt/orca/AppRun' 'helper' >"$tmp/proc/202/cmdline"
export ORCA_CGROUP_ROOT="$tmp/cgroup" ORCA_PROC_ROOT="$tmp/proc"
: >"$ORCA_SYSTEMCTL_LOG"
scope_messages="$(reconcile_orca_scopes 2>&1)"
grep -Fxq -- '--user stop app-orca-orphan.scope' "$ORCA_SYSTEMCTL_LOG"
if grep -Fq -- '--user stop app-orca-live.scope' "$ORCA_SYSTEMCTL_LOG" \
   || grep -Fq -- '--user stop app-orca-unknown.scope' "$ORCA_SYSTEMCTL_LOG"; then
  fail "live or unknown scope was stopped"
fi
[[ "$scope_messages" == *'preserved live scope'* && "$scope_messages" == *'unknown evidence'* ]]

# ExecStopPost renders the exact same scope evidence boundary.
bash -c 'source "$1/render.sh"; render_orca_reap_script' _ "$APP" >"$tmp/reap.sh"
bash -n "$tmp/reap.sh"
: >"$ORCA_SYSTEMCTL_LOG"
HOME="$tmp/reap-home" bash "$tmp/reap.sh" >"$tmp/reap.out" 2>&1
grep -Fxq -- '--user stop app-orca-orphan.scope' "$ORCA_SYSTEMCTL_LOG"
if grep -Fq -- '--user stop app-orca-live.scope' "$ORCA_SYSTEMCTL_LOG" \
   || grep -Fq -- '--user stop app-orca-unknown.scope' "$ORCA_SYSTEMCTL_LOG"; then
  fail "rendered reaper stopped live or unknown scope"
fi

# OR-C2: full installer dry-run emits no files. Only AIRLOCK_RENDER_DIR may hold
# deterministic render artifacts; real HOME/config/web roots stay untouched.
stub="$tmp/stub-root"
mkdir -p "$stub/install" "$stub/gate"
cat > "$stub/install/lib.sh" <<'SH'
log() { printf '%s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }
require_cmd() { :; }
airlock_load() {
  AIRLOCK_ORCA_GATE_PORT=18820 AIRLOCK_ORCA_BACKEND_PORT=18821 AIRLOCK_ORCA_HTTPS_PORT=8446
  AIRLOCK_OWNER=owner@example.test AIRLOCK_IDENTITY_HEADER=X-Test-Identity
}
airlock_panel_url() { :; }
airlock_run() { printf '[dry-call] %s\n' "$*"; }
airlock_quiet() { "$@"; }
ts_fqdn() { printf 'fixture.ts.net\n'; }
write_if_changed() { local dst="$1"; local tmp; tmp="$(mktemp)"; cat >"$tmp"; if [ -f "$dst" ] && cmp -s "$tmp" "$dst"; then rm "$tmp"; return 1; fi; install -d "$(dirname "$dst")"; mv "$tmp" "$dst"; return 0; }
render_loopback_nft() { printf 'table inet %s { # port %s\n}\n' "$1" "$2"; }
SH
cat > "$stub/gate/nginx-lib.sh" <<'SH'
emit_owner_gate() { printf 'server { listen %s; proxy_pass http://%s; }\n' "$1" "$2"; }
SH
dry_home="$tmp/dry-home" dry_confd="$tmp/dry-confd" dry_webroot="$tmp/dry-webroot"
mkdir -p "$dry_home"
AIRLOCK_ROOT="$stub" AIRLOCK_APP_DIR="$APP" AIRLOCK_DRY_RUN=1 HOME="$dry_home" \
  AIRLOCK_CONFD="$dry_confd" AIRLOCK_WEBROOT="$dry_webroot" \
  bash "$APP/install.sh" >"$tmp/dry.log"
[ -z "$(find "$dry_home" -mindepth 1 -print -quit)" ]
[ ! -e "$dry_confd" ] && [ ! -e "$dry_webroot" ]
contains "$tmp/dry.log" '[dry] render nginx fragment:'

render_root="$tmp/render-root"
AIRLOCK_ROOT="$stub" AIRLOCK_APP_DIR="$APP" AIRLOCK_DRY_RUN=1 HOME="$dry_home" \
  AIRLOCK_RENDER_DIR="$render_root" AIRLOCK_CONFD="$tmp/ignored-confd" \
  AIRLOCK_WEBROOT="$tmp/ignored-webroot" bash "$APP/install.sh" >"$tmp/render.log"
for rendered in \
  confd/servers.d/orca.conf units/airlock-orca-xvfb.service \
  units/airlock-orca.service bin/airlock-orca-reap \
  etc-airlock/orca-loopback.nft etc-systemd-system/airlock-orca-firewall.service; do
  [ -f "$render_root/$rendered" ] || fail "render output absent: $rendered"
done
[ -z "$(find "$dry_home" -mindepth 1 -print -quit)" ]
[ ! -e "$tmp/ignored-confd" ] && [ ! -e "$tmp/ignored-webroot" ]

# OR-C3 installer fails closed if the shipped verifier is missing/non-executable.
fake_app="$tmp/fake-app"
mkdir -p "$fake_app/bin"
cp "$APP/install.sh" "$APP/render.sh" "$APP/state.sh" "$APP/release-pin.sh" "$fake_app/"
ln -s "$APP/web-bundle" "$fake_app/web-bundle"
printf '#!/bin/sh\nexit 0\n' >"$fake_app/bin/verify-web-bundle.sh"
chmod 644 "$fake_app/bin/verify-web-bundle.sh"
if AIRLOCK_ROOT="$stub" AIRLOCK_APP_DIR="$fake_app" AIRLOCK_DRY_RUN=1 HOME="$dry_home" \
  AIRLOCK_CONFD="$tmp/missing-verifier-confd" AIRLOCK_WEBROOT="$tmp/missing-verifier-web" \
  bash "$fake_app/install.sh" >"$tmp/missing-verifier.log" 2>&1; then
  fail "non-executable verifier was accepted"
fi
contains "$tmp/missing-verifier.log" 'verifier missing or non-executable'

# OR-C3 executable refresh: clean source commit -> exact pins/scrub; dirty,
# incomplete-body, and residual PII sources all fail before replacing output.
fixture="$tmp/source"
mkdir -p "$fixture/dist/assets"
git -C "$fixture" init -q -b fixture
git -C "$fixture" config user.name parity-fixture
git -C "$fixture" config user.email parity-fixture@example.test
cat >"$fixture/dist/web-index.html" <<'HTML'
<html><body><script type="module" src="assets/web-index-Fixture.js"></script></body></html>
HTML
printf '재연결 중… Orca 런타임에 다시 연결하고 있습니다. 연결되면 이 터미널이 자동으로 이어집니다. orca-web.fixture\n' \
  >"$fixture/dist/assets/web-index-Fixture.js"
git -C "$fixture" add dist
git -C "$fixture" -c core.hooksPath=/dev/null commit -q -m valid
output="$tmp/refreshed"
"$APP/bin/refresh-web-bundle.sh" --source "$fixture" --appimage-version 1.4.139 --output "$output" >/dev/null
"$APP/bin/verify-web-bundle.sh" --quiet --bundle "$output"
source_sha="$(git -C "$fixture" rev-parse HEAD)"
grep -Fxq "web-source-commit: $source_sha" "$output/VERSION"
grep -Fq 'Reconnecting…' "$output/dist/assets/web-index-Fixture.js"
if grep -Eq '재연결|orca-web\.' "$output/dist/assets/web-index-Fixture.js"; then fail "scrub left source text"; fi

printf 'dirty\n' >>"$fixture/dist/assets/web-index-Fixture.js"
if "$APP/bin/refresh-web-bundle.sh" --source "$fixture" --appimage-version 1.4.139 --output "$output" >/dev/null 2>&1; then
  fail "dirty refresh source was accepted"
fi
grep -Fxq "web-source-commit: $source_sha" "$output/VERSION"
git -C "$fixture" restore dist
printf '<html><body>truncated' >"$fixture/dist/web-index.html"
git -C "$fixture" add dist && git -C "$fixture" -c core.hooksPath=/dev/null commit -q -m incomplete
if "$APP/bin/refresh-web-bundle.sh" --source "$fixture" --appimage-version 1.4.139 --output "$output" >/dev/null 2>&1; then
  fail "incomplete source body was accepted"
fi
grep -Fxq "web-source-commit: $source_sha" "$output/VERSION"
git -C "$fixture" checkout -q HEAD~1 -- dist
printf ' josh-dev\n' >>"$fixture/dist/assets/web-index-Fixture.js"
git -C "$fixture" add dist && git -C "$fixture" -c core.hooksPath=/dev/null commit -q -m pii
if "$APP/bin/refresh-web-bundle.sh" --source "$fixture" --appimage-version 1.4.139 --output "$output" >/dev/null 2>&1; then
  fail "PII-bearing source was accepted"
fi
grep -Fxq "web-source-commit: $source_sha" "$output/VERSION"

echo 'ok: Orca parity (C2/C3/C4/N3/N4/S2/S3/S4 executable)'
