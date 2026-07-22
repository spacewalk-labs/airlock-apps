# orca — browser Orca ADE behind the Airlock owner gate

One browser tab attaches to this box's [**Orca ADE**](https://github.com/stablyai/orca)
(a git-worktree parallel-agent IDE) — **no local install**. Authentication is your
**Tailscale identity** (no password); the box **owner only** may enter.

```
browser ──https/WireGuard──▶ tailscale serve :8446
                              │  identity header injected by tailscale serve
                              ▼
                   127.0.0.1:18820  nginx owner gate  ── not the owner? 403
                              │  (WS-safe proxy: no X-Forwarded-*, which would
                              ▼   break orca's Origin check)
                   0.0.0.0:18821  orca serve  ── nft loopback-only (gate reaches it,
                              │                    the tailnet cannot)
                    ┌─────────┴──────────┐
              web client            runtime
              (web-index.html)      (owns the worktrees, terminals, agents;
                                     keeps running even if the client disconnects)
```

Ports come from `airlock.toml` (`[apps.orca]`: `https_port` / `gate_port` /
`backend_port`); the values above are the defaults.

## v1 uses the upstream web client

This installs the vendor `orca serve` and serves the **web client that ships inside
it**. A patched web-bundle — local browser render instead of JPEG streaming, a fix
for terminals dying on reload, element-comment (Grab) — exists but lives in its own
repo that must be opened separately. Wiring it in is a **documented follow-up**, not
part of v1. Nothing here deploys a web overlay or redirect.

## Why the nft loopback rule

`orca serve` has **no `--host` flag**, so it binds `0.0.0.0`. An nft table
(`render_loopback_nft airlock_orca <backend_port>`, from `install/lib.sh`) drops any
non-loopback traffic to the backend port, so the **only** route in is
`tailscale serve` → the nginx owner gate. A small systemd oneshot re-applies the
rule on boot (nft is not persistent by default). See `SECURITY.md`.

## Runtime prerequisites (handled by `install.sh`)

- **Xvfb + GTK/nss/gbm libraries** — orca is Electron (Chromium); even headless
  `serve` needs an X display and the GTK runtime, or it crashes. `install.sh`
  installs them via `apt` (with a t64/non-t64 fallback for Ubuntu `noble`) and runs
  a **dedicated persistent Xvfb** unit for orca's display.
- **The AppImage** is downloaded from `stablyai/orca` and **sha256-verified**
  (mismatch aborts). It is `--appimage-extract`ed because the FUSE mount fails under
  `systemd --user`.
- **`sudo`** is needed for `apt` (runtime libs), `nft` (loopback rule + boot unit),
  and `tailscale serve` (HTTPS ingress). `AIRLOCK_DRY_RUN=1` prints every such step
  instead of running it (the nginx fragment is still written — it is config).
- **x86_64 only** — the pinned SHA is for the amd64 AppImage.

## Usage — add a project first

Opening a terminal on an empty screen fails with
`Local PTYs are unavailable in the web client`: with no project, the terminal falls
back to the `local` execution host (your laptop), which the browser has no PTY for.
Instead: **add a project** → host = **`Orca Server`** (this box) → pick a folder →
open the workspace → open terminals/agents **inside it** (they attach to the box's
runtime). The project list is browser-local state, so a fresh browser starts empty —
re-add the project; the runtime's worktrees are still there.

## Files

| File | Role |
|---|---|
| `install.sh` | provision + verify AppImage · Xvfb & `orca serve` systemd (`--user`) units · nft loopback rule · nginx owner-gate fragment · `tailscale serve` |
| `smoke.sh` | gate health: backend reachable, owner 200/302, deny 403, no-header 403 |

The loopback firewall reuses the shared template `gate/loopback-only.nft.tpl` (via
`render_loopback_nft`); there is no per-app `.nft` file.
