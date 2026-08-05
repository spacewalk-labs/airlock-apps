# paseo patches — AGPL-3.0-only

**License: `AGPL-3.0-only`** (not the repo's MIT).

Paseo (`@getpaseo/cli`, upstream https://github.com/getpaseo/paseo) is licensed
**AGPL-3.0**. The files in this directory modify Paseo's own bundle, so they are
**derivative works of Paseo** and are licensed **AGPL-3.0-only**, independent of
the MIT license that covers the rest of Airlock.

## What is here

- **`depth4-search.patch`** — caps the add-project name search to `maxDepth: 4`
  (paseo's default full-scans `$HOME` and times out on a large home). This is the
  reference / re-derivation copy of the edit; `../install.sh` applies it via an
  idempotent `sed` against the installed bundle.

- **`image-attachments-persist.mjs`** (+ `image-attachments-persist.patch`, the
  reference copy) — an image pasted into paseo's web UI reaches the model only as an
  inline base64 vision block: the model sees it, but no file exists, so the agent's
  `Read` tool has no path and "look at this screenshot, then edit the file" dead-ends.
  The patch keeps the inline block and *also* writes the bytes under the session cwd
  (`<cwd>/.paseo-attachments/`, self-ignored via its own `.gitignore`, name
  content-addressed so a re-paste dedups), then appends a sibling text block naming the
  absolute path. Same discipline as the others: sentinel (idempotent), all-or-nothing
  (three anchors or none), `node --check` before it replaces the file, exit 20 on
  upstream drift so the install continues without the feature.

- **`claude-model-prune.mjs`** (+ `claude-model-prune.patch`, the reference copy)
  — removes superseded entries (Opus 4.7/4.6, Sonnet 4.6) from paseo's
  `CLAUDE_MODEL_MANIFEST` so the picker is the handful people actually choose. Picker-only: the manifest
  is not on the execution path, so an agent already pinned to a removed model
  keeps running (it just loses the known context-window maximum in the gauge).
  Decomposes the array into entry blocks and refuses to write unless they
  reassemble byte-for-byte, so an upstream format change skips instead of
  mangling the file. Edit `PRUNE_IDS` to change which models are hidden.

- **`orphan-process-guard.mjs`** (+ `orphan-process-guard-{claude,codex}.patch`, the
  reference copies, and `orphan-process-guard.test.mjs`, a behaviour check) — paseo
  leaks the agent processes it spawns. Both providers track exactly one live child
  (`this.childProcess` / `this.client`) and terminate it behind an `if (handle)` with
  no else branch, and neither honours the closed flag on its spawn entry point
  (`ensureQuery()` / `connect()`). A control-plane call landing during or after close —
  `setMode`, `setModel`, `listCommands`, `revertFiles`, a codex reconnect, or the
  in-flight spawn simply finishing late — starts a **replacement** process on a session
  nothing will ever close again; it runs until the box is rebooted. close() reports
  success because at that instant there was genuinely nothing to kill, and the
  surrounding `session_close.start/complete` lines are `logger.trace`, which the
  daemon's info-level logger never emits — so the whole class of leak was unobservable.
  Measured on josh-dev 2026-08-05: 18 orphans, 2.9G RSS + 1.9G swap.
  The patch makes ownership a `Set` (a replaced handle is still terminated), gates both
  spawn entry points, terminates a late arrival on the spot instead of storing it, and
  `logger.warn`s every branch that used to be silent. Two independent targets, one
  invocation each (`claude` / `codex`) so a drift in one does not disable the other;
  anchors must be present **and unique** or it exits 20. Deliberately out of scope:
  `detached: true` + process-group kill, which would also cover MCP children orphaned
  when the leader exits first — that changes the signal/session semantics of the
  provider spawn and needs its own change and observation window; this patch logs that
  case loudly instead. Verify after install:
  `node orphan-process-guard.test.mjs <installed>/providers/claude/agent.js`.

The browse-host sidecar carries one more AGPL derivative outside this directory:
**`../browse-host/bin/patch-web-ui.js`** (`SPDX-License-Identifier:
AGPL-3.0-only`), which encodes minimal edits to paseo's web-ui bundle for live
panels. Everything else under `../browse-host/` is an independent MIT sidecar.

## Why the rest of Airlock can stay MIT

Airlock runs Paseo as a **separate process** and communicates with it over
IPC/WebSocket. The Airlock core and the `apps/paseo/` installer + `browse-host/`
sidecar (our own code) do not incorporate Paseo's source, so they are *mere
aggregation* and remain MIT. Only the modifications **to Paseo itself** (here) are
AGPL-3.0.

> This is not legal advice. Confirm against the AGPL-3.0 terms — and consider
> asking the Paseo maintainers for explicit interop guidance — before publishing.

## AGPL §13 (network use)

If you offer a modified Paseo to users over a network, AGPL-3.0 requires you to
offer them the corresponding source. Operators of an Airlock deployment that
exposes Paseo are responsible for this.

## TODO before public release

- [ ] Vendor the full AGPL-3.0 license text into this directory (`LICENSE`).
- [ ] Audit each patch/anchor to confirm only minimal, interoperability-necessary
      excerpts of Paseo source are reproduced (prefer install-time anchor derivation
      over shipping verbatim upstream lines where feasible).
