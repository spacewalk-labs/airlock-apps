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

- **`claude-model-opus5.mjs`** (+ `claude-model-opus5.patch`, the reference copy)
  — backports the Claude Opus 5 entries into `CLAUDE_MODEL_MANIFEST` and moves the
  default off Opus 4.8. paseo's model list is hardcoded in its dist, so the pinned
  version cannot offer a model released after it — and no daemon restart helps.
  The `.mjs` is the applier `../install.sh` runs: idempotent (sentinel),
  all-or-nothing (both anchors or nothing), fail-closed (`node --check` before it
  replaces the file). A paseo bump that already ships Opus 5 exits 20 and is
  skipped. Only applied when the Claude Code CLI on the daemon PATH is new enough
  to run the model (>= 2.1.219, upstream's stated minimum).

- **`claude-model-prune.mjs`** (+ `claude-model-prune.patch`, the reference copy)
  — removes superseded entries (Opus 4.7/4.6, Sonnet 4.6) from the same manifest
  so the picker is the handful people actually choose. Picker-only: the manifest
  is not on the execution path, so an agent already pinned to a removed model
  keeps running (it just loses the known context-window maximum in the gauge).
  Decomposes the array into entry blocks and refuses to write unless they
  reassemble byte-for-byte, so an upstream format change skips instead of
  mangling the file. Edit `PRUNE_IDS` to change which models are hidden.

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
