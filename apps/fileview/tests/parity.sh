#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"

bash -n "$APP/install.sh" "$APP/render.sh" "$APP/state.sh" \
  "$APP/deactivate.sh" "$APP/smoke.sh"

# The markwand-era render checks (legacy /edit redirects, /markwand/split,
# markserv PATH pinning) lost their referent when the owner-approved rename
# replaced markserv with the single-document viewer: those routes no longer
# exist in any tree, private or public. What survives is transposed, not
# weakened: the long-poll editor proxy timeout (MW-R3), the exact-match viewer
# entry, the fall-through 404 that keeps /fileview/* off the hub SPA fallback,
# and the D7/#249 owner guard on every content location.
rendered="$(bash -c 'source "$1/render.sh"; render_fileview_nginx 18799' _ "$APP")"
grep -Fq 'location /fileview/api/ {' <<<"$rendered"
grep -Fq 'proxy_pass http://127.0.0.1:18799;' <<<"$rendered"
grep -Fq 'proxy_read_timeout 86400s;' <<<"$rendered"
grep -Fq 'location = /fileview/ {' <<<"$rendered"
grep -Fq 'try_files /__fv/viewer.html =404;' <<<"$rendered"
grep -Fq 'location /fileview/ {' <<<"$rendered"
grep -Fq 'return 404;' <<<"$rendered"
# Default audience is owner: every content location carries the explicit guard.
# shellcheck disable=SC2016 # $owner_ok is an nginx variable, literal by design
guard='if ($owner_ok = 0) { return 403; }'
[ "$(grep -Fc "$guard" <<<"$rendered")" -ge 3 ]
shared="$(bash -c 'source "$1/render.sh"; render_fileview_nginx 18799 shared' _ "$APP")"
! grep -Fq "$guard" <<<"$shared"
# Unknown audience fails closed to the owner guard, never open.
unknown="$(bash -c 'source "$1/render.sh"; render_fileview_nginx 18799 bogus' _ "$APP")"
grep -Fq "$guard" <<<"$unknown"
unit="$(bash -c 'source "$1/render.sh"; render_fileview_unit_filebrowser 18799 /usr/local/bin/filebrowser /home/u/.config/airlock-fileview/fb.db' _ "$APP")"
grep -Fq -- '--root /' <<<"$unit"
grep -Fq -- '--followExternalSymlinks=false' <<<"$unit"
grep -Fq -- '--disableTypeDetectionByHeader' <<<"$unit"
grep -Fq 'WorkingDirectory=%h/.config/airlock-fileview' <<<"$unit"

APP="$APP" python3 - <<'PY'
import json
import os
import pathlib
import tomllib

app = pathlib.Path(os.environ['APP'])
manifest = json.loads((app / 'static' / 'fileview-manifest.json').read_text())
assert manifest['name'] == 'File Viewer'
assert manifest['short_name'] == 'File Viewer'
assert manifest['id'] == '/fileview/'
assert manifest['start_url'] == '/fileview/'
assert manifest['scope'] == '/fileview/'
assert manifest['name'] != 'SWK Dev Hub'
assert all(icon['src'].startswith('/assets/app-icons/fileview.') for icon in manifest['icons'])

html = (app / 'static' / 'viewer.html').read_text()
assert '<link rel="manifest" href="/__fv/fileview-manifest.json">' in html
install = (app / 'install.sh').read_text()
assert 'install -m644 "$HERE/static/fileview-manifest.json"' in install
assert 'backup_fileview_filebrowser_db "$FB_DB" 3' in install
assert install.index('backup_fileview_filebrowser_db "$FB_DB" 3') < install.index(
    'config set --baseURL /fileview')
assert 'branding.color' not in install
assert 'enable-linger' not in install

package = tomllib.loads((app / 'airlock-app.toml').read_text())
# home_aliases/agent_config_aliases left the config surface with
# [paths].code_root: filebrowser now runs with --root /, so there is no served
# subtree for a home alias to land in. The single remaining key is the port.
assert set(package['config']['defaults']) == {'filebrowser_port'}
# MW-N1 (unit naming stays airlock-prefixed), post-rename shape: one unit.
assert package['artifacts']['units'] == ['airlock-fileview.service']
# D7/#249: the audience is declared, defaulting closed to the owner.
assert package['audience'] == {'supported': ['owner', 'shared'], 'default': 'owner'}
render = (app / 'render.sh').read_text()
for marker in ('--followExternalSymlinks=false', '--disableTypeDetectionByHeader'):
    assert marker in render, marker
# MW-C1: the filebrowser release stays version-pinned (markserv retired with
# the rename, so its MS_VER pin has nothing left to pin).
assert 'FB_VER=2.63.18' in install
print('ok: fileview static parity contracts')
PY

# Alias fixtures run entirely under a disposable HOME/code root. The private
# ownership ledger is what lets the package reclaim only links it created.
(
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  export HOME="$tmp/home"
  mkdir -p "$HOME" "$tmp/code" "$HOME/workspace" "$HOME/projects"
  state="$HOME/.config/airlock/aliases"
  # shellcheck disable=SC2317 # called indirectly by sourced state helpers
  log() { :; }
  # shellcheck source=/dev/null
  source "$APP/state.sh"

  # Default-empty does not inspect or mutate an otherwise valid configured root.
  ln -s "$tmp/code" "$tmp/code-link"
  reconcile_fileview_home_aliases "$tmp/code-link" '' "$state"
  [ ! -e "$state" ]

  reconcile_fileview_home_aliases "$tmp/code" ' workspace, projects ' "$state"
  [ "$(readlink "$tmp/code/workspace")" = "$HOME/workspace" ]
  [ "$(readlink "$tmp/code/projects")" = "$HOME/projects" ]
  [ "$(cat "$state")" = $'projects\nworkspace' ]

  # Removing an allowed name reclaims the exact package-owned link.
  reconcile_fileview_home_aliases "$tmp/code" 'workspace' "$state"
  [ ! -e "$tmp/code/projects" ] && [ ! -L "$tmp/code/projects" ]

  # A disappeared source makes its owned symlink stale and safely removable.
  rm -rf "$HOME/workspace"
  reconcile_fileview_home_aliases "$tmp/code" 'workspace' "$state"
  [ ! -e "$tmp/code/workspace" ] && [ ! -L "$tmp/code/workspace" ]
  [ ! -e "$state" ]

  # Never adopt an existing path, even when a user-created link has the same target.
  mkdir -p "$HOME/workspace"
  ln -s "$HOME/workspace" "$tmp/code/workspace"
  reconcile_fileview_home_aliases "$tmp/code" 'workspace' "$state"
  [ ! -e "$state" ]
  reconcile_fileview_home_aliases "$tmp/code" '' "$state"
  [ -L "$tmp/code/workspace" ]
  rm "$tmp/code/workspace"

  # If an owned link is retargeted by the user, removal preserves it and drops ownership.
  reconcile_fileview_home_aliases "$tmp/code" 'workspace' "$state"
  rm "$tmp/code/workspace"
  ln -s "$HOME/projects" "$tmp/code/workspace"
  reconcile_fileview_home_aliases "$tmp/code" '' "$state"
  [ "$(readlink "$tmp/code/workspace")" = "$HOME/projects" ]
  [ ! -e "$state" ]
  rm "$tmp/code/workspace"

  # Traversal, hidden aliases, source symlinks, and existing real paths stay outside.
  if reconcile_fileview_home_aliases "$tmp/code" '../escape' "$state"; then exit 1; fi
  if reconcile_fileview_home_aliases "$tmp/code" '.claude' "$state"; then exit 1; fi
  [ ! -e "$tmp/escape" ] && [ ! -e "$tmp/code/.claude" ]
  ln -s "$tmp/outside" "$HOME/external"
  mkdir -p "$tmp/outside" "$tmp/code/occupied"
  reconcile_fileview_home_aliases "$tmp/code" 'external,occupied' "$state"
  [ ! -e "$tmp/code/external" ] && [ -d "$tmp/code/occupied" ]
  [ ! -e "$state" ]

  # A private-ledger parent symlink may not redirect package writes outside HOME.
  outside_state="$tmp/outside-state"
  mkdir -p "$outside_state" "$HOME/safe"
  rm -rf "$HOME/.config"
  ln -s "$outside_state" "$HOME/.config"
  if reconcile_fileview_home_aliases "$tmp/code" 'safe' "$state"; then exit 1; fi
  [ ! -e "$tmp/code/safe" ]
  [ -z "$(find "$outside_state" -mindepth 1 -maxdepth 1 -print -quit)" ]

  # MW-S2 measured compatibility is explicit, exact, and separately owned.
  rm -rf "$HOME/.config"
  mkdir -p "$HOME/.config" "$HOME/.claude" "$HOME/.codex" "$HOME/claude"
  home_state="$HOME/.config/airlock/fileview-home-aliases"
  agent_state="$HOME/.config/airlock/fileview-agent-config-aliases"
  reconcile_fileview_alias_sets "$tmp/code" '' 'claude,codex' "$home_state" "$agent_state"
  [ "$(readlink "$tmp/code/claude")" = "$HOME/.claude" ]
  [ "$(readlink "$tmp/code/codex")" = "$HOME/.codex" ]
  [ "$(cat "$agent_state")" = $'claude\ncodex' ]

  # Both transition directions converge in one call; an ambiguous simultaneous
  # claim is rejected before either ledger or target changes.
  reconcile_fileview_alias_sets "$tmp/code" 'claude' '' "$home_state" "$agent_state"
  [ "$(readlink "$tmp/code/claude")" = "$HOME/claude" ]
  [ ! -e "$tmp/code/codex" ] && [ ! -L "$tmp/code/codex" ]
  [ "$(cat "$home_state")" = claude ]
  [ ! -e "$agent_state" ]
  reconcile_fileview_alias_sets "$tmp/code" '' 'claude,codex' "$home_state" "$agent_state"
  [ "$(readlink "$tmp/code/claude")" = "$HOME/.claude" ]
  [ "$(readlink "$tmp/code/codex")" = "$HOME/.codex" ]
  before="$(find "$tmp/code" "$HOME/.config/airlock" -maxdepth 1 -printf '%p %l\n' | sort)"
  if reconcile_fileview_alias_sets "$tmp/code" 'claude' 'claude,codex' "$home_state" "$agent_state"; then exit 1; fi
  [ "$(find "$tmp/code" "$HOME/.config/airlock" -maxdepth 1 -printf '%p %l\n' | sort)" = "$before" ]

  reconcile_fileview_alias_sets "$tmp/code" '' '' "$home_state" "$agent_state"
  [ ! -e "$tmp/code/claude" ] && [ ! -L "$tmp/code/claude" ]
  [ ! -e "$tmp/code/codex" ] && [ ! -L "$tmp/code/codex" ]
  [ ! -e "$agent_state" ]

  # Wrapper callers test its status, so helper mutations must propagate errors
  # explicitly even when Bash disables errexit inside an OR-list function call.
  mkdir -p "$tmp/fail-bin"
  cat >"$tmp/fail-bin/ln" <<'SH'
#!/usr/bin/env bash
exit 73
SH
  chmod +x "$tmp/fail-bin/ln"
  if PATH="$tmp/fail-bin:$PATH" reconcile_fileview_alias_sets \
      "$tmp/code" '' 'claude,codex' "$home_state" "$agent_state"; then exit 1; fi
  [ ! -e "$agent_state" ]
)

# Backup fixtures prove same-directory atomic publication, a hard retention
# bound, and fail-closed behavior before a DB settings mutation could begin.
(
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  db="$tmp/fb.db"
  printf 'db-v1' >"$db"
  # shellcheck disable=SC2317 # called indirectly by sourced state helpers
  log() { :; }
  # shellcheck source=/dev/null
  source "$APP/state.sh"
  for _ in 1 2 3 4 5; do
    backup_fileview_filebrowser_db "$db" 3
  done
  mapfile -t backups < <(find "$tmp" -maxdepth 1 -type f -name 'fb.db.bak.*' | sort)
  [ "${#backups[@]}" -eq 3 ]
  for backup in "${backups[@]}"; do
    [ "$(cat "$backup")" = db-v1 ]
  done
  if find "$tmp" -maxdepth 1 -name '.fb.db.bak.tmp.*' | grep -q .; then exit 1; fi

  fakebin="$tmp/fakebin"
  mkdir "$fakebin"
  printf '#!/usr/bin/env bash\nexit 42\n' >"$fakebin/cp"
  chmod +x "$fakebin/cp"
  before="${#backups[@]}"
  if PATH="$fakebin:$PATH" backup_fileview_filebrowser_db "$db" 3; then exit 1; fi
  mapfile -t after < <(find "$tmp" -maxdepth 1 -type f -name 'fb.db.bak.*')
  [ "${#after[@]}" -eq "$before" ]
  if find "$tmp" -maxdepth 1 -name '.fb.db.bak.tmp.*' | grep -q .; then exit 1; fi
)

# Missing linger is observation-only: loginctl receives show-user, never enable.
(
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  mkdir "$tmp/bin"
  cat >"$tmp/bin/loginctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FILEVIEW_LOGINCTL_LOG"
[ "$1" = show-user ] || exit 91
printf 'no\n'
SH
  chmod +x "$tmp/bin/loginctl"
  export FILEVIEW_LOGINCTL_LOG="$tmp/loginctl.log"
  messages=''
  # shellcheck disable=SC2317 # called indirectly by sourced state helpers
  log() { messages="${messages}${messages:+|}$*"; }
  # shellcheck source=/dev/null
  source "$APP/state.sh"
  PATH="$tmp/bin:$PATH" warn_fileview_linger test-user
  [ "$(cat "$FILEVIEW_LOGINCTL_LOG")" = 'show-user test-user -p Linger --value' ]
  [[ "$messages" == *'WARN: linger is not enabled'* ]]
)

# MW-R1/R2 (legacy /edit + /markwand/split compatibility routes) and MW-C2
# (code_root) retired with markserv in the markwand->fileview rename: the
# routes and the key no longer exist on either side, so there is no parity
# left to hold. Everything else is transposed above under the new name.
echo 'ok: fileview parity (MW-U1/N1/N2/N3/C1/C3/S1/S2/S3 + retained R3/U2)'
