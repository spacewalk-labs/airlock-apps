# Parity difference decision triage

Status: exhaustive triage of 108 clusters (134 matrix IDs)

This document applies the campaign's over-gate to every row derived from
[`parity-matrix.md`](parity-matrix.md). It does **not** choose `keep`, `drop`, or
`migrate`. Each ID below points to the evidence-backed matrix row; this triage adds no
new behavior claim. A-D retain the original conservative decision set, while E closes
the rows that already have a bounded evidence-complete path.

The buckets are applied in order:

- **A — do not ask (coexistence possible):** coexistence does not block the parity
  goal; the later disposition phase still decides how that coexistence is delivered.
- **B — do not ask (proceed reversibly):** the choice can be changed after rollout.
- **C — census/measurement:** deployed state or use can answer the open fact.
- **D — ask a person:** the alternatives are mutually exclusive and a wrong choice
  is costly to reverse or silently disconnects an existing user.
- **E — evidence-complete closure:** fixed-SHA evidence already determines a bounded,
  reversible destination contract. No census, privilege promotion, or person choice is
  needed. E closes rows omitted from the original conservative candidate set; it does
  not weaken A-D.

| Cluster | Related matrix IDs | Bucket | Why |
|---|---|---|---|
| devterm plain-HTTP behavior | DT-R1 | D | Port `:9900` cannot simultaneously serve the terminal and redirect it, and removing the served route can silently disconnect existing HTTP consumers while restoration requires a new route validation and promotion. |
| devterm fleet usage visibility | DT-A1 | C | Caller identities or access records for the four status endpoints can show whether non-owner fleet access is actually used before its audience is narrowed. |
| devterm terminal font | DT-C4 | A | Bundled D2Coding and the platform monospace stack can coexist as available font assets/fallbacks, so preserving both does not block parity. |
| devterm account switcher activation | DT-U2 | A | The existing configuration switch can represent both enabled and disabled deployments, so both behaviors can remain without a human choice. |
| devterm detached login survival | DT-N1 | B | `KillMode` is a reversible unit policy and can be changed in a later app release if runtime evidence shows the initial setting is wrong. |
| devterm locale default | DT-C2 | B | The default locale is a reversible configuration default and can be overridden or changed later. |
| dev-monitor service restart surface | DM-R2, DM-U2 | A | The allow-listed restart API/UI and the existing read-only monitor surface can coexist, so preserving both capabilities does not force a choice. |
| dev-monitor spool firewall | DM-N3 | A | The system firewall guard and the user-owned spool permissions are compatible defense layers, so retaining both does not block the target behavior. |
| dev-monitor executable-skill allow-list | DM-C2 | A | Membership restriction can remain as an optional configuration layer alongside syntax validation, so both controls can coexist. |
| dev-monitor message-console activation | DM-C3 | A | An explicit setting can preserve enabled and disabled deployments, including the currently host-specific deployment, without choosing one behavior globally. |
| code-server fresh-install preferences | CS-C4 | B | Seeded extensions, theme, zoom, and trust values are reversible fresh-install defaults that can be revised in a later release. |
| Markwand split route | MW-R2 | C | Access logs or a bounded request probe on the five boxes can show whether `/markwand/split` is used as a direct split-view route before its compatibility behavior is selected. |
| Markwand PWA installation metadata | MW-U1 | A | The manifest can coexist with the ordinary browser experience, so retaining the installable surface does not require an exclusive choice. |
| Markwand dependency acquisition | MW-C1 | B | Pinning and archive verification are reversible release mechanics, and the selected versions can be changed by a later artifact release. |
| Markwand branding color | MW-C3 | B | The filebrowser branding color is a reversible UI/configuration value. |
| Markwand top-level home aliases | MW-S1 | A | The configured code root and a maintained set of allowed top-level aliases can coexist, so preserving both state views does not require a choice. |
| Markwand hidden credential-directory aliases | MW-S2 | C | The installed links and filebrowser/access logs can establish whether the `.claude` and `.codex` aliases are actually present and used before compatibility is changed. |
| Notepad attachment-token syntax | NP-U1 | A | Both token vocabularies and copy expansions can be recognized concurrently, so leaving compatibility for both does not block parity. |
| Notepad image encoding defaults | NP-U2 | B | Image bounds and JPEG quality are reversible client defaults for future uploads and can be tuned later. |
| Notepad clear-time sequence reset | NP-U4 | B | Resetting or retaining the page-local counter is a reversible UI behavior with no persisted migration boundary. |
| Notepad draft persistence | NP-S1 | A | Browser draft persistence can coexist with session-only attachment maps, so preserving it does not require an exclusive product choice. |
| Orca web-bundle provenance | OR-C3 | A | A pinned served bundle and a source-driven refresh workflow can coexist as build and verification stages, so neither lifecycle has to be discarded. |
| Orca rooted-artifact deactivation | OR-C4 | D | System-unit and rooted-firewall cleanup changes privileged ownership and removal semantics, and reversing a wrong choice requires another rooted-artifact validation and promotion. |
| Orca rooted paths and serve tree | OR-S4 | D | Choosing one rooted layout can strand or replace privileged firewall/serve artifacts, and reversal requires root-level migration plus renewed serving validation. |
| Paseo browse-sidecar activation | PA-R1, PA-C1 | A | The existing activation setting can preserve boxes with and without the route, tools, and live panels, so both deployment modes can remain. |
| Paseo return-widget menu | PA-U1 | A | Menu opening and direct-home fallback already depend on panel availability and can coexist without a global choice. |
| Paseo descendant privilege | PA-N3 | C | Box and session evidence can show whether spawned agents actually depend on setuid `sudo` before the privilege surface is narrowed. |
| Paseo memory limits | PA-N5 | C | Box memory and observed Paseo working-set/pressure data can determine an adequate limit instead of asking for a preference. |
| Paseo task limit | PA-N6 | C | Current and peak task counts on the five boxes can determine whether a finite cap is needed and what range is safe. |
| Paseo accepted hostnames | PA-C2 | C | Gate/access logs and deployed URLs can show whether anyone uses a tailnet-suffix hostname rather than an exact configured host. |
| Paseo ambient OpenAI key | PA-C3 | A | Blocking ambient inheritance and preserving an explicitly configured runtime key can hold at the same time, so the two requirements do not force a choice. |
| Publish management/share paths | PB-R1 | A | Compatibility routes or links can preserve both path families, so their coexistence does not block parity. |
| Publish local/remote gated mode | PB-R2, PB-A2, PB-U6, PB-C2 | A | An explicit target mode and capability negotiation can preserve both local and remote gated publication, so the fleet does not need one global mode choice. |
| Publish remote protocol compatibility | PB-A3 | A | Version/capability negotiation can retain both protocol generations and header compatibility without choosing a single fleet-wide behavior. |
| Publish source provenance | PB-A4 | C | A bounded scan of current publication sources can determine whether any source depends on the more permissive symlink/provenance behavior. |
| Publish bundle attachments and limits | PB-A5 | A | HTML-only and attachment-bearing documents can share one bundle surface with bounded per-kind limits, so both document classes can remain supported. |
| Publish unresolved-asset handling | PB-A6 | B | Bundle validation/failure behavior is a reversible release policy and can be tightened or relaxed in a later artifact version. |
| Publish remote-list conflict handling | PB-A7 | B | Abort/reuse behavior for list failures and duplicate sources is a reversible client policy. |
| Publish direct-file delete confirmation | PB-U4 | B | The confirmation interaction is a reversible UI safeguard and can be adjusted after rollout. |
| Publish unknown external status | PB-U5 | B | Hiding or offering actions while status is unknown is a reversible UI/client failure policy. |
| Publish upload filename normalization | PB-S2 | B | Filename character rules and fallback text are reversible naming defaults; existing stored names need not be renamed by the initial choice. |
| Publish clipboard-image namespace | PB-S3 | B | The filename prefix is a reversible default, and readers can continue to recognize files created under either namespace. |

### E — fixed-SHA exhaustive closure

These 66 clusters cover every matrix ID omitted from the original A-D candidate set.
Compatibility readers do not move canonical writes or privilege ownership.

| Cluster | Related matrix IDs | Bucket | Why |
|---|---|---|---|
| devterm keytest diagnostic | DT-R2 | E | An app-scoped diagnostic page is additive and removable. |
| devterm wrong-method contract | DT-A2 | E | Explicit JSON 405 responses are an additive protocol clarification. |
| devterm install restart discipline | DT-N2 | E | Change-sensitive restarts preserve service continuity. |
| devterm unit identity | DT-N3 | E | Public package ownership requires the `airlock-*` identities. |
| devterm platform configuration and identity | DT-C1, DT-C3 | E | The manifest schema and configured identity header are the portable boundary. |
| devterm usage cache persistence | DT-S1 | E | The bounded, identity-checked cache is safer than process-only state. |
| devterm legacy tab-state path | DT-S2 | E | Compatibility reads need not move canonical writes. |
| dev-monitor token freshness surface | DM-R1, DM-A2, DM-U3, DM-N1, DM-C1, DM-S2 | E | API, UI, units, config, and state are one optional public capability. |
| dev-monitor run retention | DM-A1, DM-U4, DM-S3 | E | API, UI, and persisted retention state form one public capability. |
| dev-monitor bulk message actions | DM-U1 | E | Bulk actions can layer over bounded per-item operations. |
| dev-monitor unit identity | DM-N2 | E | Public package ownership requires the `airlock-*` identity. |
| dev-monitor observability history | DM-S1 | E | Durable app state is preferable to `/tmp`. |
| dev-monitor delivery leases | DM-S4 | E | Claim leases preserve interruption recovery and lane isolation. |
| dev-monitor legacy message-state path | DM-S5 | E | Compatibility reads need not move canonical writes. |
| code-server configurable slots | CS-A1, CS-U1, CS-C1 | E | API, UI, and config are one elastic-slot contract. |
| code-server unit identity | CS-N1 | E | Public package ownership requires the `airlock-*` identities. |
| code-server unit ordering | CS-N2 | E | Network ordering avoids the documented target cycle. |
| code-server install restart discipline | CS-N3 | E | Change-sensitive restarts preserve sessions. |
| code-server identity configuration | CS-C2 | E | Configured headers and fail-closed ownership are portable. |
| code-server architecture support | CS-C3 | E | Verified amd64/arm64 artifacts preserve the broader capability. |
| code-server legacy state | CS-S1, CS-S2 | E | Bounded copy-in can coexist with canonical Airlock paths. |
| feedback owned surface | FB-R1, FB-A1, FB-A2, FB-A3, FB-N1, FB-C1, FB-C2 | E | Route, API, unit, and config are one public-only capability. |
| Markwand legacy edit route | MW-R1 | E | Same-origin redirects preserve callers without a second service. |
| Markwand long editor timeout | MW-R3 | E | The bounded proxy policy supports long editing sessions. |
| Markwand return widget | MW-U2 | E | App navigation is independent of split-page controls. |
| Markwand unit identity | MW-N1 | E | Public package ownership requires the `airlock-*` identities. |
| Markwand linger observation | MW-N2 | E | Read-only validation warns without granting authority. |
| Markwand Node PATH | MW-N3 | E | The discovered executable path makes the unit deterministic. |
| Markwand code-root requirement | MW-C2 | E | An explicit absolute path avoids a host-specific root. |
| Markwand database backup | MW-S3 | E | A bounded pre-mutation backup is reversible. |
| Notepad canonical route | NP-R1 | E | A same-origin redirect can preserve the old path. |
| Notepad upload encoding | NP-A1 | E | Prefix-free base64 can remain canonical with compatibility reads. |
| Notepad upload-size preflight | NP-U3 | E | The existing bound prevents doomed requests. |
| Notepad independent package lifecycle | NP-N1, NP-C1 | E | An explicit Publish dependency preserves independent disable. |
| Orca unit identity | OR-N1 | E | Public package ownership requires the `airlock-*` identities. |
| Orca unit ordering | OR-N2 | E | Network ordering avoids the documented target cycle. |
| Orca partial-deploy restart | OR-N3, OR-S2 | E | Separate flags and drift evidence recover only affected services. |
| Orca linger observation | OR-N4 | E | Read-only validation warns without enabling linger. |
| Orca manifest boundary | OR-C1 | E | Manifest ports and platform audience avoid personal defaults. |
| Orca dry-run renderer | OR-C2 | E | Redirected mutation-free rendering is testable. |
| Orca app-state namespace | OR-S1 | E | The Airlock namespace preserves package ownership. |
| Orca orphan-scope reconciliation | OR-S3 | E | Live scopes can be retained while proven orphans are removed. |
| Paseo stream proxy policy | PA-R2 | E | Long-stream send timeout and disabled buffering are bounded. |
| Paseo unit identity | PA-N1 | E | Public package ownership requires the `airlock-*` identities. |
| Paseo stale pidfile guard | PA-N2 | E | Evidence-gated cleanup prevents restart loops. |
| Paseo shutdown timeout | PA-N4 | E | A unit timeout is reversible release policy. |
| Paseo linger observation | PA-N7 | E | Read-only validation warns without enabling linger. |
| Paseo future provider PATH | PA-N8 | E | Future directories preserve discovery without reinstall. |
| Paseo unit ordering | PA-N9 | E | Network ordering avoids the documented target cycle. |
| Paseo app favicon branding | PA-C4 | E | App-scoped assets do not change global identity. |
| Paseo manifest and sidecar ports | PA-C5, PA-C6 | E | Schema and resolved port propagation are one boundary. |
| Paseo architecture restriction | PA-C7 | E | A host-specific rejection need not become destination policy. |
| Paseo spawned-process ownership | PA-S1 | E | Handle and process-group ownership prevents leaks. |
| Paseo credential metadata preservation | PA-S2 | E | Merge-write preserves unknown upstream fields. |
| Paseo partial-deploy restart | PA-S3 | E | `NeedDaemonReload` is bounded recovery evidence. |
| Publish public contract metadata | PB-A1 | E | Versioned additive fields preserve existing consumers. |
| Publish broken-item contract | PB-A8, PB-U8 | E | API field and repair UI are one contract. |
| Publish direct upload | PB-U1 | E | The bounded upload is an independent capability. |
| Publish theme preference | PB-U2 | E | An app-specific key avoids preference collision. |
| Publish item-type filters | PB-U3 | E | Type filters are independent of publication state. |
| Publish bundle confirmation | PB-U7 | E | Review UI can layer on the bounded bundle API. |
| Publish periodic refresh | PB-U9 | E | Visibility-aware refresh with sequence guards is reversible. |
| Publish unit identity | PB-N1 | E | Public package ownership requires the `airlock-*` identities. |
| Publish cleanup scope | PB-N2 | E | Local-publication reconciliation belongs with expiry. |
| Publish share-root configuration | PB-C1 | E | Injected paths avoid host-specific fixed directories. |
| Publish local state | PB-S1 | E | Transactional local/gated state is the public contract. |

## Counts

- A: 18 clusters
- B: 13 clusters
- C: 8 clusters
- D: 3 clusters
- E: 66 clusters
- Total: 108 clusters / 134 matrix IDs

The D bucket is an escalation list, not a decision. `DT-R1` is already tracked as the
separate `:9900` route decision; it remains here so the original 42-cluster A-D
decision set stays traceable inside the exhaustive register. Its D classification does
not bypass the live-evidence prerequisite recorded
in [`devterm-9900.md`](devterm-9900.md); this triage does not open a new question.
