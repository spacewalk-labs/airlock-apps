#!/usr/bin/env bash
# Markwand state helpers. Functions only: install.sh owns when they run.

_markwand_alias_name_ok() {
  case "$1" in
    ''|.*|*[!A-Za-z0-9._-]*) return 1 ;;
    *) return 0 ;;
  esac
}

_markwand_trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

_markwand_state_dir_safe() {
  local state_dir="$1" home_real state_real
  case "$HOME" in /*) ;; *) return 1 ;; esac
  home_real="$(readlink -m -- "$HOME")" || return 1
  state_real="$(readlink -m -- "$state_dir")" || return 1
  case "$state_real/" in "$home_real"/*) return 0 ;; *) return 1 ;; esac
}

# reconcile_markwand_home_aliases CODE_ROOT CSV STATE_FILE
#
# STATE_FILE is the ownership ledger. A pre-existing path is never adopted, and
# an owned link is removed/replaced only while it still points to the exact
# top-level $HOME directory recorded by its name. This keeps unrelated files and
# user-retargeted symlinks out of the reconciliation boundary.
reconcile_markwand_home_aliases() {
  local code_root="$1" csv="$2" state_file="$3"
  local state_dir name source target item tmp
  local -a parts=()
  local -A wanted=() previous=() owned=()

  IFS=',' read -r -a parts <<<"$csv"
  for item in "${parts[@]}"; do
    name="$(_markwand_trim "$item")"
    [ -n "$name" ] || continue
    _markwand_alias_name_ok "$name" || {
      log "invalid Markwand home alias '$name' (use a non-hidden top-level directory name)"
      return 1
    }
    wanted["$name"]=1
  done

  state_dir="$(dirname "$state_file")"
  if ! _markwand_state_dir_safe "$state_dir"; then
    log "refusing Markwand alias ownership ledger outside HOME: $state_file"
    # Default-empty must remain non-mutating even on a box whose config path is
    # externally symlinked. An enabled alias list fails closed before link work.
    [ "${#wanted[@]}" -eq 0 ] && return 0
    return 1
  fi
  if [ -L "$state_file" ]; then
    log "refusing symlinked Markwand alias ownership ledger: $state_file"
    [ "${#wanted[@]}" -eq 0 ] && return 0
    return 1
  fi
  if [ -f "$state_file" ]; then
    while IFS= read -r name || [ -n "$name" ]; do
      if _markwand_alias_name_ok "$name"; then
        previous["$name"]=1
      else
        log "ignoring invalid entry in Markwand alias ownership ledger"
      fi
    done <"$state_file"
  elif [ -e "$state_file" ]; then
    log "refusing non-file Markwand alias ownership ledger: $state_file"
    return 1
  fi
  # Preserve the default-empty contract: without a prior ownership ledger there
  # is no alias work and therefore no new restriction on the configured root.
  if [ "${#wanted[@]}" -eq 0 ] && [ "${#previous[@]}" -eq 0 ]; then
    return 0
  fi
  case "$code_root" in
    /*) ;;
    *) log "invalid Markwand code root for aliases: $code_root"; return 1 ;;
  esac
  [ -d "$code_root" ] || { log "Markwand code root does not exist: $code_root"; return 1; }
  [ ! -L "$code_root" ] || { log "Markwand code root must not be a symlink when home aliases are enabled"; return 1; }
  # Establish the private ledger boundary before touching aliases. In
  # particular, a symlinked parent that resolves outside HOME was rejected
  # above, so install/mktemp cannot be redirected to an external tree.
  install -d -m 700 "$state_dir" || return 1

  # Reclaim only aliases from the private ownership ledger, and only while the
  # link still has the exact target Markwand created.
  for name in "${!previous[@]}"; do
    [ -z "${wanted[$name]:-}" ] || continue
    source="$HOME/$name"
    target="$code_root/$name"
    if [ -L "$target" ] && [ "$(readlink -- "$target")" = "$source" ]; then
      rm -- "$target"
      log "removed Markwand home alias: $target"
    elif [ -e "$target" ] || [ -L "$target" ]; then
      log "preserving changed Markwand alias target: $target"
    fi
  done

  for name in "${!wanted[@]}"; do
    source="$HOME/$name"
    target="$code_root/$name"
    if [ "$source" = "$code_root" ]; then
      log "skipping recursive Markwand home alias: $name"
      continue
    fi
    if [ ! -d "$source" ] || [ -L "$source" ]; then
      if [ -n "${previous[$name]:-}" ] && [ -L "$target" ] \
          && [ "$(readlink -- "$target")" = "$source" ]; then
        rm -- "$target"
        log "removed stale Markwand home alias: $target"
      else
        log "skipping missing or symlinked Markwand home directory: $source"
      fi
      continue
    fi

    if [ -n "${previous[$name]:-}" ]; then
      if [ -L "$target" ] && [ "$(readlink -- "$target")" = "$source" ]; then
        owned["$name"]=1
      elif [ ! -e "$target" ] && [ ! -L "$target" ]; then
        ln -s -- "$source" "$target"
        owned["$name"]=1
        log "restored Markwand home alias: $target -> $source"
      else
        log "preserving changed Markwand alias target: $target"
      fi
    elif [ ! -e "$target" ] && [ ! -L "$target" ]; then
      ln -s -- "$source" "$target"
      owned["$name"]=1
      log "created Markwand home alias: $target -> $source"
    else
      # Identical user-created links are not silently adopted as package state.
      log "preserving pre-existing Markwand alias path: $target"
    fi
  done

  if [ "${#owned[@]}" -eq 0 ]; then
    [ ! -f "$state_file" ] || rm -- "$state_file"
    return 0
  fi
  tmp="$(mktemp "$state_dir/.markwand-home-aliases.tmp.XXXXXX")" || return 1
  if ! printf '%s\n' "${!owned[@]}" | LC_ALL=C sort >"$tmp"; then
    rm -f -- "$tmp"
    return 1
  fi
  chmod 600 "$tmp"
  if ! mv -f -- "$tmp" "$state_file"; then
    rm -f -- "$tmp"
    return 1
  fi
}

# backup_markwand_filebrowser_db DB KEEP
#
# Copy to a same-directory temporary file, then rename it into the backup set.
# A failed copy exposes no partial backup and prevents the caller's DB mutation.
backup_markwand_filebrowser_db() {
  local db="$1" keep="${2:-3}" dir base tmp backup i
  local -a backups=()
  [ -f "$db" ] && [ ! -L "$db" ] || return 1
  case "$keep" in ''|*[!0-9]*|0) return 1 ;; esac
  dir="$(dirname "$db")"
  base="$(basename "$db")"
  tmp="$(mktemp "$dir/.${base}.bak.tmp.XXXXXX")" || return 1
  if ! cp -p -- "$db" "$tmp"; then
    rm -f -- "$tmp"
    return 1
  fi
  backup="${db}.bak.$(date -u +%Y%m%dT%H%M%S%NZ).$$.${RANDOM}"
  if ! mv -- "$tmp" "$backup"; then
    rm -f -- "$tmp"
    return 1
  fi

  mapfile -t backups < <(
    find "$dir" -maxdepth 1 -type f -name "${base}.bak.*" \
      ! -name ".${base}.bak.tmp.*" -printf '%f\n' | LC_ALL=C sort -r
  )
  for ((i=keep; i<${#backups[@]}; i++)); do
    rm -f -- "$dir/${backups[$i]}"
  done
  log "backed up filebrowser DB: $backup (keeping $keep)"
}

warn_markwand_linger() {
  local who="${1:-}" linger
  if [ -z "$who" ]; then
    who="$(id -un 2>/dev/null || true)"
  fi
  if ! command -v loginctl >/dev/null 2>&1; then
    log "WARN: loginctl unavailable; could not verify linger for ${who:-current user}"
    return 0
  fi
  linger="$(loginctl show-user "$who" -p Linger --value 2>/dev/null || true)"
  [ "$linger" = yes ] \
    || log "WARN: linger is not enabled for ${who:-current user}; Markwand did not enable it"
}
