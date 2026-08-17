# Bounded census — configured `http:9900` (devterm)

This records the pre-retirement evidence and the selected transition order for
todo ⑧. The current package is HTTPS-only; the rows below describe the historical
configured surface at the fixed census point. Decision (2026-08-17, board
`0ff93d05`): **retire** after the four known consumers move; uncounted callers
are accepted. Live close is not this file.

## Configured at the fixed census point

| Source | What it says |
|---|---|
| historical `apps/devterm/airlock-app.toml` `[config.defaults] public_port` | `9900` |
| historical `[plaintext_redirect]` | `public_port -> redirect_port` |
| selected package state | no plaintext config, renderer, smoke assertion, or lifecycle claim |

At that point no other shipped app declared `public_port = 9900`. A colour literal
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

The owner decision recorded in taskboard opinion `0ff93d05` is `retire` and
accepts the risk of uncounted callers. Closure must still follow this order:

1. migrate the four confirmed consumers: central fleet collector, non-central
   gate central-store reader, legacy dev-monitor IP fallback, and legacy hub IP
   fallback;
2. deploy the HTTPS-only package state and close plaintext `:9900`.

This repository fixes the second step's desired state and regression. It does
not claim that the four external consumers have already migrated or that live
`:9900` has already closed.

## Visibility scan of the nine app trees

`bash install/check-internal-leaks.sh` on this checkout: clean.
The one prefix hit inside `apps/devterm/web/panel.html` is the already
public allowlisted identifier `swk-panel-close`.
