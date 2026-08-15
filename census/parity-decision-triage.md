# Parity difference decision triage

Status: first-pass triage of 42 clusters (47 matrix IDs)

This document applies the campaign's over-gate to the conservative candidate set
derived from [`parity-matrix.md`](parity-matrix.md). It does **not** choose `keep`,
`drop`, or `migrate`. Each ID below points to the evidence-backed matrix row; this
triage adds no new behavior claim.

The buckets are applied in order:

- **A — do not ask (coexistence possible):** coexistence does not block the parity
  goal; the later disposition phase still decides how that coexistence is delivered.
- **B — do not ask (proceed reversibly):** the choice can be changed after rollout.
- **C — census/measurement:** deployed state or use can answer the open fact.
- **D — ask a person:** the alternatives are mutually exclusive and a wrong choice
  is costly to reverse or silently disconnects an existing user.

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

## Counts

- A: 18 clusters
- B: 13 clusters
- C: 8 clusters
- D: 3 clusters
- Total: 42 clusters / 47 matrix IDs

The D bucket is an escalation list, not a decision. `DT-R1` is already tracked as the
separate `:9900` route decision; it remains here so the 42-cluster input set stays
complete. Its D classification does not bypass the live-evidence prerequisite recorded
in [`devterm-9900.md`](devterm-9900.md); this triage does not open a new question.
