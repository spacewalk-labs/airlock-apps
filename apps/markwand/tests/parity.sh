#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"

bash -n "$APP/install.sh" "$APP/render.sh" "$APP/state.sh" \
  "$APP/deactivate.sh" "$APP/smoke.sh"

rendered="$(bash -c 'source "$1/render.sh"; render_markwand_nginx 18799 18801' _ "$APP")"
grep -Fq 'location = /edit  { return 302 /markwand/edit/; }' <<<"$rendered"
grep -Fq 'location = /edit/ { return 302 /markwand/edit/; }' <<<"$rendered"
grep -Fq 'location ~ ^/edit/(.+)$' <<<"$rendered"
# shellcheck disable=SC2016 # nginx variables must remain literal in rendered text
grep -Fq 'return 302 /markwand/edit/$1$is_args$args;' <<<"$rendered"
grep -Fq 'proxy_read_timeout 86400s;' <<<"$rendered"
grep -Fq '<script src="/airlock-return.js" data-mode="corner" defer></script>' <<<"$rendered"
grep -Fq 'location = /markwand/split {' <<<"$rendered"
[ "$(grep -Fc 'try_files /__mw/markwand-split.html =404;' <<<"$rendered")" -eq 2 ]

APP="$APP" python3 - <<'PY'
import json
import os
import pathlib
import tomllib

app = pathlib.Path(os.environ['APP'])
manifest = json.loads((app / 'static' / 'markwand-manifest.json').read_text())
assert manifest['name'] == 'Markwand'
assert manifest['short_name'] == 'Markwand'
assert manifest['id'] == '/markwand/'
assert manifest['start_url'] == '/markwand/'
assert manifest['scope'] == '/markwand/'
assert manifest['name'] != 'SWK Dev Hub'
assert all(icon['src'].startswith('/assets/app-icons/markwand.') for icon in manifest['icons'])

html = (app / 'static' / 'markwand-split.html').read_text()
assert '<link rel="manifest" href="/__mw/markwand-manifest.json">' in html
install = (app / 'install.sh').read_text()
assert 'install -m644 "$HERE/static/markwand-manifest.json"' in install
assert 'backup_markwand_filebrowser_db "$FB_DB" 3' in install
assert install.index('backup_markwand_filebrowser_db "$FB_DB" 3') < install.index(
    '"$FB_BIN" config set --baseURL /markwand/edit')
assert 'branding.color' not in install
assert 'enable-linger' not in install

package = tomllib.loads((app / 'airlock-app.toml').read_text())
assert package['config']['defaults']['home_aliases'] == ''
assert package['config']['defaults']['agent_config_aliases'] is False
assert package['artifacts']['units'] == [
    'airlock-markserv.service', 'airlock-filebrowser.service']
render = (app / 'render.sh').read_text()
for marker in ('Environment=PATH=${UNIT_PATH}', '--followExternalSymlinks=false'):
    assert marker in render, marker
for marker in ('MS_VER=1.17.4', 'FB_VER=2.63.18',
               'AIRLOCK_CODE_ROOT must be an absolute path'):
    assert marker in install, marker
print('ok: Markwand static parity contracts')
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
  reconcile_markwand_home_aliases "$tmp/code-link" '' "$state"
  [ ! -e "$state" ]

  reconcile_markwand_home_aliases "$tmp/code" ' workspace, projects ' "$state"
  [ "$(readlink "$tmp/code/workspace")" = "$HOME/workspace" ]
  [ "$(readlink "$tmp/code/projects")" = "$HOME/projects" ]
  [ "$(cat "$state")" = $'projects\nworkspace' ]

  # Removing an allowed name reclaims the exact package-owned link.
  reconcile_markwand_home_aliases "$tmp/code" 'workspace' "$state"
  [ ! -e "$tmp/code/projects" ] && [ ! -L "$tmp/code/projects" ]

  # A disappeared source makes its owned symlink stale and safely removable.
  rm -rf "$HOME/workspace"
  reconcile_markwand_home_aliases "$tmp/code" 'workspace' "$state"
  [ ! -e "$tmp/code/workspace" ] && [ ! -L "$tmp/code/workspace" ]
  [ ! -e "$state" ]

  # Never adopt an existing path, even when a user-created link has the same target.
  mkdir -p "$HOME/workspace"
  ln -s "$HOME/workspace" "$tmp/code/workspace"
  reconcile_markwand_home_aliases "$tmp/code" 'workspace' "$state"
  [ ! -e "$state" ]
  reconcile_markwand_home_aliases "$tmp/code" '' "$state"
  [ -L "$tmp/code/workspace" ]
  rm "$tmp/code/workspace"

  # If an owned link is retargeted by the user, removal preserves it and drops ownership.
  reconcile_markwand_home_aliases "$tmp/code" 'workspace' "$state"
  rm "$tmp/code/workspace"
  ln -s "$HOME/projects" "$tmp/code/workspace"
  reconcile_markwand_home_aliases "$tmp/code" '' "$state"
  [ "$(readlink "$tmp/code/workspace")" = "$HOME/projects" ]
  [ ! -e "$state" ]
  rm "$tmp/code/workspace"

  # Traversal, hidden aliases, source symlinks, and existing real paths stay outside.
  if reconcile_markwand_home_aliases "$tmp/code" '../escape' "$state"; then exit 1; fi
  if reconcile_markwand_home_aliases "$tmp/code" '.claude' "$state"; then exit 1; fi
  [ ! -e "$tmp/escape" ] && [ ! -e "$tmp/code/.claude" ]
  ln -s "$tmp/outside" "$HOME/external"
  mkdir -p "$tmp/outside" "$tmp/code/occupied"
  reconcile_markwand_home_aliases "$tmp/code" 'external,occupied' "$state"
  [ ! -e "$tmp/code/external" ] && [ -d "$tmp/code/occupied" ]
  [ ! -e "$state" ]

  # A private-ledger parent symlink may not redirect package writes outside HOME.
  outside_state="$tmp/outside-state"
  mkdir -p "$outside_state" "$HOME/safe"
  rm -rf "$HOME/.config"
  ln -s "$outside_state" "$HOME/.config"
  if reconcile_markwand_home_aliases "$tmp/code" 'safe' "$state"; then exit 1; fi
  [ ! -e "$tmp/code/safe" ]
  [ -z "$(find "$outside_state" -mindepth 1 -maxdepth 1 -print -quit)" ]

  # MW-S2 measured compatibility is explicit, exact, and separately owned.
  rm -rf "$HOME/.config"
  mkdir -p "$HOME/.config" "$HOME/.claude" "$HOME/.codex" "$HOME/claude"
  home_state="$HOME/.config/airlock/markwand-home-aliases"
  agent_state="$HOME/.config/airlock/markwand-agent-config-aliases"
  reconcile_markwand_alias_sets "$tmp/code" '' 'claude,codex' "$home_state" "$agent_state"
  [ "$(readlink "$tmp/code/claude")" = "$HOME/.claude" ]
  [ "$(readlink "$tmp/code/codex")" = "$HOME/.codex" ]
  [ "$(cat "$agent_state")" = $'claude\ncodex' ]

  # Both transition directions converge in one call; an ambiguous simultaneous
  # claim is rejected before either ledger or target changes.
  reconcile_markwand_alias_sets "$tmp/code" 'claude' '' "$home_state" "$agent_state"
  [ "$(readlink "$tmp/code/claude")" = "$HOME/claude" ]
  [ ! -e "$tmp/code/codex" ] && [ ! -L "$tmp/code/codex" ]
  [ "$(cat "$home_state")" = claude ]
  [ ! -e "$agent_state" ]
  reconcile_markwand_alias_sets "$tmp/code" '' 'claude,codex' "$home_state" "$agent_state"
  [ "$(readlink "$tmp/code/claude")" = "$HOME/.claude" ]
  [ "$(readlink "$tmp/code/codex")" = "$HOME/.codex" ]
  before="$(find "$tmp/code" "$HOME/.config/airlock" -maxdepth 1 -printf '%p %l\n' | sort)"
  if reconcile_markwand_alias_sets "$tmp/code" 'claude' 'claude,codex' "$home_state" "$agent_state"; then exit 1; fi
  [ "$(find "$tmp/code" "$HOME/.config/airlock" -maxdepth 1 -printf '%p %l\n' | sort)" = "$before" ]

  reconcile_markwand_alias_sets "$tmp/code" '' '' "$home_state" "$agent_state"
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
  if PATH="$tmp/fail-bin:$PATH" reconcile_markwand_alias_sets \
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
    backup_markwand_filebrowser_db "$db" 3
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
  if PATH="$fakebin:$PATH" backup_markwand_filebrowser_db "$db" 3; then exit 1; fi
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
printf '%s\n' "$*" >>"$MARKWAND_LOGINCTL_LOG"
[ "$1" = show-user ] || exit 91
printf 'no\n'
SH
  chmod +x "$tmp/bin/loginctl"
  export MARKWAND_LOGINCTL_LOG="$tmp/loginctl.log"
  messages=''
  # shellcheck disable=SC2317 # called indirectly by sourced state helpers
  log() { messages="${messages}${messages:+|}$*"; }
  # shellcheck source=/dev/null
  source "$APP/state.sh"
  PATH="$tmp/bin:$PATH" warn_markwand_linger test-user
  [ "$(cat "$MARKWAND_LOGINCTL_LOG")" = 'show-user test-user -p Linger --value' ]
  [[ "$messages" == *'WARN: linger is not enabled'* ]]
)

echo 'ok: Markwand parity (MW-R1/R2/U1/N1/N2/N3/C1/C2/C3/S1/S2/S3 + retained R3/U2)'
