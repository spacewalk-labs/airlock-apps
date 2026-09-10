# Public app split decisions

Status: settled. This is a record, not an open questionnaire.

| Decision | Outcome |
|---|---|
| `D-REPO-NAME` | `airlock-apps` |
| `D-REPO-VISIBILITY` | Public repository in `spacewalk-labs` |
| `D-REPO-PROTECTION` | Required status checks were selected for repository creation; `.github/workflows/ci.yml` is the source of truth for the checks themselves. |
| `D-DEVTERM-9900` | Retire the plaintext endpoint after its known consumers migrate; the package desired state is HTTPS-only. |

`foundation.json` is the machine-readable transfer pin. The fixed census and the boundary between package state and live deployment are documented in [`census/devterm-9900.md`](census/devterm-9900.md).
