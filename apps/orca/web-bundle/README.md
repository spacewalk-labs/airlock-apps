# orca web-bundle — the patched Orca web client (vendored)

`dist/` is the **built** Orca web client that Airlock serves at `/orca-web/` behind
the owner gate, in place of the raw client that `orca serve` ships. `apps/orca/install.sh`
copies it to a world-readable serve path and 302-redirects the vendor client URL to it.

## Why vendor a build (not the source)

The client is a static, self-contained build (`web-index.html` + hashed `assets/`).
Serving it needs no toolchain, so only the **built dist** is vendored here — not the
upstream source and not the build tooling. The dist is a derivative of the upstream
Orca web client (MIT) plus local patches (also MIT); see repo-root `NOTICE`.

## What the patches change (all baked into `dist/`)

- **PTY-reload fix** — upstream bug: after a full page reload the terminal panes die
  with *"Local PTYs are unavailable in the web client"* forever. The fix maps the
  paired web client's "local" host to the active runtime so terminals survive reload.
- **Runtime-rebind** — a *"Reconnecting…"* overlay + automatic re-attach when the
  runtime restarts, instead of a dead terminal.
- **Local browser render** and **grab** (element-comment) — present in the bundle but
  **inert unless extra sidecars are installed** (a slot manager / a grab bridge, which
  Airlock does not deploy in v1). With those absent, the client falls back to the
  upstream behavior (streaming render; no grab). See "Not wired in v1" below.

## Integrity: VERSION + verify-web-bundle.sh

`VERSION` pins what this build *is*: the clean maintainer-source commit, upstream AppImage
version, entry asset name, file count and a sha256 over the whole tree. A build carries no
version string inside it, so without those fields neither "is this stale?" nor "did this
get corrupted in transit?" can be answered.

`../bin/verify-web-bundle.sh` checks `dist/` against the pin, and `../install.sh` runs it
before serving. This matters because of *how* a broken bundle fails: a partial clone or a
truncated copy still serves 200s and then renders a blank page, so nothing looks wrong.
Verifying up front turns that into a failed install.

It does **not** rebuild. `../bin/refresh-web-bundle.sh` consumes a clean, separately
maintained source checkout's built `dist/`, applies `public-scrub.json`, regenerates every
pin, runs this verifier, then atomically swaps the public bundle. Missing/non-executable
verification and any incomplete refresh fail closed.

## Provenance / PII

The upstream client is MIT, © 2026 Lovecast Inc. (`github.com/stablyai/orca`). The
vendored dist was **PII-scrubbed**: our patches' Korean UI strings were translated to
English and an internal namespace/token + internal script names were removed. What
remains in the dist is upstream's own content only — its i18n locale bundles (incl.
the Korean `ko-*.js` locale and the native-script language names in the language
picker), a CJK text-measurement sample, and library data — none of which is
Airlock/operator PII.

## Refreshing the bundle

The dist here is a static snapshot. Build the separately maintained source checkout, make
sure it is clean, then run:

```bash
apps/orca/bin/refresh-web-bundle.sh \
  --source /path/to/orca-web --appimage-version 1.4.139
```

The command refuses a dirty/non-git source, symlinked or incomplete dist, incomplete HTML
body, ambiguous/missing hashed entry asset, residual scrub source, denied internal/PII
terms, or mismatched pins. It keeps the prior public bundle intact on every failure.

## Not wired in v1

Local browser render (slot manager + external proxy pool) and grab (a page-injected
bridge) need extra services this repo does not install. The client degrades gracefully
without them. Wiring them is a documented follow-up, not part of v1.
