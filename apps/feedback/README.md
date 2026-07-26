# feedback

A suggestion box at the bottom of the hub launcher. The user types free text and
submits; a loopback backend attaches the **gate-verified owner** (from the hub
identity header, never a client field) and forwards `{owner, text}` to an
**optional, pluggable** external intake, which records the suggestion (e.g. opens
a GitHub issue) and returns its URL.

- **`/feedback/api/submit`** — the hub page POSTs `{text}` here (same-origin). The
  backend adds `owner` server-side and relays to the intake. The page never calls
  the external intake directly.
- The box only appears when the backend reports it's **configured**
  (`GET /feedback/api/health` -> `enabled: true`). Unconfigured -> no box.

Everything is same-origin under the hub's identity gate; no per-app auth.

## Configuration

```toml
[apps.feedback]
backend_port = 18805
intake_url = "https://your-intake.example"   # you host this (protocol below)
token_env  = "AIRLOCK_FEEDBACK_TOKEN"         # name of the env var holding the token
```

The token is **not** stored in the config. Put it in the env var named by
`token_env`, delivered via an EnvironmentFile the installer already wires:

```
# ~/.config/airlock-feedback.env   (chmod 600)
AIRLOCK_FEEDBACK_TOKEN=…your token…
```

Omit `intake_url`/the token and the box degrades cleanly (it stays hidden;
`submit` reports "not configured").

## Intake protocol (what your target must implement)

JSON over HTTPS. The token is sent in the `X-Airlock-Feedback-Token` header.

| Method + path    | Request body      | Response             |
|------------------|-------------------|----------------------|
| `POST /submit`   | `{owner, text}`   | `{ok, issue_url}`    |

- `owner` is the identity of the submitter (from the hub identity header); your
  endpoint decides how it records the suggestion.
- `issue_url` (optional) is shown to the user as a link to the created item.

A minimal target is a small web service that authenticates the token, creates a
tracking item from `text` (attributed to `owner`), and returns its URL.
