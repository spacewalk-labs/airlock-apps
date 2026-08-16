#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"

bash -n "$APP/install.sh" "$APP/render.sh" "$APP/state.sh" \
  "$APP/deactivate.sh" "$APP/smoke.sh"

# Rendered release contracts: exact unit boundaries, held policies, and the main
# route (browse=false so these assertions cannot accidentally pass on its sidecar).
unit="$(bash -c 'source "$1/render.sh"; render_paseo_unit \
  "/future/npm:/future/claude:/usr/bin" "/fixture/home" "box.tail.test" 8447 \
  "/future/npm/paseo" 6767 "/usr/bin/python3" "/app/paseo-clear-stale-pid.py" \
  "28G" "24G" "infinity" "NoNewPrivileges=yes"' _ "$APP")"
grep -Fxq 'UnsetEnvironment=OPENAI_API_KEY' <<<"$unit"
grep -Fxq 'TimeoutStopSec=20' <<<"$unit"
grep -Fxq 'After=network.target' <<<"$unit"
! grep -Fxq 'After=default.target' <<<"$unit"
grep -Fxq 'ExecStartPre=-/usr/bin/python3 /app/paseo-clear-stale-pid.py /fixture/home/.paseo/paseo.pid' <<<"$unit"
grep -Fxq 'Environment=PASEO_HOSTNAMES=box.tail.test,box.tail.test:8447,localhost' <<<"$unit"
grep -Fxq 'MemoryMax=28G' <<<"$unit"       # PA-N5 hold remains public policy
grep -Fxq 'MemoryHigh=24G' <<<"$unit"      # PA-N5 hold remains public policy
grep -Fxq 'TasksMax=infinity' <<<"$unit"   # PA-N6 hold remains public policy
grep -Fxq 'NoNewPrivileges=yes' <<<"$unit" # PA-N3 hold remains public policy

nginx="$(bash -c 'source "$1/render.sh"; render_paseo_nginx \
  18822 6767 box.tail.test 8447 /opt/airlock-return.js "" false 6768 ""' _ "$APP")"
for directive in \
  'proxy_read_timeout 86400s;' \
  'proxy_send_timeout 86400s;' \
  'proxy_buffering off;'; do
  [ "$(grep -Fc "$directive" <<<"$nginx")" -eq 1 ]
done
grep -Fq 'proxy_set_header Host box.tail.test:8447;' <<<"$nginx"
! grep -Fq 'location /browse-view/' <<<"$nginx"

APP="$APP" python3 - <<'PY'
import json
import os
import pathlib
import tomllib

app = pathlib.Path(os.environ["APP"])
install = (app / "install.sh").read_text()
render = (app / "render.sh").read_text()
manifest = tomllib.loads((app / "airlock-app.toml").read_text())
anchors = json.loads((app / "patches" / "anchor-manifest.json").read_text())

# Installation order is the state-recovery contract: observe stale manager state,
# then clear it, and leave the pure decision in charge of the restart.
observe = 'paseo_unit_needs_daemon_reload airlock-paseo.service'
reload = 'airlock_run systemctl --user daemon-reload'
decide = 'paseo_should_restart "$need_restart" "$prior_daemon_reload" "$unit_active"'
assert install.index(observe) < install.index(reload) < install.index(decide)
assert 'enable-linger' not in install
assert '20) die "Codex ambient-key anchors missing or ambiguous' in install
assert 'Codex provider not found ($CODEX_AGENT_JS) — cannot enforce' in install

# Kept/retired dispositions remain executable contracts, not prose: canonical
# identities, future provider PATH, branding/ports, no x86-only rejection, and
# the existing process/credential safety patches all remain wired.
assert manifest["artifacts"]["units"] == [
    "airlock-paseo.service", "airlock-paseo-browse-host.service"]
for marker in ('$HOME/.local/bin', '$HOME/.npm-global/bin',
               'render_paseo_icon_favicon', 'orphan-process-guard.mjs',
               'orphan-process-group.mjs', 'credential-key-preservation.mjs'):
    assert marker in install, marker
assert 'x86_64' not in install and 'uname -m' not in install
defaults = manifest["config"]["defaults"]
assert defaults == {
    "https_port": 8447, "gate_port": 18822, "backend_port": 6767,
    "browse": False, "browse_ws_port": 6768, "version": ""}
assert manifest["audience"] == {"supported": ["owner"], "default": "owner"}

# PA-C2 remains on hold: only exact fqdn, fqdn:port, and localhost are accepted.
assert 'Environment=PASEO_HOSTNAMES=${FQDN},${FQDN}:${HTTPS_PORT},localhost' in render
ids = {entry["id"] for entry in anchors["patches"]}
assert "codex-strip-ambient-openai-key" in ids
print("ok: Paseo rendered and retained disposition contracts")
PY

# Deterministic state fixtures: NeedDaemonReload=yes forces restart, while an
# unchanged active unit does not. Missing linger is observation-only.
(
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  mkdir "$tmp/bin"
  cat >"$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$PASEO_SYSTEMCTL_LOG"
printf '%s\n' "${PASEO_RELOAD_STATE:-no}"
SH
  cat >"$tmp/bin/loginctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$PASEO_LOGINCTL_LOG"
[ "$1" = show-user ] || exit 91
printf 'no\n'
SH
  chmod +x "$tmp/bin/systemctl" "$tmp/bin/loginctl"
  export PASEO_SYSTEMCTL_LOG="$tmp/systemctl.log"
  export PASEO_LOGINCTL_LOG="$tmp/loginctl.log"
  messages=''
  log() { messages="${messages}${messages:+|}$*"; }
  # shellcheck source=/dev/null
  source "$APP/state.sh"

  PASEO_RELOAD_STATE=yes PATH="$tmp/bin:$PATH" paseo_unit_needs_daemon_reload airlock-paseo.service
  [ "$(cat "$PASEO_SYSTEMCTL_LOG")" = '--user show airlock-paseo.service -p NeedDaemonReload --value' ]
  paseo_should_restart 0 yes active
  paseo_should_restart 1 no active
  paseo_should_restart 0 no inactive
  if paseo_should_restart 0 no active; then exit 1; fi

  PATH="$tmp/bin:$PATH" warn_paseo_linger fixture-user
  [ "$(cat "$PASEO_LOGINCTL_LOG")" = 'show-user fixture-user -p Linger --value' ]
  [[ "$messages" == *'WARN: linger is not enabled'* ]]
  [[ "$messages" == *'Paseo did not enable it'* ]]
)

# Synthetic upstream bundle: deterministic patch output, executable key behavior,
# idempotence, and fail-closed ambiguity handling without touching installed Paseo.
(
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  mkdir -p "$tmp/server/agent/providers"
  printf '{"type":"module"}\n' >"$tmp/package.json"
  cat >"$tmp/server/paseo-env.js" <<'JS'
export function createExternalProcessEnv(baseEnv, ...overlays) {
    const env = { ...baseEnv };
    for (const overlay of overlays) {
        for (const [key, value] of Object.entries(overlay ?? {})) {
            if (value === undefined) delete env[key];
            else env[key] = value;
        }
    }
    return env;
}
JS
  cat >"$tmp/server/agent/provider-launch-config.js" <<'JS'
export function createProviderEnvSpec({ runtimeSettings, overlays = [] } = {}) {
    return { envOverlay: Object.assign({}, runtimeSettings?.env, ...overlays.filter(Boolean)) };
}
JS
  upstream="$tmp/server/agent/providers/codex.js"
  cat >"$upstream" <<'JS'
function createProviderEnv() {}
function createProviderEnvSpec({ runtimeSettings, overlays }) {
    return { env: Object.assign({}, runtimeSettings?.env, ...overlays.filter(Boolean)) };
}
function spawnProcess(command, args, options) { return { command, args, options }; }
export function buildCodexAppServerEnv(runtimeSettings, launchEnv) {
    return createProviderEnv({
        runtimeSettings,
        overlays: [launchEnv],
    });
}
export class FixtureProvider {
    constructor(runtimeSettings) { this.runtimeSettings = runtimeSettings; }
    spawnAppServer(launchEnv) {
        return spawnProcess("codex", ["app-server"], {
            detached: true,
            stdio: ["pipe", "pipe", "pipe"],
            ...createProviderEnvSpec({
                runtimeSettings: this.runtimeSettings,
                overlays: [launchEnv],
            }),
        });
    }
}
JS
  cp "$upstream" "$tmp/codex-2.js"
  node "$APP/patches/codex-strip-ambient-openai-key.mjs" "$upstream" >/dev/null
  node "$APP/patches/codex-strip-ambient-openai-key.mjs" "$tmp/codex-2.js" >/dev/null
  cmp "$upstream.paseo-new.mjs" "$tmp/codex-2.js.paseo-new.mjs"
  node --check "$upstream.paseo-new.mjs"
  node "$APP/patches/codex-strip-ambient-openai-key.test.mjs" "$upstream.paseo-new.mjs" >/dev/null \
    || exit 1
  node --input-type=module - "$upstream.paseo-new.mjs" <<'JS'
import { pathToFileURL } from "node:url";
const mod = await import(pathToFileURL(process.argv[2]));
const spawned = new mod.FixtureProvider({
    env: { OPENAI_API_KEY: "FAKE-explicit" },
}).spawnAppServer({ OPENAI_API_KEY: "FAKE-launch" });
if (spawned.options.env.OPENAI_API_KEY !== "FAKE-explicit") process.exit(1);
JS

  mv "$upstream.paseo-new.mjs" "$upstream"
  rc=0
  node "$APP/patches/codex-strip-ambient-openai-key.mjs" "$upstream" >/dev/null || rc=$?
  [ "$rc" -eq 10 ]
  [ ! -e "$upstream.paseo-new.mjs" ]

  # The internal predecessor used the same sentinel but returned {}, so a public
  # install must upgrade that state rather than mistake it for the fixed version.
  legacy="$tmp/server/agent/providers/legacy.js"
  sed 's/return { OPENAI_API_KEY: explicitKey };/return {};/' "$upstream" >"$legacy"
  node "$APP/patches/codex-strip-ambient-openai-key.mjs" "$legacy" >/dev/null
  grep -Fq 'return { OPENAI_API_KEY: explicitKey };' "$legacy.paseo-new.mjs"
  node "$APP/patches/codex-strip-ambient-openai-key.test.mjs" "$legacy.paseo-new.mjs" >/dev/null \
    || exit 1

  cp "$tmp/codex-2.js" "$tmp/drift.js"
  printf '\nexport function buildCodexAppServerEnv(runtimeSettings, launchEnv) {}\n' >>"$tmp/drift.js"
  rc=0
  node "$APP/patches/codex-strip-ambient-openai-key.mjs" "$tmp/drift.js" >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 20 ]
  [ ! -e "$tmp/drift.js.paseo-new.mjs" ]
)

echo 'ok: Paseo parity (migrate PA-R2/N4/N7/C3/S3; holds N3/N5/N6/C2 unchanged; keep/retire preserved)'
