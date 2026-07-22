# code-server — browser IDE

VS Code in the browser ([coder/code-server](https://github.com/coder/code-server),
MIT), behind the Airlock owner gate.

```
browser --https--> tailscale serve :https_port --(identity)--> nginx owner-gate
        --(owner only / else 403)--> code-server 127.0.0.1:backend_port
```

- **Auth**: Airlock nginx gate (`$owner_ok`), owner-only. code-server itself runs
  `--auth none` — safe only because the gate is the sole path and the backend
  binds loopback. See `../../SECURITY.md`.
- **Binary**: sha256-pinned release (no piped installer).

## Config (`[apps.code-server]`)

`https_port` · `gate_port` (loopback gate) · `backend_port` (loopback IDE).

## Not yet ported (enhancement)

The internal version ships a multi-tab **slot manager** (up to 4 concurrent IDE
instances with a tab bar, `manager_port`/`slots`). v1 runs a **single instance**;
the slot manager is a planned enhancement. `manager_port`/`slots` in the config
are reserved for it.
