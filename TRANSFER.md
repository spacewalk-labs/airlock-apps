# History-preserving transfer — method and rehearsal

Do not create the GitHub repository from this document. The rehearsal
builds a disposable local repo and deletes it.

## Destination (pending human decision)

| Field | Planned default | Status |
|---|---|---|
| name | `airlock-apps` | uncreated |
| owner | undecided (public org vs company private org) | blocked |
| visibility | undecided (public vs private) | blocked |
| default branch | `main` | assumed |
| protection | undecided | blocked |

## Method

Once the empty destination exists:

```bash
# 1. Export only the nine app histories from the split source revision.
#    HEAD, not --all: other local branches are not part of this transfer.
git fast-export HEAD -- \
  apps/code-server apps/dev-monitor apps/devterm apps/feedback \
  apps/markwand apps/notepad apps/orca apps/paseo apps/publish \
  > /tmp/airlock-apps-apps.fi

# 2. Import into a fresh clone of the empty destination (no squash).
git -C airlock-apps fast-import < /tmp/airlock-apps-apps.fi

# 3. Add the foundation tree at the destination paths in a follow-up commit.
#    history/public-apps/test/          -> test/
#    history/public-apps/foundation.json -> docs/releases/foundation.json
#    history/public-apps/abi/            -> docs/abi/
#    history/public-apps/lock/           -> releases/
#    history/public-apps/builder/        -> releases/builder/

# 4. Verify before the first push:
#    - each apps/<id>/airlock-app.toml blob matches airlock-work HEAD
#    - dest commit count for those paths is not 1 unless source was 1
#    - bash test/foundation-boundary.sh
#    - bash test/app-release-isolation.sh
```

`git filter-repo --path apps/<id>` is an equivalent tool. The rehearsal
uses `fast-export` because it is built into git.

## After the destination exists — do not delete this tree

`history/` on airlock-work allows `A` and `M` only. A delete of
`history/public-apps/` is cutline-red. Once the destination has the
files, replace this directory with a single tombstone file (that is an
`M`, not a `D`) pointing at the new repository. Do not `git rm` the
prefix.

## What is not transferred

- Airlock core (`bin/`, `install/`, `hub/`, `gate/`, …)
- Company apps, fleet catalog, trust-gate files
- Cutline policy (`docs/airlock/sot-cutline.yaml` and friends)

## Verification the rehearsal already runs

`rehearsal/transfer-dry-run.sh` does steps 1–2 into `$TMP`, checks the
nine manifests byte-identical to this checkout, then deletes `$TMP`.
It never talks to GitHub.
