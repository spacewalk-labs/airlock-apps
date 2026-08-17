# Public app parity disposition register

Status: 106 executable clusters decided; 2 clusters deliberately held

This register is the disposition layer over the exhaustive 108-cluster triage in
[`../../census/parity-decision-triage.md`](../../census/parity-decision-triage.md).
It assigns every one of the 134 rows in
[`../../census/parity-matrix.md`](../../census/parity-matrix.md) exactly once.

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
| dev-monitor service restart surface | DM-R2, DM-U2 | migrate | Carry the allow-listed user-service restart API/UI into a separately authenticated mutation path; system services remain rejected. Keep the public discovered-user-service log selector instead of copying the internal fixed list. |
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

## C — measured decisions

The private raw records remain in `TeamSPWK/swk-infra`; the public sanitized
fixture is [`../../census/parity-c-measurement-20260817.json`](../../census/parity-c-measurement-20260817.json).
Its exact evidence commit and L2 REFUTE certificate are executable inputs to the
disposition validator. Missing caller/Host fields remain `unknown`, never zero.

| Cluster | Matrix IDs | Disposition | Destination contract |
|---|---|---|---|
| devterm fleet usage visibility | DT-A1 | keep | Keep the four status endpoints owner-only. The retained request source had positive traffic controls but no caller-principal field, so there is no evidence to widen the audience. |
| Markwand split route | MW-R2 | migrate | Add an exact `/markwand/split` compatibility route to the canonical split viewer; `/markwand/` remains canonical. The exact legacy route had 20 retained requests. |
| Markwand hidden credential-directory aliases | MW-S2 | migrate | Add explicit opt-in, package-owned `claude -> ~/.claude` and `codex -> ~/.codex` aliases. Default remains off; the measurement found links on 5/5 and 4/5 boxes and 39 direct alias requests. |
| Paseo descendant privilege | PA-N3 | migrate | Add an explicit descendant-sudo capability that renders `NoNewPrivileges=no` for this unit only. Default remains hardened; the positive failure/recovery record proves spawned-agent setuid dependence. |
| Paseo memory limits | PA-N5 | keep | Keep box-derived `MemoryHigh`/`MemoryMax` for finite cgroup caps. An unbounded container must supply an explicit cap instead of inheriting shared-host `MemTotal`. |
| Paseo task limit | PA-N6 | keep | Keep `TasksMax=infinity` as delegation to the enclosing user slice rather than pinning a box-specific finite guess. Current/peak/event measurements remain covered by the outer cap. |
| Paseo accepted hostnames | PA-C2 | keep | Keep exact FQDN, exact FQDN with HTTPS port, and localhost. Incoming Host was not logged, so this is a conservative no-widening choice rather than a zero-use claim. |
| Publish source provenance | PB-A4 | keep | Preserve top-level external-symlink HTML publication compatibility; 13 active publications depend on it. Keep attachment symlink provenance rejected and the existing lexical path boundary intact. |

## D — owner decisions

| Cluster | Matrix IDs | Disposition | Destination contract |
|---|---|---|---|
| devterm plain-HTTP behavior | DT-R1 | retire | Remove `public_port`, `redirect_port`, `[plaintext_redirect]`, the loopback redirect renderer, and the `plaintext-redirect` lifecycle claim from the package. Deployment is ordered: migrate the four confirmed consumers first, then apply this HTTPS-only desired state and close `:9900`; uncounted callers are an accepted decision risk. |

## E — fixed-SHA exhaustive closure

These 66 evidence-complete clusters were outside the original conservative A-D
candidate set. All can proceed without census, privilege promotion, or a person choice.

| Cluster | Matrix IDs | Disposition | Destination contract |
|---|---|---|---|
| devterm keytest diagnostic | DT-R2 | migrate | Add the app-scoped input diagnostic under the existing owner gate. |
| devterm wrong-method contract | DT-A2 | migrate | Return explicit JSON 405 responses for wrong secret methods. |
| devterm install restart discipline | DT-N2 | keep | Restart only on content change or inactivity. |
| devterm unit identity | DT-N3 | keep | Keep canonical `airlock-devterm*` units. |
| devterm platform configuration and identity | DT-C1, DT-C3 | keep | Keep app-scoped settings and the platform-configured identity header. |
| devterm usage cache persistence | DT-S1 | keep | Keep the identity-checked persistent Codex usage cache. |
| devterm legacy tab-state path | DT-S2 | migrate | Read or copy legacy tab state non-destructively; write only the public path. |
| dev-monitor token freshness surface | DM-R1, DM-A2, DM-U3, DM-N1, DM-C1, DM-S2 | keep | Keep the opt-in API, health, UI, units, config, and snapshot as one capability. |
| dev-monitor run retention | DM-A1, DM-U4, DM-S3 | keep | Keep the completed-run window and 24-hour reclamation state. |
| dev-monitor bulk message actions | DM-U1 | migrate | Add visible-card bulk actions with progress, partial failure, and undo. |
| dev-monitor unit identity | DM-N2 | keep | Keep `airlock-dev-monitor.service` canonical. |
| dev-monitor observability history | DM-S1 | keep | Keep history in durable app state rather than `/tmp`. |
| dev-monitor delivery leases | DM-S4 | keep | Keep lane-aware claim leases and startup recovery. |
| dev-monitor legacy message-state path | DM-S5 | migrate | Import legacy DB/spool state non-destructively; write only the public path. |
| code-server configurable slots | CS-A1, CS-U1, CS-C1 | keep | Keep configurable slot counts, ports, validation, and UI topology. |
| code-server unit identity | CS-N1 | keep | Keep canonical `airlock-code-server*` units. |
| code-server unit ordering | CS-N2 | keep | Keep `network.target` ordering. |
| code-server install restart discipline | CS-N3 | keep | Restart only changed or inactive services. |
| code-server identity configuration | CS-C2 | keep | Keep the configured identity header and fail-closed owner check. |
| code-server architecture support | CS-C3 | keep | Keep verified amd64 and arm64 artifacts. |
| code-server legacy state | CS-S1, CS-S2 | migrate | Copy legacy slots/extensions/tabs and single-instance state without deleting it; write canonical Airlock paths. |
| feedback owned surface | FB-R1, FB-A1, FB-A2, FB-A3, FB-N1, FB-C1, FB-C2 | keep | Keep the same-origin route, validated API, identity-derived submitter, delivery modes, user unit, and env-reference secret boundary. |
| Markwand legacy edit route | MW-R1 | migrate | Redirect legacy `/edit...` paths to canonical `/markwand/edit...`. |
| Markwand long editor timeout | MW-R3 | keep | Keep the 86400-second editor proxy read timeout. |
| Markwand return widget | MW-U2 | keep | Keep the Airlock return widget on direct file pages. |
| Markwand unit identity | MW-N1 | keep | Keep canonical `airlock-markserv` and `airlock-filebrowser` units. |
| Markwand linger observation | MW-N2 | migrate | Warn on missing linger; do not enable it from the app. |
| Markwand Node PATH | MW-N3 | keep | Keep the discovered Node path in the unit environment. |
| Markwand code-root requirement | MW-C2 | keep | Require an explicit absolute code root. |
| Markwand database backup | MW-S3 | migrate | Take an atomic bounded backup before DB settings changes. |
| Notepad canonical route | NP-R1 | migrate | Redirect `/notepad.html` to canonical `/notepad/`. |
| Notepad upload encoding | NP-A1 | keep | Keep prefix-free base64 writes and backend Data URL compatibility. |
| Notepad upload-size preflight | NP-U3 | keep | Keep the 12 MiB encoded-image preflight. |
| Notepad independent package lifecycle | NP-N1, NP-C1 | keep | Keep Notepad unitless, Publish-dependent, and independently deactivatable. |
| Orca unit identity | OR-N1 | keep | Keep canonical `airlock-orca*` identities. |
| Orca unit ordering | OR-N2 | keep | Keep `network.target` ordering. |
| Orca partial-deploy restart | OR-N3, OR-S2 | migrate | Separate Xvfb/Orca change flags and use drift evidence for targeted recovery. |
| Orca linger observation | OR-N4 | migrate | Warn on missing linger; do not enable it from the app. |
| Orca manifest boundary | OR-C1 | keep | Keep manifest ports and platform owner audience. |
| Orca dry-run renderer | OR-C2 | keep | Keep mutation-free dry-run and redirected rendering. |
| Orca app-state namespace | OR-S1 | keep | Keep state and helpers in the Airlock namespace. |
| Orca orphan-scope reconciliation | OR-S3 | migrate | Preserve live serve scopes and remove only proven orphans. |
| Paseo stream proxy policy | PA-R2 | migrate | Add 86400-second send timeout and disable response buffering. |
| Paseo unit identity | PA-N1 | keep | Keep canonical `airlock-paseo*` identities. |
| Paseo stale pidfile guard | PA-N2 | keep | Keep the evidence-gated stale/PID-reuse guard. |
| Paseo shutdown timeout | PA-N4 | migrate | Add `TimeoutStopSec=20`. |
| Paseo linger observation | PA-N7 | migrate | Warn on missing linger; do not enable it from the app. |
| Paseo future provider PATH | PA-N8 | keep | Keep future provider directories in unit PATH. |
| Paseo unit ordering | PA-N9 | keep | Keep `network.target` ordering. |
| Paseo app favicon branding | PA-C4 | keep | Keep app-scoped icon-ring favicon generation. |
| Paseo manifest and sidecar ports | PA-C5, PA-C6 | keep | Keep explicit manifest settings, platform owner, and resolved sidecar ports. |
| Paseo architecture restriction | PA-C7 | retire | Do not carry the host-specific x86-only rejection into the destination. |
| Paseo spawned-process ownership | PA-S1 | keep | Keep handle ownership and orphan process-group cleanup. |
| Paseo credential metadata preservation | PA-S2 | keep | Keep merge-write refresh that preserves unknown fields. |
| Paseo partial-deploy restart | PA-S3 | migrate | Treat `NeedDaemonReload=yes` as recovery-restart evidence. |
| Publish public contract metadata | PB-A1 | migrate | Add versioned `public_contract` fields without removing existing fields. |
| Publish broken-item contract | PB-A8, PB-U8 | keep | Keep `isBroken` in the API and the functioning repair action. |
| Publish direct upload | PB-U1 | keep | Keep bounded 50 MiB file upload. |
| Publish theme preference | PB-U2 | migrate | Add system/light/dark using a Publish-specific storage key. |
| Publish item-type filters | PB-U3 | keep | Keep HTML, image, folder, and file filters. |
| Publish bundle confirmation | PB-U7 | migrate | Show attachment names/count/size and document sources over PB-A5. |
| Publish periodic refresh | PB-U9 | migrate | Add visibility-aware 30-second refresh guarded against stale responses. |
| Publish unit identity | PB-N1 | keep | Keep canonical `airlock-publish*` identities. |
| Publish cleanup scope | PB-N2 | keep | Keep upload cleanup plus local-publication expiry/reconciliation. |
| Publish share-root configuration | PB-C1 | keep | Keep configurable injected paths and avoid `~/public_html` defaults. |
| Publish local state | PB-S1 | keep | Keep transactional local/gated content, ownership, expiry, credential, and recovery state. |

## Held decision work

The held set is now two D clusters. All eight C measurements and the selected
DT-R1 fixture are bound above.

| Bucket | Cluster | Matrix IDs | Disposition | Waiting for | Producer or decision owner |
|---|---|---|---|---|---|
| D | Orca rooted-artifact deactivation | OR-C4 | hold | Orca capability promotion with immutable upstream evidence across the TRUST boundary. | The upstream evidence producer/promotion owner is currently unassigned; `TRUST_CAPABILITY_GATE` is the consumer. |
| D | Orca rooted paths and serve tree | OR-S4 | hold | Orca capability promotion with immutable upstream evidence across the TRUST boundary. | The upstream evidence producer/promotion owner is currently unassigned; `TRUST_CAPABILITY_GATE` is the consumer. |

The Orca owner check above is bounded to the campaign board and active task documents
on `swk-infra` `origin/main`, plus this repository's ABI files. The same `git grep`
sample positively finds Orca as the `system-unit`/`rooted-artifact` promotion target;
the board activity records that the remaining producer closed and no replacement owner
was assigned. This is a campaign-doc sample, not a company-wide absence claim.

## Decision pinning gate

Coverage and aggregate counts do not identify the selected decision: exchanging two
cluster dispositions preserves both signals. The validator therefore pins every exact
matrix-ID set to its reviewed `keep`, `migrate`, `retire`, or `hold` disposition. A
future decision change must deliberately update both this register and that pin in the
same reviewed change. The pin is appropriate here because these dispositions are this
task's approved output, not values that can be derived again from the census tables.

## Accounting boundary

The positive control is the matrix itself: 134 distinct IDs. The triage partitions
them into A 18, B 13, C 8, D 3, and E 66 clusters. This register assigns all A, B, C,
and E clusters plus one D decision, and holds only D 2: 106 decided plus 2 held, covering 108 clusters and
all 134 matrix IDs exactly once. This is an exhaustive fixed-SHA claim, not a
current-HEAD census; changes after the declared pair require a new delta.
