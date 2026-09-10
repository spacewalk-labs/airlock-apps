# History-preserving transfer — completed record

The destination repository already exists. This document preserves the original
transfer method and its nine-app evidence; it is not a creation or live-inventory
playbook. The current app set is owned by `test/lib.sh`.

## Destination

| Field | Value | Status |
|---|---|---|
| name | `airlock-apps` | created |
| owner | `spacewalk-labs` | settled |
| visibility | public | settled |
| default branch | `main` | active |
| protection | required status checks selected at creation | external live state |

## Method

The empty destination was seeded with this method:

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
#    history/public-apps/foundation.json -> foundation.json
#    history/public-apps/abi/            -> abi/
#    history/public-apps/lock/           -> lock/
#    history/public-apps/builder/        -> builder/

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

The source repository's `rehearsal/transfer-dry-run.sh` performed steps 1–2
inside `$TMP`, checked the nine manifests byte-identical to the transfer source,
and then deleted `$TMP`. It did not talk to GitHub.
