# devterm — browser web terminal

A terminal in the browser (via [ttyd](https://github.com/tsl0922/ttyd), MIT),
behind the Airlock owner gate. Sessions run in `tmux`, so closing the tab and
reopening the same URL resumes the same session.

## How it works

```
browser --https--> tailscale serve :https_port --(identity)--> nginx owner-gate
        --(owner only / else 403)--> ttyd 127.0.0.1:ttyd_port --> tmux (auto-resume)
```

- **Auth**: the Airlock nginx gate (`$owner_ok`) — owner-only. See `../../SECURITY.md`.
- **Sessions**: `?arg=<name>` selects/creates a tmux session (`devterm-shell`).
- **ttyd** is provisioned automatically (sha256-pinned x86_64 release).

## Config (`[apps.devterm]`)

`https_port` (secure-context, clipboard) · `public_port` (convenience http) ·
`gate_port` (loopback nginx gate) · `ttyd_port` (loopback ttyd) · `font_size`.

## Not yet ported (enhancement)

The internal version ships a custom xterm.js 5.x client (mobile session tabs,
forced Ctrl+C, touch scroll, CJK IME, clipboard-image upload) instead of ttyd's
built-in client. That client is a **planned enhancement** — this version uses
ttyd's built-in web UI, which is fully functional but less mobile-polished.
The claude-account switcher (an internal, out-of-repo dependency) is intentionally
omitted.
