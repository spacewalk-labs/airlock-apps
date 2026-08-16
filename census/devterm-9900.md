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
copied into this public tree. The immutable dated mapping is the private
company record
[`devterm-9900-bounded-census-20260814.md`](https://github.com/TeamSPWK/swk-infra/blob/8227aca0c7c565e164fc78a19f1585f378cd79db/docs/tasks/active/airlock-universal-platform/01-fleet-census-target.task.logs/devterm-9900-bounded-census-20260814.md),
merged by `TeamSPWK/swk-infra` PR #659. It separates configured selectors,
topology nodes, positively observed automated callers, responding endpoints,
the configured same-origin browser surface, and the explicitly unknown
human/browser-principal count.

That mapping closes only the evidence half of `DT-R1`. It does not choose
keep / migrate / retire; this card waits for the recorded owner decision before
adding the selected route regression fixture.

## Visibility scan of the nine app trees

`bash install/check-internal-leaks.sh` on this checkout: clean.
The one prefix hit inside `apps/devterm/web/panel.html` is the already
public allowlisted identifier `swk-panel-close`.
