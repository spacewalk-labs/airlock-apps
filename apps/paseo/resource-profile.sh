#!/usr/bin/env bash
# shellcheck shell=bash
# Pure helpers for Paseo's unit resource profile. Keep this separate from the
# installer so threshold behaviour can be tested without an Airlock host.

paseo_effective_memory_cap_bytes() {
  local root="${1:-/sys/fs/cgroup}" cgroup_file="${2:-/proc/self/cgroup}" rel path cap best=""
  rel="$(awk -F: '$1 == "0" { print $3; exit }' "$cgroup_file" 2>/dev/null || true)"
  [ -n "$rel" ] || rel=/
  path="${root%/}${rel}"

  # A process may live below a delegated cgroup. Its usable limit is the lowest
  # numeric memory.max on the path to the cgroup root; `max` imposes no ceiling.
  while :; do
    cap="$(cat "$path/memory.max" 2>/dev/null || true)"
    case "$cap" in
      ''|max|*[!0-9]*) ;;
      *) if [ -z "$best" ] || [ "$cap" -lt "$best" ]; then best="$cap"; fi ;;
    esac
    [ "$path" = "${root%/}" ] && break
    path="$(dirname "$path")"
    case "$path" in "${root%/}"/*|"${root%/}") ;; *) break ;; esac
  done
  printf '%s\n' "${best:-max}"
}

# paseo_resource_profile CAP_BYTES [TASKSMAX]
# Prints MemoryMax, MemoryHigh and TasksMax. Returns 64 below the small profile.
paseo_resource_profile() {
  local cap="$1" tasksmax="${2:-24576}"
  local gib=$((1024 * 1024 * 1024))
  if [ "$cap" -lt "$((7 * gib))" ]; then
    return 64
  elif [ "$cap" -ge "$((16 * gib))" ]; then
    printf '14G 12G %s\n' "$tasksmax"
  else
    printf '6.5G 6G %s\n' "$tasksmax"
  fi
}
