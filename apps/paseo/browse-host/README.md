# paseo browse-host — server-side browser panels (FOLLOW-UP, not wired into v1)

This is a **loopback WebSocket sidecar** that gives the paseo daemon a
server-side browser automation host: a Playwright-backed headless Chromium the
agents drive through paseo's native `browser_*` tools, plus a live browser panel
the owner can watch/drive from the web UI.

> **Status: documented follow-up.** The Airlock v1 paseo installer
> (`../install.sh`) does **not** run this. It ships here as labeled source so the
> wiring can be reviewed and enabled later. Nothing in v1 installs Playwright,
> the web-ui patch, or the browse WebSocket port (`browse_ws_port` stays reserved
> in `airlock.toml`).

## What it takes to wire in

1. **Playwright + Chromium.** `install.sh` runs `npm install` (adds `playwright` +
   `ws`) and `playwright install chromium`. This is a heavy dependency the v1
   daemon deliberately avoids.
2. **A SHA-pinned web-ui bundle patch.** `bin/patch-web-ui.js` applies three
   minimal, verified-unique edits to paseo's minified web-ui bundle (un-gate the
   "New browser" button on web + mark the pane container) and injects the
   companion `web/browse-view-client.js`. It is **fail-loud**: on a `@getpaseo/cli`
   version bump the bundle SHA changes, the patcher refuses, and a human must
   re-derive the anchors. This lockstep with an upstream minified bundle is why it
   is a follow-up, not v1.
3. **Reconcile ports/origin with `airlock.toml`.** The unit defaults
   (`PASEO_WS_URL` backend `6767`, stream port `6768`, allowed Origin on the
   `https_port`) must match your resolved `[apps.paseo]` config, and the nginx
   owner gate must proxy `/browse-view/` to the loopback stream port.

## Licensing

- **The sidecar is MIT.** `host.js`, `security.js`, `executor.js`,
  `stream-server.js`, `commands.js`, `bin/paseo-browse-host.js`, `web/*.js`, the
  tests, `install.sh`, and `smoke.sh` are an **independent** loopback-WS sidecar —
  they do **not** import paseo. Each carries `SPDX-License-Identifier: MIT`.
- **`bin/patch-web-ui.js` is AGPL-3.0-only.** It encodes derivative edits to
  paseo's own web-ui bundle, so it carries `SPDX-License-Identifier:
  AGPL-3.0-only` (same basis as `../patches/`). See `../patches/README.md`.

## Layout

| Path | Role | License |
|---|---|---|
| `bin/paseo-browse-host.js` | entry point | MIT |
| `bin/patch-web-ui.js` | paseo web-ui bundle patcher (live panel) | **AGPL-3.0-only** |
| `src/host.js` | WS client: registers the browser host, answers execute requests | MIT |
| `src/executor.js` | Playwright command executor (tabs, refs, redaction) | MIT |
| `src/stream-server.js` | live-view CDP screencast + input transport | MIT |
| `src/security.js` | proportionate URL policy (SSRF guard) | MIT |
| `src/commands.js` | supported-command manifest | MIT |
| `web/browse-view-client.js` | web-ui companion (canvas + toolbar + roster dock) | MIT |
| `test/*` | unit + integration + e2e | MIT |
| `install.sh` / `smoke.sh` | manual install + ship-gate smoke | MIT |

## Tests

`npm test` runs the unit/integration suite (needs a resolvable `playwright`; some
integration tests need network). Two use environment overrides so they carry no
box-specific paths:

- `PASEO_PLAYWRIGHT_PATH` — optional extra path to resolve a `playwright` install.
- `PASEO_BROKER_PATH` — path to the installed `@getpaseo/server` broker.js;
  `test/broker.integration.mjs` **skips** cleanly when it is unset.

`smoke.sh` (the deploy gate) runs `test/smoke.cjs`, asserts the unit is active +
registered with the live daemon, and checks the loopback stream port.
