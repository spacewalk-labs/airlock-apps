# devterm — browser web terminal

A terminal in the browser with a **custom xterm.js client** and a **programmable
gate**, in front of a [ttyd](https://github.com/tsl0922/ttyd) (MIT) PTY backend,
behind the Airlock owner gate. Sessions run in `tmux`, so closing the tab and
reopening the same URL resumes the same session.

## How it works

```
browser --https--> tailscale serve :https_port --(identity)--> nginx owner-gate
        --(owner only / else 403)--> devterm-gate 127.0.0.1:backend_port
                                     --> serves the custom client + API
                                     --> proxies /ws,/token --> ttyd --> tmux (auto-resume)
```

- **Auth**: the Airlock nginx gate (`$owner_ok`) — owner-only. The loopback
  `devterm-gate` re-checks the identity header (`AIRLOCK_IDENTITY_HEADER`) as
  defense-in-depth. See `../../SECURITY.md`.
- **Client**: a self-contained xterm.js 5.x front (vendored under `web/vendor/`, MIT):
  live session tab bar (`tmux ls`), tab rename/kill/color/reorder/new, `Ctrl+1-9`,
  a toolbar (copy modal / OSC52, font size, 10 server-persisted themes, file upload,
  image paste + annotate, pane zoom / equalize), seamless auto-reconnect, a mobile key
  bar with forced Ctrl+C / touch scroll / CJK-IME handling, clickable URLs, and a
  return-to-Airlock affordance (origin derived from `location`, not hardcoded).
- **ttyd** is provisioned automatically (sha256-pinned x86_64 release) and is used
  only as the PTY backend; its built-in web UI is never served.

## Config (`[apps.devterm]`)

`https_port` (secure-context, clipboard) · `public_port` (plaintext; 301s to
`https_port` and serves nothing) · `redirect_port` (loopback server behind that
301) · `gate_port` (loopback nginx gate) · `backend_port` (loopback devterm-gate) ·
`ttyd_port` (loopback ttyd) · `font_size` · `lang`.

### Optional features (default off, degrade cleanly when their deps are absent)

- **Claude account pool + Codex login** (`accounts = true`): switch between Claude
  accounts and manage a Codex login from the account popup. Depends on the
  repo-external `claude-switch` / `claude-status` tools (paths via `claude_switch` /
  `claude_status`) and the `codex` CLI. When off or the tools are missing, the UI is
  hidden and the endpoints return a clean "disabled".
- **Fleet usage store** (`fleet_store` / `fleet_store_url`): annotates the account
  popup with utilization from a shared store. No host is hardcoded; unset = no usage
  numbers (the list still works).
- **markwand file-open**: click a file path in the terminal to open it in markwand.
  Turns on automatically when `[apps.markwand]` is enabled and `[paths].code_root`
  is set.
- **Orca worktree sidebar** (`orca_shim`): an experimental layout showing Orca's
  worktrees with per-worktree agent launchers. Needs the Orca CLI shim; falls back to
  the top-tab layout otherwise.
- **Remote sessions** (`remote_hosts = "hostA,hostB"`): also surface tmux sessions
  from the listed ssh hosts as tabs. Empty = local only (fully inert).
