# Core / app manifest ABI — public-app-split/v1

## Compatibility range

| Layer | Accepts | Rejects |
|---|---|---|
| Airlock core today | `airlock-app.toml` `contract = 1` | any other `contract`, unknown keys (F10) |
| airlock-apps release gate | contract 1 **plus** a complete `[lifecycle]` declaration (this ABI) | missing lifecycle, unknown lifecycle keys, tag used as a lock |
| Future core extension | additive `[lifecycle]` table on contract 1 | a silent contract 2 bump that breaks existing boxes |

Core `contract = 1` packages remain installable. Lifecycle is required by
the **release** gate, not by `airlock-config` validate, until a coordinated
additive extension lands. Putting `[lifecycle]` into live manifests today
would be fatal (F10) and would collide with the trust-surface parser.

Compatibility id: `public-app-split/v1`.
Core contract window: `[1]`.
Next compatible core change: add closed table `[lifecycle]` to
`_MANIFEST_KEYS` without changing `contract`.

## Core consumption (unchanged)

- Packages are local paths. `[packages.X]` accepts `path` (and ABI 2 `grant`) only.
- `source = "git+…"` stays fatal.
- Airlock does not fetch remotes, resolve tags, or read a catalog.
- Shipped apps resolve as `$ROOT/apps/<id>` until the physical split.

## App package ABI additions

Every public app declares a `[lifecycle]` table. Stateless apps must say
`none` on every field — omission is red.

```toml
[lifecycle]
quiesce = "none"          # or a named procedure
snapshot = "none"
forward = "none"          # forward migrate
write_capture = "none"    # post-cutover write capture
reverse = "none"          # reverse / compatibility
rpo = "none"              # "none" if stateless, else "0"
paths = []                # retained data paths; empty iff stateless
capabilities = []         # elevated/restricted names; declaration only
```

`capabilities` marks promotion *targets*. It does not promote. `orca`
declares `rooted-artifact` and `system-unit`. The rest declare an empty
list. The capability vocabulary no longer includes `plaintext-redirect`.

Campaign cutover requires RPO=0 for stateful apps. A declared but
unimplemented migrator is still a complete ABI row; implementation belongs
to `PUBLIC_APP_PARITY`.

Closed field set: `quiesce`, `snapshot`, `forward`, `write_capture`,
`reverse`, `rpo`, `paths`. Unknown keys are fatal.

## Lock provenance

A human-facing **tag** is a label. A **lock** is the only rebuild input:

- `source_sha` — resolved immutable commit SHA (40 lowercase hex)
- `tree_digest` — `digest_tree` of the package source (64 lowercase hex)
- `artifact_digest` — `digest_tree` of the built artifact (64 lowercase hex)

Rebuild materializes `source_sha` from a git repo (`--repo --source-path`).
A working tree or tag is not a rebuild input. After a tag retarget, rebuilding
the old lock must be byte-identical. See `lock/schema.md`.
