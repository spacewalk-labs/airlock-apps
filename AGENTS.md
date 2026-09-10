# Repository Contract

## Public boundary

This repository is public: treat every tracked byte, diff, fixture, comment, and historical path as externally visible. Material derived from private sources requires file-by-file review before it enters this tree; never bulk-sync a private tree or publish internal hosts, paths, identifiers, credentials, or operational topology. The privacy scanner and its self-test are mandatory, but they supplement rather than replace that review; see `test/no-internal-names.sh` and the vendored-bundle checks.

## Scope and compatibility

This repository owns public default app packages and their release contracts. Airlock core is excluded and consumes staged local package paths; do not add core code, remote-fetch behavior, or a core/app cross-repository change here.

Treat `apps/<id>/airlock-app.toml`, `abi/`, `foundation.json`, `lock/schema.md`, app READMEs, and tests as their respective sources of truth. A live app manifest remains `contract = 1`, and the current core parser's accepted key set is closed. Keep lifecycle metadata in `abi/apps/<id>.toml`; embedding it in the live manifest or changing the contract requires a coordinated core parser extension.

Adding or renaming an app is incomplete until package artifacts, live inventories, manifest and unit validation, lifecycle ABI, the foundation ABI digest, current references, and in-repository tests agree. Do not treat the historical transfer list in `foundation.json` or `TRANSFER.md` as the live inventory.

## Releases and verification

Mint and rebuild releases only from immutable per-app locks containing `source_sha`, `tree_digest`, and `artifact_digest`. A rollback restores one app from its predecessor lock without consulting mutable labels, working trees, or sibling app state.

Before handoff, run the applicable app-local tests and the complete workflow defined in `.github/workflows/ci.yml`. Privacy and parity coverage are mandatory even when branch protection does not require them; do not silently broaden an omission list or skip a failing suite.
