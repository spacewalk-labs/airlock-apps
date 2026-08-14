# Bounded census — configured `http:9900` (devterm)

This is the configured-consumer half of todo ⑧. It does **not** decide
keep / migrate / retire.

## Configured in this tree

| Source | What it says |
|---|---|
| `apps/devterm/airlock-app.toml` `[config.defaults] public_port` | `9900` |
| same file `[plaintext_redirect]` | `public_port -> redirect_port` |
| `apps/devterm/README.md` | plaintext port 301s to HTTPS |

No other shipped app declares `public_port = 9900`. A colour literal
`#990000` in `apps/devterm/web/app.js` is not a listener.

## Live boxes

Live unit/port observations are company-ops evidence and are **not**
copied into this public tree. The dated write-up is the company
`2026-08-11_devterm-airlock-cutover` task. This file only records that
such a write-up exists and that this card will not ask for
keep/migrate/retire until that live evidence is attached to the
decision document the person actually reads.

## Visibility scan of the nine app trees

`bash install/check-internal-leaks.sh` on this checkout: clean.
The one prefix hit inside `apps/devterm/web/panel.html` is the already
public allowlisted identifier `swk-panel-close`.
