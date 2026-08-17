#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$APP/../.." && pwd)"

fail() {
  echo "FAIL code-server parity: $*" >&2
  exit 1
}

contains() {
  local file="$1" literal="$2"
  grep -Fq -- "$literal" "$file" || fail "${file#"$APP/"} missing contract: $literal"
}

not_contains_runtime() {
  local literal="$1"
  if grep -FRq -- "$literal" \
    "$APP/install.sh" "$APP/bin" "$APP/manager" "$APP/render.sh" "$APP/web"; then
    fail "runtime unexpectedly seeds retired profile value: $literal"
  fi
}

tree_snapshot() {
  local root="$1"
  (
    cd "$root"
    find . -printf '%y %m %U %G %s %T@ %P %l\n' | sort
    find . -type f -print0 | sort -z | xargs -0 -r sha256sum
  )
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fixture_home="$tmp/home"

# CS-S1/CS-S2: positive controls cover both former layouts, collisions, and
# non-colliding data. Hash every source file before and after migration: this is
# an exhaustive fixture (not a sample) for the two declared legacy roots.
mkdir -p \
  "$fixture_home/.local/share/code-server-slots/1/User" \
  "$fixture_home/.local/share/code-server-slots/2/User" \
  "$fixture_home/.local/share/code-server-slots/2/User/private" \
  "$fixture_home/.local/share/code-server-slots/extensions/multi.ext" \
  "$fixture_home/.local/share/code-server-slots/extensions/multi.new" \
  "$fixture_home/.config/code-server-tabs" \
  "$fixture_home/.local/share/code-server/User" \
  "$fixture_home/.local/share/code-server/extensions/single.ext" \
  "$fixture_home/.local/share/airlock-code-server/slots/1/User" \
  "$fixture_home/.local/share/airlock-code-server/extensions/multi.ext" \
  "$fixture_home/.config/airlock-code-server"

printf 'multi settings\n' > "$fixture_home/.local/share/code-server-slots/1/User/settings.json"
printf 'multi precedence\n' > "$fixture_home/.local/share/code-server-slots/1/User/source-order.json"
printf 'slot two\n' > "$fixture_home/.local/share/code-server-slots/2/User/state.json"
printf 'private state\n' > "$fixture_home/.local/share/code-server-slots/2/User/private/state.json"
printf 'outside state\n' > "$tmp/outside-state.json"
ln -s "$tmp/outside-state.json" "$fixture_home/.local/share/code-server-slots/2/User/outbound.json"
chmod 700 "$fixture_home/.local/share/code-server-slots/2/User/private"
touch -d '2020-01-01 00:00:00 UTC' "$fixture_home/.local/share/code-server-slots/2/User/private"
legacy_private_metadata="$(stat -c '%a:%Y' "$fixture_home/.local/share/code-server-slots/2/User/private")"
mkfifo "$fixture_home/.local/share/code-server-slots/2/User/transient.fifo"
printf 'multi extension\n' > "$fixture_home/.local/share/code-server-slots/extensions/multi.ext/data"
printf 'new multi extension\n' > "$fixture_home/.local/share/code-server-slots/extensions/multi.new/data"
printf 'legacy tabs\n' > "$tmp/linked-tabs.json"
ln -s "$tmp/linked-tabs.json" "$fixture_home/.config/code-server-tabs/tabs.json"
printf 'single settings\n' > "$fixture_home/.local/share/code-server/User/settings.json"
printf 'single precedence\n' > "$fixture_home/.local/share/code-server/User/source-order.json"
printf 'single history\n' > "$fixture_home/.local/share/code-server/User/history.json"
printf 'single extension\n' > "$fixture_home/.local/share/code-server/extensions/single.ext/data"
printf 'canonical settings\n' > "$fixture_home/.local/share/airlock-code-server/slots/1/User/settings.json"
printf 'canonical extension\n' > "$fixture_home/.local/share/airlock-code-server/extensions/multi.ext/data"
printf 'canonical tabs\n' > "$fixture_home/.config/airlock-code-server/tabs.json"
mkdir -p "$tmp/linked-slot/User"
printf 'linked slot\n' > "$tmp/linked-slot/User/state.json"
ln -s "$tmp/linked-slot" "$fixture_home/.local/share/code-server-slots/3"
linked_slot_target="$(readlink "$fixture_home/.local/share/code-server-slots/3")"
chmod 751 "$fixture_home/.local/share/airlock-code-server/slots/1/User"
touch -d '2025-01-01 00:00:00 UTC' "$fixture_home/.local/share/airlock-code-server/slots/1/User"
canonical_dir_before="$(stat -c '%a:%Y' "$fixture_home/.local/share/airlock-code-server/slots/1/User")"

source_snapshot() {
  (
    cd "$fixture_home"
    find .local/share/code-server-slots .config/code-server-tabs .local/share/code-server \
      -type f -print0 | sort -z | xargs -0 sha256sum
  )
}
before="$(source_snapshot)"
HOME="$fixture_home" "$APP/bin/migrate-legacy-state"
canonical_once="$(cd "$fixture_home" && find .local/share/airlock-code-server .config/airlock-code-server -type f -print0 | sort -z | xargs -0 sha256sum)"
HOME="$fixture_home" "$APP/bin/migrate-legacy-state"
canonical_twice="$(cd "$fixture_home" && find .local/share/airlock-code-server .config/airlock-code-server -type f -print0 | sort -z | xargs -0 sha256sum)"
after="$(source_snapshot)"
[[ "$after" == "$before" ]] || fail "legacy source files changed after copy-in"
[[ "$canonical_twice" == "$canonical_once" ]] || fail "second copy-in changed canonical state"
canonical_dir_after="$(stat -c '%a:%Y' "$fixture_home/.local/share/airlock-code-server/slots/1/User")"
[[ "$canonical_dir_after" == "$canonical_dir_before" ]] \
  || fail "legacy copy changed existing canonical directory metadata"

grep -Fxq 'canonical settings' "$fixture_home/.local/share/airlock-code-server/slots/1/User/settings.json" \
  || fail "canonical slot collision was overwritten"
grep -Fxq 'slot two' "$fixture_home/.local/share/airlock-code-server/slots/2/User/state.json" \
  || fail "legacy multi-slot state was not copied"
grep -Fxq 'linked slot' "$fixture_home/.local/share/airlock-code-server/slots/3/User/state.json" \
  || fail "symlinked legacy slot root was not copied"
grep -Fxq 'linked slot' "$tmp/linked-slot/User/state.json" \
  || fail "symlinked legacy slot source changed"
[[ -L "$fixture_home/.local/share/code-server-slots/3" \
   && "$(readlink "$fixture_home/.local/share/code-server-slots/3")" == "$linked_slot_target" ]] \
  || fail "symlinked legacy slot root changed"
[[ "$(stat -c '%a:%Y' "$fixture_home/.local/share/airlock-code-server/slots/2/User/private")" == "$legacy_private_metadata" ]] \
  || fail "new canonical directory did not preserve private legacy metadata"
[[ ! -e "$fixture_home/.local/share/airlock-code-server/slots/2/User/transient.fifo" ]] \
  || fail "unsupported legacy FIFO was copied"
[[ -p "$fixture_home/.local/share/code-server-slots/2/User/transient.fifo" ]] \
  || fail "legacy FIFO source changed"
[[ ! -e "$fixture_home/.local/share/airlock-code-server/slots/2/User/outbound.json" ]] \
  || fail "legacy tree copied an outbound symlink"
[[ "$(readlink "$fixture_home/.local/share/code-server-slots/2/User/outbound.json")" == "$tmp/outside-state.json" ]] \
  || fail "legacy outbound symlink source changed"
grep -Fxq 'outside state' "$tmp/outside-state.json" || fail "outbound symlink target changed"
grep -Fxq 'multi precedence' "$fixture_home/.local/share/airlock-code-server/slots/1/User/source-order.json" \
  || fail "legacy multi-slot state did not take precedence over single-instance state"
grep -Fxq 'single history' "$fixture_home/.local/share/airlock-code-server/slots/1/User/history.json" \
  || fail "legacy single-instance state was not copied"
grep -Fxq 'canonical extension' "$fixture_home/.local/share/airlock-code-server/extensions/multi.ext/data" \
  || fail "canonical extension collision was overwritten"
grep -Fxq 'new multi extension' "$fixture_home/.local/share/airlock-code-server/extensions/multi.new/data" \
  || fail "legacy multi-slot extension was not copied"
grep -Fxq 'single extension' "$fixture_home/.local/share/airlock-code-server/extensions/single.ext/data" \
  || fail "legacy single-instance extension was not copied"
grep -Fxq 'canonical tabs' "$fixture_home/.config/airlock-code-server/tabs.json" \
  || fail "canonical tabs collision was overwritten"
rm "$fixture_home/.config/airlock-code-server/tabs.json"
HOME="$fixture_home" "$APP/bin/migrate-legacy-state"
grep -Fxq 'legacy tabs' "$fixture_home/.config/airlock-code-server/tabs.json" \
  || fail "legacy tab preferences were not copied"
[[ ! -L "$fixture_home/.config/airlock-code-server/tabs.json" ]] \
  || fail "canonical tabs retained an outbound legacy symlink"
[[ "$(readlink "$fixture_home/.config/code-server-tabs/tabs.json")" == "$tmp/linked-tabs.json" ]] \
  || fail "legacy tabs symlink changed"

# Canonical app roots are write boundaries, not redirectable links. Positive control:
# the same legacy tabs source above copied into a real directory.
unsafe_home="$tmp/unsafe-home"
mkdir -p "$unsafe_home/.config/code-server-tabs" "$tmp/outside-tabs"
printf 'unsafe tabs\n' > "$unsafe_home/.config/code-server-tabs/tabs.json"
mkdir -p "$unsafe_home/.config"
ln -s "$tmp/outside-tabs" "$unsafe_home/.config/airlock-code-server"
outside_tabs_before="$(tree_snapshot "$tmp/outside-tabs")"
set +e
HOME="$unsafe_home" "$APP/bin/migrate-legacy-state" >/dev/null 2>&1
unsafe_rc=$?
set -e
[[ "$unsafe_rc" -ne 0 ]] || fail "canonical tabs symlink was accepted"
[[ "$(tree_snapshot "$tmp/outside-tabs")" == "$outside_tabs_before" ]] \
  || fail "canonical tabs symlink changed outside tree"

unsafe_config_home="$tmp/unsafe-config-home"
outside_config="$tmp/outside-config"
mkdir -p "$unsafe_config_home" "$outside_config/code-server-tabs"
ln -s "$outside_config" "$unsafe_config_home/.config"
printf 'ancestor tabs\n' > "$outside_config/code-server-tabs/tabs.json"
outside_config_before="$(tree_snapshot "$outside_config")"
set +e
HOME="$unsafe_config_home" "$APP/bin/migrate-legacy-state" >/dev/null 2>&1
unsafe_config_rc=$?
set -e
[[ "$unsafe_config_rc" -ne 0 ]] || fail "canonical .config ancestor symlink was accepted"
[[ "$(tree_snapshot "$outside_config")" == "$outside_config_before" ]] \
  || fail "canonical .config ancestor symlink changed outside tree"

unsafe_share_home="$tmp/unsafe-share-home"
outside_share="$tmp/outside-share"
mkdir -p "$unsafe_share_home/.local" "$outside_share/code-server-slots/1/User"
ln -s "$outside_share" "$unsafe_share_home/.local/share"
printf 'ancestor slot\n' > "$outside_share/code-server-slots/1/User/state.json"
outside_share_before="$(tree_snapshot "$outside_share")"
set +e
HOME="$unsafe_share_home" "$APP/bin/migrate-legacy-state" >/dev/null 2>&1
unsafe_share_rc=$?
set -e
[[ "$unsafe_share_rc" -ne 0 ]] || fail "canonical share ancestor symlink was accepted"
[[ "$(tree_snapshot "$outside_share")" == "$outside_share_before" ]] \
  || fail "canonical share ancestor symlink changed outside tree"

for boundary in app-root slots user-dir; do
  boundary_home="$tmp/unsafe-$boundary-home"
  boundary_outside="$tmp/outside-$boundary"
  mkdir -p "$boundary_home/.local/share/code-server/User" "$boundary_outside"
  printf '%s\n' "$boundary" > "$boundary_home/.local/share/code-server/User/state.json"
  case "$boundary" in
    app-root)
      ln -s "$boundary_outside" "$boundary_home/.local/share/airlock-code-server"
      escaped_state="$boundary_outside/slots/1/User/state.json"
      ;;
    slots)
      mkdir -p "$boundary_home/.local/share/airlock-code-server"
      ln -s "$boundary_outside" "$boundary_home/.local/share/airlock-code-server/slots"
      escaped_state="$boundary_outside/1/User/state.json"
      ;;
    user-dir)
      mkdir -p "$boundary_home/.local/share/airlock-code-server/slots/1"
      ln -s "$boundary_outside" "$boundary_home/.local/share/airlock-code-server/slots/1/User"
      escaped_state="$boundary_outside/state.json"
      ;;
  esac
  boundary_outside_before="$(tree_snapshot "$boundary_outside")"
  set +e
  HOME="$boundary_home" "$APP/bin/migrate-legacy-state" >/dev/null 2>&1
  boundary_rc=$?
  set -e
  [[ "$boundary_rc" -ne 0 ]] || fail "canonical $boundary symlink was accepted"
  [[ ! -e "$escaped_state" ]] || fail "canonical $boundary symlink escaped write boundary"
  [[ "$(tree_snapshot "$boundary_outside")" == "$boundary_outside_before" ]] \
    || fail "canonical $boundary symlink changed outside tree"
done

# Every destination file created by the migrator must be under one of the two
# canonical Airlock state roots. The fixture includes positive-control sources.
while IFS= read -r path; do
  case "$path" in
    .local/share/code-server-slots/*|.config/code-server-tabs/*|.local/share/code-server/*|\
    .local/share/airlock-code-server/*|.config/airlock-code-server/*) ;;
    *) fail "migration wrote outside declared roots: $path" ;;
  esac
done < <(cd "$fixture_home" && find . \( -type f -o -type l \) -printf '%P\n' | sort)
contains "$APP/install.sh" 'LEGACY_MIGRATOR="$HERE/bin/migrate-legacy-state"'
grep -Fxq '  "$LEGACY_MIGRATOR"' "$APP/install.sh" \
  || fail "install.sh does not execute the state migrator"
contains "$APP/install.sh" 'if [ "${AIRLOCK_DRY_RUN:-0}" = 1 ]; then'

# Exercise the full install entrypoint with external commands/configuration stubbed.
# An unreachable or conditionally wrapped migrator leaves no canonical output and
# fails this fixture; the dry-run traversal must complete without copying state.
stub_root="$tmp/stub-root"
mkdir -p "$stub_root/install" "$stub_root/gate"
printf '%s\n' \
  'require_cmd() { :; }' \
  'die() { echo "$*" >&2; exit 1; }' \
  'log() { :; }' \
  'airlock_run() { :; }' \
  'write_if_changed() { mkdir -p "$(dirname "$1")"; cat > "$1"; }' \
  'airlock_load() {' \
  '  AIRLOCK_CODE_SERVER_GATE_PORT=18808' \
  '  AIRLOCK_CODE_SERVER_BACKEND_PORT=18811' \
  '  AIRLOCK_CODE_SERVER_HTTPS_PORT=8444' \
  '  AIRLOCK_CODE_SERVER_MANAGER_PORT=18810' \
  '  AIRLOCK_CODE_SERVER_SLOTS=4' \
  '  AIRLOCK_OWNER=owner@example.test' \
  '  AIRLOCK_IDENTITY_HEADER=X-Test-Identity' \
  '}' > "$stub_root/install/lib.sh"
printf '%s\n' 'emit_slot_gate() { :; }' > "$stub_root/gate/nginx-lib.sh"
install_home="$tmp/install-home"
mkdir -p "$install_home/.local/share/code-server/User"
printf 'entrypoint legacy\n' > "$install_home/.local/share/code-server/User/entrypoint.json"
mkdir -p "$install_home/.local/lib/code-server-4.128.0-linux-amd64/bin" "$install_home/.local/bin"
printf '%s\n' '#!/usr/bin/env bash' 'echo 4.128.0' \
  > "$install_home/.local/lib/code-server-4.128.0-linux-amd64/bin/code-server"
chmod +x "$install_home/.local/lib/code-server-4.128.0-linux-amd64/bin/code-server"
set +e
HOME="$install_home" AIRLOCK_ROOT="$stub_root" AIRLOCK_APP_DIR="$APP" \
  AIRLOCK_CONFD="$tmp/install-confd" AIRLOCK_WEBROOT="$tmp/install-webroot" \
  "$APP/install.sh" >/dev/null 2>&1
install_rc=$?
set -e
[[ "$install_rc" -eq 0 ]] || fail "stubbed full install flow failed"
grep -Fxq 'entrypoint legacy' \
  "$install_home/.local/share/airlock-code-server/slots/1/User/entrypoint.json" \
  || fail "install entrypoint did not execute state migration"
dry_home="$tmp/dry-home"
mkdir -p "$dry_home/.local/share/code-server/User"
printf 'dry legacy\n' > "$dry_home/.local/share/code-server/User/dry.json"
HOME="$dry_home" AIRLOCK_ROOT="$stub_root" AIRLOCK_APP_DIR="$APP" \
  AIRLOCK_DRY_RUN=1 AIRLOCK_CONFD="$tmp/dry-confd" AIRLOCK_WEBROOT="$tmp/dry-webroot" \
  "$APP/install.sh"
[[ ! -e "$dry_home/.local/share/airlock-code-server/slots/1/User/dry.json" ]] \
  || fail "dry-run copied legacy state"

# Both retained config stores are lifecycle data: manager tabs and code-server's
# own config/extensions-adjacent state. Omitting either would make RPO=0 incomplete.
contains "$ROOT/abi/apps/code-server.toml" '"~/.config/airlock-code-server/tabs.json"'
contains "$ROOT/abi/apps/code-server.toml" '"~/.config/code-server/"'

# CS-A1/CS-U1/CS-C1: configured slots and ports drive API, shell, and manifests.
contains "$APP/airlock-app.toml" 'slots = 4'
contains "$APP/airlock-app.toml" 'base = "backend_port"'
contains "$APP/airlock-app.toml" 'count = "slots"'
contains "$APP/manager/manager.py" 'MAX_SLOTS = int(os.environ.get("AIRLOCK_CODE_SERVER_SLOTS", "4"))'
contains "$APP/manager/manager.py" 'VALID_SLOTS = {str(n) for n in range(1, MAX_SLOTS + 1)}'
contains "$APP/manager/manager.py" '"maxSlots": MAX_SLOTS'
contains "$APP/web/shell.html" 'data-max-slots="@@MAX_SLOTS@@"'
contains "$APP/web/shell.html" 'MAX_SLOTS_HARD_CAP = 64'
contains "$APP/web/shell.html" 'DEFAULT_COLOR_CYCLE'

PYTHONDONTWRITEBYTECODE=1 AIRLOCK_IDENTITY_HEADER=X-Test-Identity AIRLOCK_CODE_SERVER_ALLOW=owner@example.test \
AIRLOCK_CODE_SERVER_SLOTS=6 AIRLOCK_CODE_SERVER_BACKEND_PORT=19000 \
  python3 - "$APP/manager/manager.py" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("airlock_code_server_manager", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.VALID_SLOTS == {"1", "2", "3", "4", "5", "6"}
assert module.slot_port(1) == 19000
assert module.slot_port(6) == 19005
assert module.slot_unit(6) == "airlock-code-server@6.service"
PY

# CS-N1/CS-N2: canonical unit names and non-cyclic network ordering.
slot_unit="$tmp/slot.unit"
manager_unit="$tmp/manager.unit"
source "$APP/render.sh"
render_code_server_unit_slot 18810 '1|2|3|4' 4 > "$slot_unit"
render_code_server_unit_manager 18810 4 18811 owner@example.test X-Test-Identity > "$manager_unit"
grep -Fxq 'After=network.target' "$slot_unit" || fail "slot unit network ordering"
grep -Fxq 'After=network.target' "$manager_unit" || fail "manager unit network ordering"
! grep -Fxq 'After=default.target' "$slot_unit" || fail "slot unit has target cycle"
! grep -Fxq 'After=default.target' "$manager_unit" || fail "manager unit has target cycle"
contains "$APP/manager/manager.py" 'UNIT_TEMPLATE = "airlock-code-server@%d.service"'
! grep -FRq -- 'swk-codeserver' "$APP/install.sh" "$APP/bin" "$APP/manager" "$APP/render.sh" \
  || fail "runtime retains internal unit identity"

# CS-N3: changed content restarts; unchanged content only ensures services start.
contains "$APP/install.sh" 'if [ "$changed" = 1 ]; then'
contains "$APP/install.sh" 'airlock_run systemctl --user restart airlock-code-server-manager.service'
contains "$APP/install.sh" 'airlock_run systemctl --user start airlock-code-server-manager.service'

# CS-C2: operator-selected identity is injected and the manager fails closed.
contains "$APP/render.sh" 'Environment=AIRLOCK_IDENTITY_HEADER=${AIRLOCK_IDENTITY_HEADER}'
contains "$APP/manager/manager.py" 'if not IDENT_HEADER:'
contains "$APP/manager/manager.py" 'if login not in ALLOW:'

# CS-C3: both supported architectures retain distinct pinned artifacts.
contains "$APP/install.sh" 'x86_64)'
contains "$APP/install.sh" 'aarch64|arm64)'
contains "$APP/install.sh" '79ba26bf186e5268a22b7c17b30a5f288a16c37791f0b86c27859e8fef103188'
contains "$APP/install.sh" 'f8f02c2a81d1a433a4d132716a6f0405f690f6d70dd955942e95e87356db8a10'

# CS-C4 retire: exhaustive over app-owned runtime inputs (not this regression).
# Positive control: the legacy fixture above contains settings.json, proving the
# migration path preserves user settings while the runtime seeds no host profile.
not_contains_runtime '--install-extension'
not_contains_runtime 'workbench.colorTheme'
not_contains_runtime 'security.workspace.trust.enabled'
not_contains_runtime 'window.zoomLevel'

echo "ok   parity code-server (11/11 matrix IDs)"
