# Release lock schema

Tag is a display label. Lock is the rebuild input. A builder that accepts a
tag as a source ref is out of contract.

## Tag (label only)

```toml
[tags.notepad]
label = "notepad/v1.2.3"
lock = "locks/notepad-deadbeef.lock.json"
```

Moving the tag must not change any existing lock file and must not change
the output of a rebuild that named that lock.

## Lock (immutable)

```json
{
  "abi": "public-app-split/v1",
  "id": "notepad",
  "source_sha": "0123456789abcdef0123456789abcdef01234567",
  "tree_digest": "<64 lowercase hex digest_tree of package source>",
  "artifact_digest": "<64 lowercase hex digest_tree of built artifact>"
}
```

Closed keys. Unknown keys are fatal. Digests are bare lowercase 64-hex —
no `sha256:` prefix (same grammar as `airlock.lock`).

`source_sha` is a resolved commit. Branch names, tags, and abbreviated SHAs
are not valid values.

## Provenance chain

1. Release operator writes a lock after resolving the tag (or branch) once.
2. Rebuild is `build-release.py --repo <git> --source-path apps/<id> --lock <file>`.
3. Builder archives `lock.source_sha:source-path`. A working tree or tag is not consulted.
4. Builder verifies `digest_tree(archived source) == tree_digest`.
5. Builder writes the artifact and verifies `digest_tree(artifact) == artifact_digest`.
6. Airlock core never sees the tag. It is pointed at the artifact directory
   with `[packages.X].path`.

## Rollback

Rollback of app A is a rebuild of A's predecessor lock. There is no
separate rollback object. App B's lock is not an input. A test that
advances A and then rebuilds A's previous lock must restore A's previous
artifact and leave B's artifact unchanged.

Mint and rebuild both extract `source_sha` with `tar --no-same-owner -xp`
so `tree_digest` is a property of the commit, not of the process umask.

