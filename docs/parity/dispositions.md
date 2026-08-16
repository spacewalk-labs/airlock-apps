# Public app parity disposition register

Status: 31 executable clusters decided; 11 clusters deliberately held

This register is the disposition layer over the conservative 42-cluster sample in
[`../../census/parity-decision-triage.md`](../../census/parity-decision-triage.md).
It is not a disposition of all 134 rows in
[`../../census/parity-matrix.md`](../../census/parity-matrix.md).

The evidence pair remains fixed at:

- public: `893c4da58f9aecb3d25fd085bbbfd57aeb4518d2`
- internal: `3ced9d54ceb03b118b2961bf3938252f5f397431`

## Terms and decision rule

- **keep** — retain the current public behavior as the destination contract. A
  compatibility reader may consume legacy state, but canonical writes and privilege
  boundaries do not move to the internal form.
- **migrate** — bring an internal behavior into the public destination, normally as
  compatibility or an explicitly bounded capability, while retaining the named public
  invariant.
- **retire** — intentionally do not carry the behavior forward. This is the task
  document's term for `drop`.
- **hold** — do not choose or implement a disposition until the named evidence or
  promotion prerequisite arrives.

For reversible choices, prefer the behavior that preserves a user capability or makes
failure safer. Do not copy host-specific activation, personal presentation defaults, or
privileged machinery when the public contract already represents the needed outcome
with a narrower boundary.

## A — coexistence decisions

These eighteen rows need no person decision and can proceed now.

| Cluster | Matrix IDs | Disposition | Destination contract |
|---|---|---|---|
| devterm terminal font | DT-C4 | migrate | Add D2Coding as an available bundled font and retain the platform monospace stack as the default/fallback. Font license and NOTICE become release inputs. |
| devterm account switcher activation | DT-U2 | keep | Keep explicit `accounts=false/true`; it already represents both disabled and always-enabled deployments without a hostname policy. |
| dev-monitor service restart surface | DM-R2, DM-U2 | migrate | Carry the allow-listed user-service restart API/UI and log targets into a separately authenticated mutation path; system services remain rejected. |
| dev-monitor spool firewall | DM-N3 | keep | Keep the public operator-owned `0700` spool boundary and do not carry the internal low-trust spool UID or its root-owned firewall unit into an app with `capabilities = []`. |
| dev-monitor executable-skill allow-list | DM-C2 | migrate | Add an optional membership allow-list; unset keeps the current syntax validation and set adds membership validation. |
| dev-monitor message-console activation | DM-C3 | keep | Keep the explicit `messages` setting and retire the `hostname == josh-dev` activation rule. |
| Markwand PWA installation metadata | MW-U1 | migrate | Add app-scoped Markwand manifest metadata without copying the internal `SWK Dev Hub` identity or root `/` scope. |
| Markwand top-level home aliases | MW-S1 | migrate | Add an explicit, default-empty alias allow-list under the configured code root; reconcile only links owned by that list. |
| Notepad attachment-token syntax | NP-U1 | migrate | Accept both English and Korean token vocabularies; keep English generation canonical and preserve each recognized vocabulary's copy expansion. |
| Notepad draft persistence | NP-S1 | keep | Keep editor-text draft persistence; attachment maps and uploaded paths remain session-only. |
| Orca web-bundle provenance | OR-C3 | migrate | Add a maintainer-only source refresh stage, but continue serving only the committed bundle whose entry, file count, and tree hash pass public verification. Do not migrate stale-bundle fallback. |
| Paseo browse-sidecar activation | PA-R1, PA-C1 | keep | Keep `browse=false/true` as the sole activation contract; route, Chromium, live panels, and tool injection appear only when enabled. |
| Paseo return-widget menu | PA-U1 | keep | Keep menu-on-panel and direct-home fallback when no panel URL resolves. |
| Paseo ambient OpenAI key | PA-C3 | migrate | Strip ambient `OPENAI_API_KEY` at both the unit and Codex-spawn boundaries while preserving an explicitly configured runtime key. |
| Publish management/share paths | PB-R1 | migrate | Keep `/publish/` and `/publish/files/` canonical and add a same-origin `/publish-manager.html` compatibility alias. Do not claim or recreate the separate `:8000` listener in this app. |
| Publish local/remote gated mode | PB-R2, PB-A2, PB-U6, PB-C2 | migrate | Keep explicit `public_target=local|remote`, `entry` canonical with `name` fallback, and add remote v1 gated/bundle capability negotiation. |
| Publish remote protocol compatibility | PB-A3 | migrate | Negotiate v0/v1 and the matching single token header, then validate results and revoke mismatched creations. |
| Publish bundle attachments and limits | PB-A5 | migrate | Preserve HTML-only bundles and add bounded attachment-bearing bundles with explicit member and total limits. External-symlink provenance remains conservative until PB-A4 is measured. |

## B — reversible decisions

All thirteen rows can proceed now. Each choice changes only a release, configuration
default, future write, or UI policy and has no irreversible data rewrite in the initial
step.

| Cluster | Matrix IDs | Disposition | Destination contract and rollback boundary |
|---|---|---|---|
| devterm detached login survival | DT-N1 | keep | Keep `KillMode=process`; a later unit release can change it, while the current choice avoids interrupting detached device login. |
| devterm locale default | DT-C2 | keep | Keep portable `C.UTF-8` as the default and retain the existing locale override. |
| code-server fresh-install preferences | CS-C4 | retire | Do not seed theme, zoom, trust, or extensions from a host-specific profile. Existing user data remains untouched; a future explicit profile can add deterministic pins. |
| Markwand dependency acquisition | MW-C1 | keep | Keep pinned versions and archive verification; updates remain explicit artifact releases. |
| Markwand branding color | MW-C3 | retire | Do not copy the fixed internal teal into destination state. Preserve an existing DB choice and keep package-owned name/files migration only. |
| Notepad image encoding defaults | NP-U2 | keep | Keep the current 2400-pixel/0.9 future-upload default rather than lowering fidelity without measurement; a later client release can tune it. |
| Notepad clear-time sequence reset | NP-U4 | keep | Keep resetting the page-local attachment counter when the page is cleared. |
| Publish unresolved-asset handling | PB-A6 | migrate | Adopt context-aware local-asset validation and fail publication when local assets remain unresolved; rollback is a later bundler policy release. |
| Publish remote-list conflict handling | PB-A7 | migrate | Abort on list failure or multiple entries for one source and report the conflicting slugs; rollback is a later client policy release. |
| Publish direct-file delete confirmation | PB-U4 | keep | Keep matching-filename re-entry for permanent direct-file deletion. |
| Publish unknown external status | PB-U5 | keep | Keep publish/revoke unavailable while external state is unknown instead of acting on an empty or stale map. |
| Publish upload filename normalization | PB-S2 | migrate | Preserve safe Unicode, including Hangul, for future uploads with explicit normalization and length bounds; do not rename stored files. |
| Publish clipboard-image namespace | PB-S3 | keep | Keep `imageNNN` for new writes and extend sequence recognition to existing `이미지NNN` names during migration. Existing files are not renamed. |

## Held evidence and promotion work

The held set is 11 clusters in this bounded sample: eight C and three D.
No code or regression fixture for these rows is authorized by this register.

| Bucket | Cluster | Matrix IDs | Disposition | Waiting for | Producer or decision owner |
|---|---|---|---|---|---|
| C | devterm fleet usage visibility | DT-A1 | hold | Strict accepted caller/access measurement for the four status endpoints. | `FLEET_CENSUS_TARGET`. |
| C | Markwand split route | MW-R2 | hold | Five-box route request/access measurement for `/markwand/split`. | `FLEET_CENSUS_TARGET`. |
| C | Markwand hidden credential-directory aliases | MW-S2 | hold | Installed-link and access/use measurement for the `.claude` and `.codex` aliases. | `FLEET_CENSUS_TARGET`. |
| C | Paseo descendant privilege | PA-N3 | hold | Box/session evidence of spawned-agent setuid `sudo` dependence. | `FLEET_CENSUS_TARGET`. |
| C | Paseo memory limits | PA-N5 | hold | Box memory plus observed Paseo working-set and pressure measurement. | `FLEET_CENSUS_TARGET`. |
| C | Paseo task limit | PA-N6 | hold | Current and peak task-count measurement on the five boxes. | `FLEET_CENSUS_TARGET`. |
| C | Paseo accepted hostnames | PA-C2 | hold | Gate/access evidence for tailnet-suffix hostname use. | `FLEET_CENSUS_TARGET`. |
| C | Publish source provenance | PB-A4 | hold | Bounded scan of current publication sources and their symlink/provenance dependence. | `FLEET_CENSUS_TARGET`. |
| D | devterm plain-HTTP behavior | DT-R1 | hold | The dated live `:9900` mapping attached to the decision surface, followed by the already-scoped keep/migrate/retire decision. Only then can this card add the selected route fixture. | `FLEET_CENSUS_TARGET` supplies live evidence; the person owns the disposition; `PUBLIC_APP_PARITY` only consumes it. |
| D | Orca rooted-artifact deactivation | OR-C4 | hold | Orca capability promotion with immutable upstream evidence across the TRUST boundary. | The upstream evidence producer/promotion owner is currently unassigned; `TRUST_CAPABILITY_GATE` is the consumer. |
| D | Orca rooted paths and serve tree | OR-S4 | hold | Orca capability promotion with immutable upstream evidence across the TRUST boundary. | The upstream evidence producer/promotion owner is currently unassigned; `TRUST_CAPABILITY_GATE` is the consumer. |

The Orca owner check above is bounded to the campaign board and active task documents
on `swk-infra` `origin/main`, plus this repository's ABI files. The same `git grep`
sample positively finds Orca as the `system-unit`/`rooted-artifact` promotion target;
the board activity records that the remaining producer closed and no replacement owner
was assigned. This is a campaign-doc sample, not a company-wide absence claim.

## Accounting boundary

The positive control is the triage register itself: 42 table rows covering 47 matrix
IDs, partitioned as A 18, B 13, C 8, D 3. This register assigns all 18 A plus all 13 B
rows and holds 8 C plus 3 D rows. Therefore its bounded accounting is 31 decided plus
11 held, not a claim that the full 134-row parity matrix has zero undecided deltas.
