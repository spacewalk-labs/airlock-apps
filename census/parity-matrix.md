# Public ↔ internal app behavior parity matrix

Status: complete — 9/9 apps inventoried, 134 evidence-backed difference entries

This census records observable or operational differences only. It does not decide
`keep`, `drop`, or `migrate`, and it does not add contracts or tests.

Inputs inspected:

- Public: `893c4da58f9aecb3d25fd085bbbfd57aeb4518d2`
- Internal: `3ced9d54ceb03b118b2961bf3938252f5f397431`

## Method and evidence convention

- `P:` means the public tree rooted at this repository.
- `I:` means the read-only internal tree, written here as `<internal-tree>`.
  The real path names a person's home directory and a private repository, so it
  is redacted — this file is public, and the commands below are reproducible
  only by someone who already has that tree. Substitute your own checkout root.
  Internal unit names are redacted the same way, as `<internal>-…`.
- The six axes are route, API, UI, unit, config, and state. Each numbered row is one
  difference entry; an axis with no entry has no evidenced difference in this sample.
- Route inventory covers explicit handler/proxy paths and intentional human-facing HTML
  pages. It does not count every JavaScript, font, icon, or other static asset as a route.
- API inventory records method, access, and response-contract differences as well as
  endpoint presence. UI inventory records user actions, not copy or translation alone;
  visual defaults such as fonts and installed themes/extensions are classified as config.
- Evidence is current file content with 1-based line numbers. A one-sided feature is
  counted only when its implementation is cited and the bounded opposite app-owned
  scope was checked. The zero-match probes below make those absence checks repeatable;
  they are not a substitute for the positive file-and-line evidence in each row.

Bounded zero-match probes (all were run from the public repository root and returned
no match):

- Z1 — public devterm diagnostic/font assets:
  `rg --files apps/devterm | rg 'keytest\.html|D2Coding'` and
  `rg -n 'D2Coding' apps/devterm`

- Z2 — internal devterm persistent Codex cache:
  `rg -n 'codex-usage\.json|CODEX_USAGE_STATE|_codex_usage_state_(load|save)' <internal-tree>/infra/dev-hub/devterm`

- Z3 — internal dev-monitor token config, units, and state:
  `rg -n 'token[_ -]?fresh|TOKEN_FRESH|token-freshness\.json' <internal-tree>/infra/dev-hub/dev-monitor <internal-tree>/infra/dev-hub/bin/setup-md-notebook.sh`

- Z4 — public dev-monitor system firewall unit:
  `rg -n 'devmon-spool-fw|DEVMON_FW|meta skuid|nft (add|list).*devmon|iptables' apps/dev-monitor`

- Z5 — public dev-monitor skill membership setting:
  `rg -n 'DEV_MONITOR_SKILL_ALLOW|SKILL_ALLOW|allowed_skills' apps/dev-monitor`

- Z6 — public code-server default theme/extension seeding:
  `rg -n 'One Dark Pro|colorTheme|extensions\.json|--install-extension|install-extension' apps/code-server`

- Z7 — public code-server legacy-copy implementation:
  `rg -n 'OLD_UDD|OLD_EXT|cp -an' apps/code-server`

- Z8 — internal feedback implementation, registration, routes, units, and config:
  `rg -n -i --glob '!**/__pycache__/**' --glob '!**/*.pyc' 'airlock-feedback|feedback/api|apps\.feedback|feedback\.service|AIRLOCK_FEEDBACK' <internal-tree>/infra/dev-hub` and
  `rg --files <internal-tree>/infra/dev-hub | rg '(^|/)feedback(/|\.|$)|(^|/)[^/]*feedback[^/]*$'`

- Z9 — internal notepad editor-text persistence:
  `rg -n 'localStorage|airlock\.notepad\.text' <internal-tree>/infra/dev-hub/publish-manager/frontend/notepad.html`

- Z10 — internal notepad encoded-payload preflight:
  `rg -n 'MAX_ENCODED|b64\.length|stripPrefix\(out\.upload\)' <internal-tree>/infra/dev-hub/publish-manager/frontend/notepad.html`

- Z11 — internal notepad file-sequence reset in the clear handler:
  `rg -n "editor\.value = ''; imgMap\.clear\(\); fileMap\.clear\(\); viewMap\.clear\(\); fileSeq = 0" <internal-tree>/infra/dev-hub/publish-manager/frontend/notepad.html`

- Z12 — public Markwand legacy `/edit` redirects:
  `rg -n 'location[[:space:]]+(=|~)[[:space:]]+/edit|return 302 /markwand/edit' apps/markwand`

- Z13 — public Markwand special `/markwand/split` route:
  `rg -n 'location[[:space:]]+=[[:space:]]+/markwand/split' apps/markwand`

- Z14 — internal Markwand editor-proxy read timeout:
  `sed -n '1145,1159p' <internal-tree>/infra/dev-hub/bin/setup-md-notebook.sh | rg -n 'proxy_read_timeout'`

- Z15 — public Markwand PWA manifest advertisement or asset:
  `rg -n '<link rel="manifest"|markwand-manifest' apps/markwand`

- Z16 — internal direct-file viewer Airlock return widget:
  `sed -n '1161,1176p' <internal-tree>/infra/dev-hub/bin/setup-md-notebook.sh | rg -n 'airlock-return\.js'`

- Z17 — public Markwand linger setup or validation:
  `rg -n 'loginctl|enable-linger' apps/markwand`

- Z18 — internal Markwand unit `PATH` injection:
  `sed -n '195,211p' <internal-tree>/infra/dev-hub/bin/setup-md-notebook.sh | rg -n 'Environment=PATH'`

- Z19 — public Markwand filebrowser branding color migration:
  `rg -n 'branding\.color' apps/markwand`

- Z20 — public Markwand served-root symlink creation or reconciliation:
  `rg -n -g '!**/static/vendor/**' '(^|[;&|[:space:]])ln[[:space:]]+-s(fn|f|n)?|readlink|shopt' apps/markwand`

- Z21 — public Markwand timestamped filebrowser DB backup:
  `rg -n 'FB_DB\.bak|cp[[:space:]]+-a.*FB_DB' apps/markwand`

- Z22 — public Orca app-specific owner setting:
  `rg -n 'ORCA_ALLOW' apps/orca --glob '!web-bundle/dist/**'`

- Z23 — internal Orca dry-run/render-destination controls:
  `rg -n 'AIRLOCK_RENDER_DIR|AIRLOCK_DRY_RUN' <internal-tree>/infra/dev-hub/orca`

- Z24 — internal Orca inventory's rooted-artifact retirement declarations:
  `sed -n '297,337p' <internal-tree>/infra/dev-hub/ownership.json | rg -n 'rooted|orca-firewall\.nft|unit-file-rm'`

- Z25 — public Orca partial-deployment drift recovery:
  `rg -n 'NeedDaemonReload|ActiveEnterTimestamp|orca_stale_binary' apps/orca --glob '!web-bundle/dist/**'`

- Z26 — public Orca live-instance-safe orphan reconciliation:
  `rg -n 'scope_has_serve|고아 scope|reaped=.*app-orca' apps/orca --glob '!web-bundle/dist/**'`

- Z27 — public Paseo send-timeout/response-buffering overrides:
  `sed -n '141,177p' apps/paseo/render.sh | rg -n 'proxy_send_timeout|proxy_buffering'`

- Z28 — internal Paseo stale-pid pre-start guard:
  `rg -n 'ExecStartPre|clear-stale-pid|paseo\.pid' <internal-tree>/infra/dev-hub/paseo`

- Z29 — public Paseo stop timeout:
  `rg -n 'TimeoutStopSec' apps/paseo`

- Z30 — public Paseo linger setup or validation:
  `rg -n 'enable-linger|Linger=yes' apps/paseo`

- Z31 — public Paseo ambient `OPENAI_API_KEY` removal:
  `rg -n 'UnsetEnvironment=OPENAI_API_KEY|codex-strip-ambient-openai-key|paseo-codex-strip-ambient-openai-key' apps/paseo`

- Z32 — internal Paseo favicon-ring transformation:
  `rg -n 'favicon-ring|AIRLOCK_ICON_RING|ring_icon_svg' <internal-tree>/infra/dev-hub/paseo` and
  `sed -n '770,830p' <internal-tree>/infra/dev-hub/bin/setup-md-notebook.sh | rg -n 'favicon|assets/assets/images'`

- Z33 — internal Paseo orphan process guard/group patches:
  `rg -n 'orphan-process-guard|paseo-orphan-guard|orphan-process-group|paseo-process-group' <internal-tree>/infra/dev-hub/paseo`

- Z34 — internal Paseo credential-key preservation patch:
  `rg -n 'credential-key-preservation|paseo-cred-preserve' <internal-tree>/infra/dev-hub/paseo`

- Z35 — internal Publish local gated route:
  `rg -n 'publish-gated|HTPASSWD|publish-gated-auth|Restricted document|location .*\^/g/' <internal-tree>/infra/dev-hub/publish-manager <internal-tree>/infra/dev-hub/bin/setup-md-notebook.sh`

- Z36 — public Publish bundle attachments:
  `rg -n 'MAX_BUNDLE_ATTACHMENTS|attachment_bytes|_collect_bundle_attachments|plan\.attachments' apps/publish/backend apps/publish/frontend`

- Z37 — public Publish source-provenance machinery:
  `rg -n '_publish_source_identity|_git_tracked|external symlink target|FetchFingerprint' apps/publish/backend apps/publish/frontend`

- Z38 — internal Publish on-box local-publication state:
  `rg -n 'publish-public\.json|AIRLOCK_PUBLISH_PUBLIC_MODE|AIRLOCK_PUBLISH_PUBLIC_DIR|_local_ingest|def _reconcile' <internal-tree>/infra/dev-hub/publish-manager <internal-tree>/infra/dev-hub/bin/setup-md-notebook.sh`

- Z39 — internal Publish manager upload UI:
  `rg -n 'type="file"|upload-file' <internal-tree>/infra/dev-hub/publish-manager/frontend/publish-manager.html`

- Z40 — public Publish theme control/state:
  `rg -n 'data-theme-btn|markwand-theme' apps/publish/frontend/publish.html`

- Z41 — internal Publish item-type filter:
  `rg -n 'id="type"|#type|\$\("#type"\)' <internal-tree>/infra/dev-hub/publish-manager/frontend/publish-manager.html`

- Z42 — public Orca linger setup or validation:
  `rg -n 'loginctl|enable-linger|Linger=yes' apps/orca --glob '!web-bundle/dist/**'`

- Z43 — public Paseo partial-deployment systemd drift recovery:
  `rg -n 'NeedDaemonReload' apps/paseo`

- Z44 — internal Publish broken-link field:
  `rg -n 'isBroken' <internal-tree>/infra/dev-hub/publish-manager/backend/publish-manager.py`

- Z45 — public Paseo explicit architecture rejection:
  `rg -n 'uname -m|x86_64|aarch64|arm64|unsupported arch|미지원 arch' apps/paseo --glob '!patches/*.patch' --glob '!browse-host/test/**'`

- Z46 — public Publish periodic UI refresh:
  `rg -n 'setInterval' apps/publish/frontend/publish.html`

## devterm

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| DT-R1 | route | public | Plain HTTP `:9900` is redirect-only: the public manifest maps `public_port` to a separate redirect listener, requests an HTTPS redirect from the platform renderer, and its smoke contract requires 301 plus an HTTPS location. Internal maps `:9900` directly to the owner gate, so the terminal application is served over HTTP as well as HTTPS. | P: `apps/devterm/airlock-app.toml:101-102`; P: `apps/devterm/render.sh:62-68`; P: `apps/devterm/smoke.sh:34-36`; P: `apps/devterm/smoke.sh:65-69`; I: `infra/dev-hub/devterm/bin/install.sh:126-140` |
| DT-R2 | route | internal | `/keytest.html` is an intentional Hangul/input diagnostic page in the internal web root. The public web-root inventory has no corresponding page. | I: `infra/dev-hub/devterm/web/keytest.html:1-6`; P: `apps/devterm/install.sh:147-159`; Z1 |
| DT-A1 | API | internal | `GET /claude-status`, `/claude-usage`, `/claude-usage-store`, and `/codex-usage` admit any authenticated company-domain identity. Public re-checks every route against the owner allow-list, so these four fleet-readable responses are owner-only there. | I: `infra/dev-hub/devterm/backend/devterm-gate.py:216-220`; I: `infra/dev-hub/devterm/backend/devterm-gate.py:2395-2405`; P: `apps/devterm/backend/devterm-gate.py:2465-2475` |
| DT-A2 | API | internal | A wrong method on `/secret-put`, `/secret-list`, or `/secret-del` returns JSON `405 method not allowed`. Public only dispatches the allowed method and otherwise falls through to static handling, so the same wrong-method request does not have the internal 405 contract. | I: `infra/dev-hub/devterm/backend/devterm-gate.py:2410-2424`; P: `apps/devterm/backend/devterm-gate.py:2518-2523`; P: `apps/devterm/backend/devterm-gate.py:2550-2551` |
| DT-C4 | config | internal | The terminal waits for bundled D2Coding regular/bold fonts and uses D2Coding as its first terminal font. Public uses the platform monospace stack and bundles no D2Coding font files. | I: `infra/dev-hub/devterm/web/index.html:52-57`; I: `infra/dev-hub/devterm/web/app.js:18-24`; I: `infra/dev-hub/devterm/web/app.js:121`; P: `apps/devterm/web/app.js:122`; P: `apps/devterm/install.sh:152-158`; Z1 |
| DT-U2 | UI | internal by default | Internal always renders the account-switch action and installs the status probe; public renders that action only when `accounts=true`, defaults it off, and installs/wires the account tools only when enabled. Both sides deploy the account UI assets, so asset presence is not counted as a difference. | I: `infra/dev-hub/devterm/web/app.js:810-823`; I: `infra/dev-hub/devterm/bin/install.sh:54-67`; P: `apps/devterm/web/app.js:20-22`; P: `apps/devterm/web/app.js:795-803`; P: `apps/devterm/airlock-app.toml:14-19`; P: `apps/devterm/install.sh:131-158` |
| DT-N1 | unit | public | The public gate unit uses `KillMode=process`, explicitly allowing a detached `codex login --device-auth` process to survive a gate redeploy. The internal gate unit has no `KillMode` override, although its ttyd unit does. | P: `apps/devterm/render.sh:46-55`; I: `infra/dev-hub/devterm/bin/install.sh:69-110` |
| DT-N2 | unit | public | Public installation restarts ttyd and gate only when rendered content changed or a unit is inactive. Internal installation unconditionally restarts ttyd and then the gate on every run. | P: `apps/devterm/install.sh:168-186`; P: `apps/devterm/install.sh:253-263`; I: `infra/dev-hub/devterm/bin/install.sh:113-118` |
| DT-N3 | unit | naming differs | Public owns `airlock-devterm.service` and `airlock-devterm-gate.service`; internal owns `<internal>-devterm-ttyd.service` and `<internal>-devterm-gate.service`. The ttyd role therefore changes unit identity across trees. | P: `apps/devterm/airlock-app.toml:90-95`; I: `infra/dev-hub/devterm/bin/install.sh:69-110` |
| DT-C1 | config | public | Public exposes `accounts`, `secret_ttl_sec`, `claude_switch`, `claude_status`, `fleet_store`, `fleet_store_url`, `orca_shim`, ports, font size, and locale in the app config schema. Internal has shell environment inputs for a subset, but its installer fixes account wiring and does not expose a comparable app config schema. | P: `apps/devterm/airlock-app.toml:5-22`; I: `infra/dev-hub/devterm/bin/install.sh:12-24`; I: `infra/dev-hub/devterm/bin/install.sh:54-67` |
| DT-C2 | config | defaults differ | Public defaults the unit locale to `C.UTF-8`; internal defaults to `ko_KR.UTF-8`. | P: `apps/devterm/airlock-app.toml:12-13`; I: `infra/dev-hub/devterm/bin/install.sh:21-23` |
| DT-C3 | config | public | Public derives the identity header from platform config, injects it into the gate environment, and reads that name at runtime; internal hardcodes `tailscale-user-login` in the gate. | P: `apps/devterm/install.sh:32-40`; P: `apps/devterm/install.sh:218-225`; P: `apps/devterm/backend/devterm-gate.py:130-131`; I: `infra/dev-hub/devterm/backend/devterm-gate.py:213-218` |
| DT-S1 | state | public | The last good Codex usage reading is written to `~/.local/state/airlock/devterm/codex-usage.json`, loaded at gate startup, rejected after an auth-file identity change, and shown stale until refreshed. Internal keeps this cache only in process memory, so a gate restart starts without the remembered reading. | P: `apps/devterm/backend/devterm-gate.py:165-173`; P: `apps/devterm/backend/devterm-gate.py:2130-2186`; P: `apps/devterm/backend/devterm-gate.py:2619-2624`; I: `infra/dev-hub/devterm/backend/devterm-gate.py:2034-2063`; Z2 |
| DT-S2 | state | path differs | Server-side tab order/hidden/color/theme state is `~/.config/airlock-devterm/tabs.json` publicly and `~/.config/devterm/tabs.json` internally. | P: `apps/devterm/backend/devterm-gate.py:159-163`; I: `infra/dev-hub/devterm/backend/devterm-gate.py:273-276` |

Sample count: **14 difference entries**.

## dev-monitor

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| DM-R1 | route | public | `GET /monitor/api/tokens` (also `/tokens`) exists when token freshness is enabled; it returns live provider verdicts plus the scheduled check's last snapshot time. When disabled it returns a non-empty 404 reason rather than an empty success. Internal has no tokens branch in its complete GET dispatcher. | P: `apps/dev-monitor/backend/airlock-dev-monitor.py:622-649`; P: `apps/dev-monitor/backend/airlock-dev-monitor.py:738-747`; I: `infra/dev-hub/dev-monitor/backend/dev-monitor.py:612-659` |
| DM-R2 | route | internal | `POST /monitor/api/service/restart` (also `/service/restart`) restarts allow-listed user services and refuses system services. Public's complete non-owner POST dispatcher only returns 404. | I: `infra/dev-hub/dev-monitor/backend/dev-monitor.py:244-254`; I: `infra/dev-hub/dev-monitor/backend/dev-monitor.py:661-674`; P: `apps/dev-monitor/backend/airlock-dev-monitor.py:781-787` |
| DM-A1 | API | public | `POST /api/owner/runs/{run_id}/keep` persists an owner choice that exempts a completed run from 24-hour reclamation; success returns `{ok, run_id, keep:true}`. Internal owner-run POST routes only support `stop` and `view`. | P: `apps/dev-monitor/backend/airlock-dev-monitor.py:873-883`; P: `apps/dev-monitor/backend/airlock-dev-monitor.py:979-987`; I: `infra/dev-hub/dev-monitor/backend/dev-monitor.py:771-779` |
| DM-A2 | API | public | `/api/health` reports the realized message feature state, requested message state, and token-freshness state. Internal health only returns `{ok, service, port}`. | P: `apps/dev-monitor/backend/airlock-dev-monitor.py:769-777`; I: `infra/dev-hub/dev-monitor/backend/dev-monitor.py:656-658` |
| DM-U1 | UI | internal | The message console has per-card checkboxes, “select all visible”, and bulk unpin/archive/dismiss with progress, partial-failure reporting, and undo. Public has individual card actions only. | I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:292-300`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:914-1011`; P: `apps/dev-monitor/frontend/dev-monitor.html:293-298`; P: `apps/dev-monitor/frontend/dev-monitor.html:929-937` |
| DM-U2 | UI | internal | The services table exposes restart buttons for user services, while public exposes no restart control. Internal's log selector is a fixed four-service list; public populates it from all discovered user services. | I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:375`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:557-563`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:644-658`; P: `apps/dev-monitor/frontend/dev-monitor.html:524-535` |
| DM-U3 | UI | public | A Credentials card displays token expiry/staleness and last-check state. Internal has no Credentials section between Host and CPU. | P: `apps/dev-monitor/frontend/dev-monitor.html:316-321`; P: `apps/dev-monitor/frontend/dev-monitor.html:629-664`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:309-327` |
| DM-U4 | UI | public | Completed-run detail includes “Keep window”; internal detail has stop/view/close but no retention exemption action. | P: `apps/dev-monitor/frontend/dev-monitor.html:394-397`; P: `apps/dev-monitor/frontend/dev-monitor.html:1166-1173`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:406-408` |
| DM-N1 | unit | public | Public can install three additional user units for credential monitoring: a oneshot checker, an `OnFailure` alarm, and a persistent randomized timer. Internal setup creates no equivalent credential-check units. | P: `apps/dev-monitor/systemd/airlock-token-freshness.service.in:1-29`; P: `apps/dev-monitor/systemd/airlock-token-freshness-failed.service.in:1-10`; P: `apps/dev-monitor/systemd/airlock-token-freshness.timer.in:1-16`; P: `apps/dev-monitor/install-token-timer.sh:55-56`; P: `apps/dev-monitor/install-token-timer.sh:130-150`; Z3 |
| DM-N2 | unit | naming differs | Public owns `airlock-dev-monitor.service`; internal owns `dev-monitor.service`. | P: `apps/dev-monitor/airlock-app.toml:60-69`; I: `infra/dev-hub/bin/setup-md-notebook.sh:500-512` |
| DM-N3 | unit | internal | Internal conditionally owns a system-level `devmon-spool-fw.service` that blocks the low-trust spool UID from all loopback traffic, and disables the message/action feature if that firewall cannot be proven. Public's app package declares only its main user unit and creates a user-owned 0700 spool, with no matching system firewall unit. | I: `infra/dev-hub/bin/setup-md-notebook.sh:375-432`; P: `apps/dev-monitor/airlock-app.toml:60-69`; P: `apps/dev-monitor/install.sh:103-121`; Z4 |
| DM-C1 | config | public | Token monitoring is explicitly configurable with `token_freshness`, warning hours, and stale hours; it defaults off. Internal has no corresponding settings. | P: `apps/dev-monitor/airlock-app.toml:19-29`; P: `apps/dev-monitor/render.sh:25-34`; Z3 |
| DM-C2 | config | internal | `DEV_MONITOR_SKILL_ALLOW` can restrict executable skill names and participates in plan validation. Public validates skill syntax without a membership knob. | I: `infra/dev-hub/dev-monitor/backend/dev-monitor.py:1095-1100`; I: `infra/dev-hub/dev-monitor/backend/devmon_messages.py:616-625`; P: `apps/dev-monitor/airlock-app.toml:13-29`; P: `apps/dev-monitor/backend/devmon_messages.py:712-764`; P: `apps/dev-monitor/backend/airlock-dev-monitor.py:1314-1333`; Z5 |
| DM-C3 | config | deployment differs | Public exposes `messages` as an app setting on any installed box. Internal setup enables the message/action console only when the hostname is exactly one specific box and its firewall precondition passes. | P: `apps/dev-monitor/airlock-app.toml:13-18`; P: `apps/dev-monitor/install.sh:88-117`; I: `infra/dev-hub/bin/setup-md-notebook.sh:362-365`; I: `infra/dev-hub/bin/setup-md-notebook.sh:443-485` |
| DM-S1 | state | public | Observability history is kept under `~/.local/share/airlock-dev-monitor/history.csv`. Internal defaults history to `/tmp/dev-monitor-history.csv`, so it is not in a durable application state directory. | P: `apps/dev-monitor/backend/airlock-dev-monitor.py:95-99`; I: `infra/dev-hub/dev-monitor/backend/dev-monitor.py:36-38` |
| DM-S2 | state | public | Token checks persist `token-freshness.json` in the Airlock state directory; the UI distinguishes “never checked” from an aged scheduled result. Internal has no token snapshot state. | P: `apps/dev-monitor/install-token-timer.sh:29-31`; P: `apps/dev-monitor/backend/airlock-dev-monitor.py:623-641`; Z3 |
| DM-S3 | state | public | Completed Claude runs have `keep_requested`, `kept_at`, and `reclaimed_at`; unkept runs are reclaimed 24 hours after turn end, including tmux window and sentinels. Internal's run schema ends at `ended_at` and has no retention/reclamation state. | P: `apps/dev-monitor/backend/devmon_messages.py:335-350`; P: `apps/dev-monitor/backend/airlock-dev-monitor.py:91-93`; P: `apps/dev-monitor/backend/airlock-dev-monitor.py:1196-1260`; I: `infra/dev-hub/dev-monitor/backend/devmon_messages.py:222-234` |
| DM-S4 | state | public | Delivery rows are lane-aware and claim-leased (`claimed_by`, `lease_until`, per-channel indexes/uniqueness); interrupted claims are returned to pending at startup. Internal delivery state has no claim owner or lease and its worker claims one undifferentiated queue. | P: `apps/dev-monitor/backend/devmon_messages.py:183-184`; P: `apps/dev-monitor/backend/devmon_messages.py:211-277`; P: `apps/dev-monitor/backend/devmon_messages.py:364-377`; P: `apps/dev-monitor/backend/devmon_slack.py:64-76`; I: `infra/dev-hub/dev-monitor/backend/devmon_messages.py:248-257`; I: `infra/dev-hub/dev-monitor/backend/devmon_slack.py:57-66` |
| DM-S5 | state | path differs | Public message DB/spool defaults under `~/.local/state/airlock/dev-monitor`; internal uses `~/.local/state/dev-monitor`. | P: `apps/dev-monitor/install.sh:53-55`; P: `apps/dev-monitor/install.sh:143-153`; I: `infra/dev-hub/bin/setup-md-notebook.sh:362-367`; I: `infra/dev-hub/bin/setup-md-notebook.sh:453-461` |

Sample count: **19 difference entries**.

## code-server

Coverage note (not counted as a difference): the public app delegates nginx route
generation to the platform-owned `gate/nginx-lib.sh`, which is not present in this
app-artifact repository (P: `apps/code-server/install.sh:24-28`;
P: `apps/code-server/render.sh:71-77`). Internal hardcodes `/s/1/` through `/s/4/`
(I: `infra/dev-hub/bin/setup-md-notebook.sh:1239-1296`). Without the current public
generator body, a route-only difference cannot be evidenced from the two specified
trees, so none is claimed here.

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| CS-A1 | API | public | `/api/list`, `/api/spawn`, `/api/kill`, and `/api/prefs` have the same endpoint set, but public derives valid slots, returned `maxSlots`, port values, and range validation from configuration. Internal hardcodes `MAX_SLOTS=4` and `port=18810+slot`. | P: `apps/code-server/manager/manager.py:28-53`; P: `apps/code-server/manager/manager.py:390-457`; I: `infra/dev-hub/code-server/manager/manager.py:10-18`; I: `infra/dev-hub/code-server/manager/manager.py:346-412` |
| CS-U1 | UI | public | The shell renders and validates any configured slot count up to a defensive UI cap of 64, and cycles default colors beyond slot 4. Internal renders a fixed four-slot model and fixed four default colors. | P: `apps/code-server/web/shell.html:164-205`; I: `infra/dev-hub/code-server/web/index.html:165-189` |
| CS-C4 | config | internal | Fresh install seeds One Dark Pro, disables workspace trust, sets zoom +1 for all four slots, and installs Claude Code plus One Dark Pro extensions. Public creates the shared extensions directory but does not seed settings or install default extensions. | I: `infra/dev-hub/code-server/bin/install.sh:94-135`; P: `apps/code-server/install.sh:95-117`; Z6 |
| CS-N1 | unit | naming differs | Public manager controls `airlock-code-server@N.service` and owns `airlock-code-server-manager.service`; internal controls `<internal>-codeserver@N.service` and owns `<internal>-codeserver-manager.service`. | P: `apps/code-server/manager/manager.py:51-64`; P: `apps/code-server/airlock-app.toml:106-114`; I: `infra/dev-hub/code-server/manager/manager.py:164-212`; I: `infra/dev-hub/code-server/bin/install.sh:36-40` |
| CS-N2 | unit | public | The public manager unit orders after `network.target`. Internal orders after `default.target` while also being wanted by `default.target`; public comments identify this as the ordering-cycle pattern it avoids. | P: `apps/code-server/render.sh:41-47`; P: `apps/code-server/render.sh:66-68`; I: `infra/dev-hub/code-server/bin/install.sh:161-181` |
| CS-N3 | unit | public | Reinstall restarts manager and slot 1 only when installed content changed; otherwise it only starts them if needed. Internal always restarts both on every install. | P: `apps/code-server/install.sh:95-117`; P: `apps/code-server/install.sh:136-146`; I: `infra/dev-hub/code-server/bin/install.sh:188-200` |
| CS-C1 | config | public | `https_port`, `gate_port`, `backend_port`, `manager_port`, and `slots` are app config with defaults. Internal exposes only owner/gate/HTTPS as shell inputs while manager port, backend slot ports, and slot count remain fixed in code/unit templates. | P: `apps/code-server/airlock-app.toml:13-26`; I: `infra/dev-hub/code-server/bin/install.sh:12-16`; I: `infra/dev-hub/code-server/manager/manager.py:10-18` |
| CS-C2 | config | public | The identity header name is platform-configured, injected into the manager unit, and the manager fails closed if it is absent. Internal hardcodes `tailscale-user-login` and defaults the allowed login to `cho@<company-domain>`. | P: `apps/code-server/render.sh:37-56`; P: `apps/code-server/manager/manager.py:41-49`; I: `infra/dev-hub/code-server/manager/manager.py:15-18` |
| CS-C3 | config | public | Pinned binaries support both amd64 and arm64. Internal rejects arm64 and supports only the pinned amd64 asset. | P: `apps/code-server/install.sh:56-63`; I: `infra/dev-hub/code-server/bin/install.sh:17-29` |
| CS-S1 | state | path differs | Public slot user data/extensions live at `~/.local/share/airlock-code-server/{slots/N,extensions}` and tab prefs at `~/.config/airlock-code-server/tabs.json`. Internal uses `~/.local/share/code-server-slots/{N,extensions}` and `~/.config/code-server-tabs/tabs.json`. | P: `apps/code-server/bin/airlock-code-server-slot:22-26`; P: `apps/code-server/manager/manager.py:51-52`; P: `apps/code-server/manager/manager.py:197-204`; I: `infra/dev-hub/code-server/bin/install.sh:15`; I: `infra/dev-hub/code-server/manager/manager.py:15-18` |
| CS-S2 | state | internal | Internal performs a one-time migration from the legacy single-instance `~/.local/share/code-server` into slot 1/shared extensions. Public explicitly treats installation as greenfield and has no legacy-copy implementation in its app-owned scope. | I: `infra/dev-hub/code-server/bin/install.sh:99-110`; P: `apps/code-server/install.sh:8-13`; Z7 |

Sample count: **11 difference entries**.

## feedback

Internal coverage note: none of the five internal box profiles registers feedback
(I: `infra/dev-hub/roster.json:10-13`; I: `infra/dev-hub/roster.json:25-27`;
I: `infra/dev-hub/roster.json:36-38`; I: `infra/dev-hub/roster.json:47-49`;
I: `infra/dev-hub/roster.json:58-60`), and Z8 finds no implementation anywhere in
the internal runtime tree. The public app says its suggestion-box UI lives in the
platform hub, but that hub UI source is outside this app-artifact repository
(P: `apps/feedback/render.sh:45-48`). Therefore no UI behavior is claimed without
an implementation line in the specified public tree.

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| FB-R1 | route | public | The rendered hub fragment exposes `/feedback/api/` as a same-origin proxy to a loopback backend. Internal has no feedback route or implementation. Access-control behavior is not claimed because the public server-level gate implementation is outside the specified tree. | P: `apps/feedback/render.sh:41-53`; Z8 |
| FB-A1 | API | public | `GET /feedback/api/health` (backend aliases `/api/health`, `/health`, and `/`) returns `{ok, service, port, enabled, intake, mail}`, making disabled or partially configured delivery visible. Internal has no feedback API. | P: `apps/feedback/backend/airlock-feedback.py:164-185`; Z8 |
| FB-A2 | API | public | `POST /feedback/api/submit` accepts `{text}`, takes the submitter from the configured identity header while ignoring any client owner field, rejects empty or over-8,000-character text, and returns success/failure JSON with status `200`/`400`. | P: `apps/feedback/backend/airlock-feedback.py:65-66`; P: `apps/feedback/backend/airlock-feedback.py:119-128`; P: `apps/feedback/backend/airlock-feedback.py:171-195`; Z8 |
| FB-A3 | API | public | Delivery can target an external intake, transactional mail, or both. Intake sends `{owner,text}` with a dedicated token header and returns `issue_url`; mail conditionally sets `reply_to`. When both are enabled, every target must succeed; mail-provider error bodies and API keys are not returned. | P: `apps/feedback/backend/airlock-feedback.py:74-116`; P: `apps/feedback/backend/airlock-feedback.py:119-142`; Z8 |
| FB-N1 | unit | public | `airlock-feedback.service` is a user unit ordered after network, reads an optional private environment file, runs the loopback Python backend, restarts on failure, and is enabled/restarted by installation. Internal owns no feedback unit. | P: `apps/feedback/render.sh:8-38`; P: `apps/feedback/install.sh:60-74`; Z8 |
| FB-C1 | config | public | App config exposes `backend_port`, external intake URL/token-env name, mail recipient/sender/API/key-env name, and the runtime token environment; no secret value is stored in the app manifest. | P: `apps/feedback/airlock-app.toml:10-24`; Z8 |
| FB-C2 | config | public | Intake becomes active only with URL plus token; mail requires recipient, sender, and API key. With neither complete, submissions report not configured. Secret values are resolved through configured environment-variable names and the optional unit `EnvironmentFile`. | P: `apps/feedback/backend/airlock-feedback.py:41-63`; P: `apps/feedback/backend/airlock-feedback.py:119-127`; P: `apps/feedback/render.sh:20-31`; Z8 |

Difference count: **7 entries**.

## markwand

Coverage note (not counted as a difference): internal's shared hub server owns
`/__reset` and old Markwand/SilverBullet service-worker cleanup routes
(I: `infra/dev-hub/bin/setup-md-notebook.sh:1097-1119`). The public hub source is
outside this app-artifact repository, so the matrix cannot establish whether the
public platform has an equivalent global route. The same boundary prevents a claim
about the complete public hub allow-list. API calls used by the two split viewers
have no evidenced request/response difference, so no API row is added.

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| MW-R1 | route | internal | `/edit`, `/edit/`, and `/edit/<path>` return compatibility redirects into `/markwand/edit/...`. The public app route renderer has no legacy `/edit` route. | I: `infra/dev-hub/bin/setup-md-notebook.sh:1127-1132`; P: `apps/markwand/render.sh:55-102`; Z12 |
| MW-R2 | route | internal | `/markwand/split` directly serves the split viewer. Public special-cases only exact `/markwand/`; `/markwand/split` falls through the ordinary markserv prefix proxy. | I: `infra/dev-hub/bin/setup-md-notebook.sh:1134-1143`; P: `apps/markwand/render.sh:77-101`; Z13 |
| MW-R3 | route | public | The filebrowser editor proxy sets `proxy_read_timeout 86400s`; the internal editor location has no read-timeout override. | P: `apps/markwand/render.sh:63-75`; I: `infra/dev-hub/bin/setup-md-notebook.sh:1145-1159`; Z14 |
| MW-U1 | UI | internal | The split viewer advertises an installable PWA manifest whose name/start URL are `SWK Dev Hub` and `/`. Public supplies Markwand icon metadata but advertises no manifest, so it has no equivalent install-to-home contract in the app artifact. | I: `infra/dev-hub/markwand/static/markwand-split.html:7-18`; I: `infra/dev-hub/markwand/static/markwand-manifest.json:1-12`; P: `apps/markwand/static/markwand-split.html:6-22`; Z15 |
| MW-U2 | UI | public | Direct `/markwand/<file>` markserv pages receive the shared Airlock return widget in addition to enhance/edit controls. Internal direct-file pages inject enhance/edit controls only; its split page's own Airlock button is a separate surface. | P: `apps/markwand/render.sh:88-100`; I: `infra/dev-hub/bin/setup-md-notebook.sh:1161-1176`; Z16 |
| MW-N1 | unit | naming differs | Public owns `airlock-markserv.service` and `airlock-filebrowser.service`; internal owns `markserv.service` and `filebrowser.service`. | P: `apps/markwand/airlock-app.toml:64-70`; I: `infra/dev-hub/bin/setup-md-notebook.sh:109-113`; I: `infra/dev-hub/bin/setup-md-notebook.sh:195-231` |
| MW-N2 | unit | internal | Installation checks user linger and enables it when absent, keeping user units alive after logout. The public Markwand installer neither sets nor validates linger. | I: `infra/dev-hub/bin/setup-md-notebook.sh:233-236`; P: `apps/markwand/install.sh:168-217`; Z17 |
| MW-N3 | unit | public | The markserv unit receives an explicit `PATH` containing the discovered Node directory. Internal relies on the systemd default environment for markserv's `env node` launcher. | P: `apps/markwand/install.sh:84-96`; P: `apps/markwand/render.sh:19-26`; I: `infra/dev-hub/bin/setup-md-notebook.sh:195-211`; Z18 |
| MW-C1 | config | public | Public pins markserv `1.17.4` and filebrowser `2.63.18` and verifies the filebrowser archive checksum. Internal retains any existing global markserv or installs it without a version and downloads filebrowser `latest` without checksum verification. | P: `apps/markwand/install.sh:67-68`; P: `apps/markwand/install.sh:115-166`; I: `infra/dev-hub/bin/setup-md-notebook.sh:176-193` |
| MW-C2 | config | defaults differ | Public requires global `paths.code_root` to be a configured absolute path with no fallback. Internal accepts `ROOT_DIR` and defaults it to `$HOME/code`. The equal port defaults are not counted. | P: `apps/markwand/install.sh:49-61`; I: `infra/dev-hub/bin/setup-md-notebook.sh:104-108` |
| MW-C3 | config | internal | Filebrowser DB migration writes `branding.color=#0f766e` as well as name/files. Public migrates only branding name/files. | I: `infra/dev-hub/bin/setup-md-notebook.sh:253-267`; P: `apps/markwand/install.sh:195-212`; Z19 |
| MW-S1 | state | internal | Installation builds a served-root symlink farm from allowed non-hidden top-level home directories and removes stale links. Public only ensures the configured `CODE_ROOT` directory exists. | I: `infra/dev-hub/bin/setup-md-notebook.sh:146-174`; P: `apps/markwand/install.sh:98-100`; Z20 |
| MW-S2 | state | internal | Installation additionally exposes hidden `~/.claude` and `~/.codex` as `${ROOT_DIR}/claude` and `${ROOT_DIR}/codex`. The public app installer creates no corresponding aliases. | I: `infra/dev-hub/bin/setup-md-notebook.sh:294-304`; Z20 |
| MW-S3 | state | internal | Before changing filebrowser DB settings, internal creates a timestamped `fb.db.bak.YYYYMMDD-HHMM` copy. Public updates the same DB without a backup step. | I: `infra/dev-hub/bin/setup-md-notebook.sh:253-268`; P: `apps/markwand/install.sh:195-213`; Z21 |

Difference count: **14 entries**.

## notepad

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| NP-R1 | route | path differs | Public installs the UI as hub webroot `notepad/index.html` with canonical route `/notepad/`. Internal installs `/etc/nginx/notepad.html` and serves it through the hub's shared top-level `*.html` location as `/notepad.html`. | P: `apps/notepad/airlock-app.toml:27-38`; P: `apps/notepad/install.sh:33-42`; I: `infra/dev-hub/bin/setup-md-notebook.sh:649-652`; I: `infra/dev-hub/bin/setup-md-notebook.sh:1197-1201`; I: `infra/dev-hub/ownership.json:99-102` |
| NP-A1 | API | request differs | Both call the shared publish image/file upload APIs, but public strips the Data URL prefix and sends base64 only in `image`/`data`; internal sends the complete Data URL. | P: `apps/notepad/frontend/notepad.html:181-184`; P: `apps/notepad/frontend/notepad.html:243-254`; P: `apps/notepad/frontend/notepad.html:270-275`; P: `apps/notepad/frontend/notepad.html:296-305`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:175-180`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:222-238` |
| NP-U1 | UI | behavior differs | Public inserts `[imageN]` and `[fileN]`, then replaces recognized tokens with bare server paths when copying. Internal inserts Korean `[이미지N]` and `[파일N]` tokens and preserves each token while appending `(<path>)` to the copied text. | P: `apps/notepad/frontend/notepad.html:186-195`; P: `apps/notepad/frontend/notepad.html:243-264`; P: `apps/notepad/frontend/notepad.html:296-312`; P: `apps/notepad/frontend/notepad.html:401-405`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:144-154`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:175-185`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:195-203`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:231-244`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:329-334` |
| NP-U2 | UI | defaults differ | Public uses one maximum-2,400-pixel JPEG at quality 0.9 for upload and the viewer/drawing source. Internal separately creates an upload JPEG at quality 0.8 and a maximum-2,048-pixel viewer source at quality 0.82. | P: `apps/notepad/frontend/notepad.html:159`; P: `apps/notepad/frontend/notepad.html:198-217`; P: `apps/notepad/frontend/notepad.html:260-264`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:105-108`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:120-137`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:175-185` |
| NP-U3 | UI | public | Before upload, public rejects an encoded image payload over 12 MiB. Internal has no encoded-length preflight in its complete image/file upload frontend. | P: `apps/notepad/frontend/notepad.html:160`; P: `apps/notepad/frontend/notepad.html:243-253`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:98-304`; Z10 |
| NP-U4 | UI | behavior differs | Clearing the page resets public's attachment sequence, so the next file is `[file1]`; internal clears the UI/maps but leaves `fileSeq` running for the rest of that page session. | P: `apps/notepad/frontend/notepad.html:412-420`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:341-347`; Z11 |
| NP-N1 | unit | ownership differs | Public notepad declares no unit and explicitly depends on publish's three `airlock-publish*` user units. Internal packages publish and notepad together under the shared `publish-manager.service` plus cleanup service/timer. | P: `apps/notepad/airlock-app.toml:15-16`; P: `apps/notepad/airlock-app.toml:27-30`; P: `apps/publish/airlock-app.toml:79-85`; I: `infra/dev-hub/ownership.json:87-105`; I: `infra/dev-hub/bin/setup-md-notebook.sh:487-499`; I: `infra/dev-hub/bin/setup-md-notebook.sh:513-534` |
| NP-C1 | config | lifecycle differs | Public declares a `publish` dependency, refuses a broken standalone install, and can independently reclaim only notepad's webroot when disabled. Internal has one publish/notepad package and cannot deactivate only one without source changes. | P: `apps/notepad/airlock-app.toml:15-16`; P: `apps/notepad/install.sh:26-30`; P: `apps/notepad/deactivate.sh:2-8`; I: `infra/dev-hub/ownership.json:87-130` |
| NP-S1 | state | public | Public saves only editor text in `localStorage["airlock.notepad.text"]` and restores it after reload. Internal does not persist editor text in browser storage; upload maps remain session-only on both sides. | P: `apps/notepad/frontend/notepad.html:154-178`; I: `infra/dev-hub/publish-manager/frontend/notepad.html:98-347`; Z9 |

Difference count: **9 entries**.

## orca

Coverage note: internal `orca/web-bundle/` tracks only `VERSION`; the generated
`install-into-box.sh`, slot manager, and nginx slot implementation come from an external
checkout and are absent from the designated tree. The documented local-render/grab routes
and `8500..8515`/`8520..8527` ports are therefore not counted. The base `8446`/`18820`/
`18821` ports and the two-user-unit plus one-system-firewall-unit scope split are equal.

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| OR-N1 | unit | naming differs | Both sides own two user units plus one system firewall unit, but their identities differ: public uses `airlock-orca-xvfb.service`, `airlock-orca.service`, and `airlock-orca-firewall.service`; internal uses the corresponding `<internal>-orca-*` names. | P: `apps/orca/airlock-app.toml:74-90`; I: `infra/dev-hub/orca/bin/install.sh:60-68`; I: `infra/dev-hub/orca/bin/install.sh:169-185` |
| OR-N2 | unit | ordering differs | Public user units order after `network.target`. Internal orders both after `default.target` while also installing them into `default.target`. | P: `apps/orca/render.sh:43-68`; P: `apps/orca/render.sh:77-107`; I: `infra/dev-hub/orca/bin/install.sh:217-237`; I: `infra/dev-hub/orca/bin/install.sh:242-276` |
| OR-N3 | unit | restart behavior differs | Public collapses binary and either-user-unit changes into one flag and restarts Xvfb and Orca together. Internal tracks Xvfb and Orca changes separately, restarting Xvfb only for its own unit/socket conditions and Orca for its own unit/binary/Xvfb conditions. | P: `apps/orca/install.sh:147-178`; P: `apps/orca/install.sh:224-251`; I: `infra/dev-hub/orca/bin/install.sh:312-333` |
| OR-N4 | unit | internal | Internal checks user linger, attempts to enable it when absent, and reports whether reboot persistence is guaranteed. Public's Orca app scope neither enables nor validates linger. | I: `infra/dev-hub/orca/bin/install.sh:375-379`; I: `infra/dev-hub/orca/bin/install.sh:425-429`; Z42 |
| OR-C1 | config | schema/default differs | Public declares the three port defaults and an owner-only audience in the app manifest and consumes platform owner configuration. Internal exposes `ORCA_GATE_PORT`, `ORCA_BACKEND_PORT`, `ORCA_HTTPS_PORT`, and `ORCA_ALLOW`; `ORCA_ALLOW` defaults to `cho@<company-domain>`. The equal numeric defaults are not counted separately. | P: `apps/orca/airlock-app.toml:5-8`; P: `apps/orca/airlock-app.toml:106-108`; P: `apps/orca/install.sh:374-386`; I: `infra/dev-hub/orca/bin/install.sh:15-22`; I: `infra/dev-hub/orca/bin/install.sh:252-262`; Z22 |
| OR-C2 | config | public | Public supports mutation-free `AIRLOCK_DRY_RUN` and redirected `AIRLOCK_RENDER_DIR` emission, including emission of the system firewall ruleset/unit without `sudo`. Internal has no corresponding app-local controls. | P: `apps/orca/install.sh:16-18`; P: `apps/orca/install.sh:86-96`; P: `apps/orca/install.sh:201-218`; P: `apps/orca/install.sh:263-287`; Z23 |
| OR-C3 | config | bundle lifecycle differs | Public commits the patched web-client dist, pins its entry asset, file count, and full-tree hash, and verifies them before serving. Internal tracks a source commit/entry asset in `VERSION` and regenerates an untracked bundle from a separate checkout; auto mode may retain the previous deployed bundle when that checkout is absent, while require mode enforces source HEAD equality. | P: `apps/orca/web-bundle/VERSION:1-18`; P: `apps/orca/bin/verify-web-bundle.sh:22-48`; P: `apps/orca/install.sh:303-313`; I: `infra/dev-hub/orca/README.md:31-42`; I: `infra/dev-hub/orca/bin/refresh-web-bundle.sh:28-65` |
| OR-C4 | config | artifact lifecycle differs | Public records its system-scope firewall unit, rooted firewall ruleset/web tree, and HTTPS serve-port claim in the app manifest, and deactivation delegates their removal to the artifact ledger. Internal's ownership inventory records the unit scopes and serve path, but its Orca deactivation list only stops/disables the firewall unit and does not declare removal of either the system unit file or `/etc/dev-hub/orca-firewall.nft`. | P: `apps/orca/airlock-app.toml:74-90`; P: `apps/orca/deactivate.sh:2-16`; I: `infra/dev-hub/ownership.json:297-327`; I: `infra/dev-hub/orca/bin/install.sh:162-185`; Z24 |
| OR-S1 | state | path differs | AppImage, extracted runtime, and `serve.log` live under `~/.local/share/airlock-orca` publicly versus `~/.local/share/orca` internally. Pairing and reap-helper paths also differ: `airlock-pairing-code`/`airlock-orca-reap` versus `<internal>-pairing-code`/`<internal>-orca-daemon-reap`. | P: `apps/orca/install.sh:80-97`; I: `infra/dev-hub/orca/bin/install.sh:55-68`; I: `infra/dev-hub/orca/bin/install.sh:147-159` |
| OR-S2 | state | internal | A later internal install detects `NeedDaemonReload=yes` or an extracted `AppRun` newer than the active process and forces a recovery restart. Public bases restart only on changes observed in the current invocation or service inactivity. | I: `infra/dev-hub/orca/bin/install.sh:288-310`; I: `infra/dev-hub/orca/bin/install.sh:326-333`; P: `apps/orca/install.sh:147-178`; P: `apps/orca/install.sh:224-251`; Z25 |
| OR-S3 | state | internal | After an install that preserves the live service, internal scans `app-orca-*.scope`, keeps scopes containing a live `--serve` process, and removes only orphan scopes. Public removes all such scopes through `ExecStopPost`; an unchanged install performs no proactive orphan reconciliation. | I: `infra/dev-hub/orca/bin/install.sh:336-362`; P: `apps/orca/render.sh:19-35`; P: `apps/orca/install.sh:244-251`; Z26 |
| OR-S4 | state | rooted path differs | Public writes `/etc/airlock/orca-loopback.nft` and installs its patched client below `${webroot_parent}/orca-web/`, making that serve tree world-readable. Internal writes `/etc/dev-hub/orca-firewall.nft` and maintains a root-owned launcher fragment at `/etc/nginx/devhub-orca-card.html`; further generated canary paths are outside the designated tree and are not claimed. | P: `apps/orca/install.sh:261-287`; P: `apps/orca/install.sh:298-325`; I: `infra/dev-hub/orca/bin/install.sh:66-68`; I: `infra/dev-hub/orca/bin/install.sh:162-185`; I: `infra/dev-hub/orca/bin/install.sh:443-464` |

Difference count: **12 entries**.

## paseo

Coverage note: both sides install the core Paseo server/UI from npm, and that upstream
body is absent from the designated trees. Core upstream API differences are therefore not
claimed; the rows below are limited to app-owned proxy, unit, installer, vendor patches,
and browse-host behavior.

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| PA-R1 | route | activation differs | Public emits `/browse-view/` only when `browse=true`, whose default is false. Internal's gate always exposes the route and the core installer always attempts the bundled sidecar. | P: `apps/paseo/airlock-app.toml:19-24`; P: `apps/paseo/render.sh:244-264`; P: `apps/paseo/install.sh:710-724`; I: `infra/dev-hub/bin/setup-md-notebook.sh:795-808`; I: `infra/dev-hub/paseo/bin/install.sh:484-500` |
| PA-R2 | route | internal | Internal's main Paseo proxy sets `proxy_send_timeout 86400s` and `proxy_buffering off`. Public sets the 86400-second read timeout only, leaving send timeout and response buffering at nginx defaults. | I: `infra/dev-hub/bin/setup-md-notebook.sh:809-824`; P: `apps/paseo/render.sh:157-174`; Z27 |
| PA-U1 | UI | behavior differs | Public's return widget opens the account/subscription menu only when `airlock_panel_url` resolves; otherwise it navigates directly home. Internal always injects `data-menu=1`. | P: `apps/paseo/install.sh:51-60`; P: `apps/paseo/render.sh:169-174`; I: `infra/dev-hub/bin/setup-md-notebook.sh:819-824` |
| PA-N1 | unit | naming differs | Public owns `airlock-paseo.service` and `airlock-paseo-browse-host.service`; internal owns `<internal>-paseo.service` and `<internal>-paseo-browse-host.service`, with corresponding sidecar dependencies/client IDs. | P: `apps/paseo/install.sh:234-244`; P: `apps/paseo/browse-host/install.sh:19-22`; P: `apps/paseo/browse-host/install.sh:204-225`; I: `infra/dev-hub/paseo/bin/install.sh:62-64`; I: `infra/dev-hub/paseo/browse-host/install.sh:14-17`; I: `infra/dev-hub/paseo/browse-host/install.sh:148-169` |
| PA-N2 | unit | public | Public runs a fail-open `ExecStartPre` guard that removes a provably stale or PID-reused `~/.paseo/paseo.pid`, preventing a persistent restart loop after reboot. Internal has no corresponding pre-start guard. | P: `apps/paseo/render.sh:69-82`; P: `apps/paseo/paseo-clear-stale-pid.py:8-35`; P: `apps/paseo/paseo-clear-stale-pid.py:200-228`; I: `infra/dev-hub/paseo/bin/install.sh:315-375`; Z28 |
| PA-N3 | unit | privilege differs | Public defaults to `NoNewPrivileges=yes`, so spawned agent descendants cannot use setuid elevation; a measured snap-node escape hatch renders `NoNewPrivileges=no`. Internal deliberately omits the directive so descendants can use `sudo`. | P: `apps/paseo/install.sh:140-191`; P: `apps/paseo/render.sh:123-131`; I: `infra/dev-hub/paseo/bin/install.sh:367-375` |
| PA-N4 | unit | internal | Internal caps shutdown at 20 seconds before systemd escalates. Public has no `TimeoutStopSec` override and uses the systemd default. | I: `infra/dev-hub/paseo/bin/install.sh:345-354`; P: `apps/paseo/render.sh:82-131`; Z29 |
| PA-N5 | unit | resource policy differs | Public derives `MemoryMax` as box/container memory minus `max(4 GiB, 15%)`, sets `MemoryHigh` to 8/9 of that, refuses undersized boxes unless explicitly rendered unbacked, and has no hostname exceptions. Internal uses 8/12/16-GiB tiers plus fixed per-hostname 46/42-GiB and 36/32-GiB overrides on two named boxes. | P: `apps/paseo/install.sh:71-122`; P: `apps/paseo/render.sh:92-109`; I: `infra/dev-hub/paseo/bin/install.sh:277-314`; I: `infra/dev-hub/paseo/bin/install.sh:355-361` |
| PA-N6 | unit | process policy differs | Public defaults `TasksMax=infinity`, deferring to the enclosing user slice, with an environment override for a finite cap. Internal fixes the unit cap at 24576. | P: `apps/paseo/install.sh:88-92`; P: `apps/paseo/render.sh:110-127`; I: `infra/dev-hub/paseo/bin/install.sh:362-366` |
| PA-N7 | unit | internal | Internal's installer checks and attempts to enable user linger, then reports whether reboot persistence is guaranteed. Public's Paseo app scope neither enables nor validates linger. | I: `infra/dev-hub/paseo/bin/install.sh:389-393`; I: `infra/dev-hub/paseo/bin/install.sh:454-457`; P: `apps/paseo/install.sh:566-608`; Z30 |
| PA-N8 | unit | PATH population differs | Public always puts future npm/provider CLI directories into the unit PATH, even before those directories exist. Internal includes each candidate only if its directory exists at install time, so a provider installed later can remain undiscoverable until reinstall. | P: `apps/paseo/install.sh:214-232`; I: `infra/dev-hub/paseo/bin/install.sh:53-60` |
| PA-N9 | unit | ordering differs | Public orders after `network.target`. Internal orders after `default.target` while also being wanted by `default.target`. | P: `apps/paseo/render.sh:36-49`; P: `apps/paseo/render.sh:130-131`; I: `infra/dev-hub/paseo/bin/install.sh:315-320`; I: `infra/dev-hub/paseo/bin/install.sh:374-375` |
| PA-C1 | config | activation differs | Public exposes `browse` with default false and only then installs browser tools/live panels. Internal always attempts browse-host, which enables `daemon.browserTools.enabled` and normally `daemon.mcp.injectIntoAgents`, broadening the tool catalog exposed to spawned agents. | P: `apps/paseo/airlock-app.toml:19-24`; P: `apps/paseo/install.sh:66-69`; P: `apps/paseo/install.sh:710-739`; I: `infra/dev-hub/paseo/bin/install.sh:484-500`; I: `infra/dev-hub/paseo/browse-host/install.sh:106-145` |
| PA-C2 | config | internal | Internal adds the whole tailnet suffix to `PASEO_HOSTNAMES`, alongside exact FQDN/port and localhost. Public allows the exact FQDN, exact FQDN with configured HTTPS port, and localhost only. | I: `infra/dev-hub/paseo/bin/install.sh:270-275`; I: `infra/dev-hub/paseo/bin/install.sh:329-334`; P: `apps/paseo/render.sh:60-65` |
| PA-C3 | config | internal | Internal removes ambient `OPENAI_API_KEY` both at the systemd boundary and in the Codex spawn overlay, while preserving an explicitly configured runtime key. Public has neither protection in its Paseo app scope. | I: `infra/dev-hub/paseo/bin/install.sh:199-232`; I: `infra/dev-hub/paseo/bin/install.sh:338-342`; I: `infra/dev-hub/paseo/patches/codex-strip-ambient-openai-key.mjs:38-64`; P: `apps/paseo/render.sh:51-82`; Z31 |
| PA-C4 | config | public | When icon-ring branding is configured, public generates and serves a ringed `/favicon.ico` plus ringed copies of Paseo's idle/running/attention favicon variants. The internal Paseo gate/app scope has no corresponding branding transformation. | P: `apps/paseo/install.sh:619-650`; P: `apps/paseo/render.sh:198-232`; I: `infra/dev-hub/bin/setup-md-notebook.sh:785-826`; Z32 |
| PA-C5 | config | schema/default differs | Public declares HTTPS/gate/backend/browse-stream ports, browse activation, version override, and owner-only audience in the app manifest. Internal exposes `PASEO_ALLOW`, three main ports, and `PASEO_VER` as shell inputs, defaults the owner to `cho@<company-domain>`, and has no browse activation/stream-port input in the main installer. The equal numeric main-port defaults are not counted separately. | P: `apps/paseo/airlock-app.toml:19-28`; P: `apps/paseo/airlock-app.toml:124-126`; I: `infra/dev-hub/paseo/bin/install.sh:21-26` |
| PA-C6 | config | sidecar port propagation differs | When browse is enabled, public passes the resolved backend, browse-stream, and HTTPS ports into browse-host and its unit/origin. Internal passes only FQDN; its sidecar fixes those values at 6767, 6768, and 8447 even if the main installer's corresponding ports were overridden. | P: `apps/paseo/install.sh:719-724`; P: `apps/paseo/browse-host/install.sh:24-28`; P: `apps/paseo/browse-host/install.sh:107-115`; P: `apps/paseo/browse-host/install.sh:218-223`; I: `infra/dev-hub/paseo/bin/install.sh:484-500`; I: `infra/dev-hub/paseo/browse-host/install.sh:51-59`; I: `infra/dev-hub/paseo/browse-host/install.sh:162-167` |
| PA-C7 | config | internal | Internal explicitly rejects every architecture except `x86_64` before installation. Public's Paseo app scope has no explicit architecture gate; this row does not claim that every architecture is supported. | I: `infra/dev-hub/paseo/bin/install.sh:28-30`; Z45 |
| PA-S1 | state | public | Public patches Claude and Codex session ownership to retain all spawned handles, reject or kill late spawns after close, and sweep detached process groups whose leaders exited, preventing leaked agents/MCP descendants from surviving session closure. Internal has no guard/group patch. | P: `apps/paseo/install.sh:377-493`; P: `apps/paseo/patches/orphan-process-guard.mjs:7-36`; P: `apps/paseo/patches/orphan-process-group.mjs:137-168`; Z33 |
| PA-S2 | state | public | Public's quota-refresh patch merges refreshed credentials into raw on-disk Claude/Codex JSON, preserving unknown identity, expiry, and token metadata. Internal lacks the patch, so upstream schema-based writeback remains. | P: `apps/paseo/install.sh:495-555`; P: `apps/paseo/patches/credential-key-preservation.mjs:9-37`; P: `apps/paseo/patches/credential-key-preservation.mjs:63-98`; P: `apps/paseo/patches/credential-key-preservation.mjs:100-160`; Z34 |
| PA-S3 | state | internal | Internal treats `NeedDaemonReload=yes` as evidence of a prior partial deployment and forces a recovery restart after daemon-reload. Public restarts only for current-run changes or inactivity, with no corresponding systemd drift check. | I: `infra/dev-hub/paseo/bin/install.sh:379-398`; P: `apps/paseo/install.sh:246-249`; P: `apps/paseo/install.sh:578-592`; Z43 |

Difference count: **22 entries**.

## publish

Coverage note: internal publish-manager calls an external doc-public runtime whose
implementation is absent from the designated tree. Its storage and TTL enforcement are
not compared; only the in-tree client and runtime-negotiation behavior are counted.

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| PB-R1 | route | path differs | Public management UI/shared files use `/publish/` and `/publish/files/`. Internal UI uses `/publish-manager.html`, and its shared-file links target separate HTTP `:8000/<name>`. | P: `apps/publish/airlock-app.toml:87-93`; P: `apps/publish/render.sh:99-114`; I: `infra/dev-hub/bin/setup-md-notebook.sh:1197-1206`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:569-575` |
| PB-R2 | route | public | Public local mode creates `/g/<slug>/...` nginx routes protected by slug-specific htpasswd files. Internal app/runtime installation scope has no local `/g/` gate route. | P: `apps/publish/render.sh:118-133`; P: `apps/publish/install.sh:262-283`; Z35 |
| PB-A1 | API | response differs | On `GET /api/list` and `/api/health`, public list/health expose `public_enabled`, `public_mode`, `gated_enabled`, and a disabled reason. Internal list returns `{ok,items,root}` while health instead reports the publisher/runtime `public_contract`. | P: `apps/publish/backend/airlock-publish.py:1655-1665`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1530-1540`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1954-1969` |
| PB-A2 | API | contract differs | `POST /publish/api/publish-plan` publicly prefers request key `entry`, accepts `name` as a fallback, and is allowed in local mode only; the public UI sends `entry`. Internal uses `name` and plans a remote doc-public bundle. | P: `apps/publish/backend/airlock-publish.py:628-632`; P: `apps/publish/backend/airlock-publish.py:1701-1710`; P: `apps/publish/frontend/publish.html:1045-1056`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1210-1229`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:2014-2025`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:1051-1064` |
| PB-A3 | API | protocol differs | Public remote client uses fixed `X-Airlock-Publish-Token` and rejects remote gated/bundle requests. Internal uses `X-Docpub-Token`, negotiates v0/v1 and mode capabilities through `/health`, preserves v0 behavior, validates v1 results, and revokes mismatched creations. | P: `apps/publish/backend/airlock-publish.py:731-737`; P: `apps/publish/backend/airlock-publish.py:1357-1369`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1471-1527`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1560-1606`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1710-1763` |
| PB-A4 | API | internal | Internal external-publication input requires a ROOT-external symlink target to be a Git-tracked regular file and allows attachments inside an owner-linked directory only under bounded rules. Public follows a top-level symlink HTML target through `os.path.isfile`/`open` without the same provenance checks. | I: `infra/dev-hub/publish-manager/backend/publish-manager.py:142-161`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:164-235`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1422-1430`; P: `apps/publish/backend/airlock-publish.py:229-238`; P: `apps/publish/backend/airlock-publish.py:391-400`; Z37 |
| PB-A5 | API | internal | Internal bundle plan/build derives linked non-HTML attachments and reports `attachments`, `attachment_bytes`, source identity, and digest, with 100-member/64-MiB member/160-MiB total limits. Public bundles HTML documents only, with 60-MiB total and 25-MiB local limits. | I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1143-1149`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1277-1299`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1302-1357`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1380-1455`; P: `apps/publish/backend/airlock-publish.py:76-88`; P: `apps/publish/backend/airlock-publish.py:673-680`; P: `apps/publish/backend/airlock-publish.py:683-719`; Z36 |
| PB-A6 | API | bundling differs | Public single-file bundling replaces local CSS/JS/img references and leaves original tags when reads fail. Internal also handles CSS `url()`, style blocks/attributes, context masking, modules/srcset/source validation, and fails publication when local assets remain unresolved. | P: `apps/publish/backend/airlock-publish.py:367-433`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:550-569`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:970-1072`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1073-1105` |
| PB-A7 | API | conflict handling differs | If external list fails, public remote publish can proceed with a new slug; when multiple entries share a source it reuses the first. Internal aborts on list failure or multiple entries for the same source. | P: `apps/publish/backend/airlock-publish.py:1409-1420`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1553-1557`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1635-1646` |
| PB-A8 | API | public | Public `GET /api/list` items include `isBroken`, computed from dangling-symlink state. Internal list items omit that response field even though its UI consumes it. | P: `apps/publish/backend/airlock-publish.py:168-215`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:46-94`; Z44 |
| PB-U1 | UI | public | Public Publish UI lets a user choose and upload a file up to 50 MiB through `/upload-file`. Internal publish-manager UI has no file-upload action. | P: `apps/publish/frontend/publish.html:225-229`; P: `apps/publish/frontend/publish.html:921-940`; Z39 |
| PB-U2 | UI | internal | Internal UI offers system/light/dark theme controls and persists the choice in `localStorage["markwand-theme"]`. Public Publish UI has no theme-switch action. | I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:253-264`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:478-490`; Z40 |
| PB-U3 | UI | public | Public UI separately filters HTML, image, folder, and file item types. Internal UI filters symlink/direct/broken/public states only. | P: `apps/publish/frontend/publish.html:232-253`; P: `apps/publish/frontend/publish.html:598-609`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:272-293`; Z41 |
| PB-U4 | UI | delete confirmation differs | Public direct-file deletion requires the user to re-enter the matching filename. Internal asks for modal confirmation but fills `confirm_name` automatically. | P: `apps/publish/frontend/publish.html:567-577`; P: `apps/publish/frontend/publish.html:667-674`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:336-349`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:769-779` |
| PB-U5 | UI | public | If external `public-list` is delayed or fails, public marks status unknown and hides or disables publish/revoke actions. Internal exposes no unknown/loading state: an `ok:false` success response resets to an empty map, while network/JSON rejection is silently caught and preserves the prior map. When no prior mapping exists, either path can leave an HTML row offering a new-publication action. | P: `apps/publish/frontend/publish.html:433-486`; P: `apps/publish/frontend/publish.html:522-581`; P: `apps/publish/frontend/publish.html:732-756`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:450-475`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:581-583`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:684-700` |
| PB-U6 | UI | gated availability differs | Public UI enables gated publication on this box in local mode and explicitly disables it in remote mode. Internal enables gated publication when the remote runtime advertises contract v1 with gated mode. | P: `apps/publish/frontend/publish.html:1103-1137`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:435-448`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:940-965` |
| PB-U7 | UI | internal | Internal bundle confirmation shows attachment names/count/total MiB and each document source. Public shows a linked-HTML checklist only. | I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:1077-1116`; P: `apps/publish/frontend/publish.html:1045-1081`; Z36 |
| PB-U8 | UI | behavior differs | Internal's broken filter and repair button depend on `item.isBroken`; because its list API omits that field, the filter produces no rows and the button reports zero without calling repair. Public list supplies the field, and its repair action calls the backend without a client-side zero-count gate. | I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:533-544`; I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:916-922`; P: `apps/publish/frontend/publish.html:907-918`; PB-A8 |
| PB-U9 | UI | internal | Internal refreshes local/public state and visible TTL aging every 30 seconds. Public performs initial and action-triggered loads but has no periodic refresh timer. | I: `infra/dev-hub/publish-manager/frontend/publish-manager.html:1282-1296`; Z46 |
| PB-N1 | unit | naming differs | Public owns `airlock-publish.service`, `airlock-publish-cleanup.service`, and `.timer`; internal owns the corresponding `publish-manager*` names. | P: `apps/publish/airlock-app.toml:69-84`; P: `apps/publish/install.sh:228-246`; I: `infra/dev-hub/bin/setup-md-notebook.sh:487-499`; I: `infra/dev-hub/bin/setup-md-notebook.sh:513-530` |
| PB-N2 | unit | public | Public cleanup oneshot sweeps uploads and also expires/reconciles local public snapshots. Internal cleanup oneshot performs uploads TTL deletion only. | P: `apps/publish/render.sh:48-70`; P: `apps/publish/backend/airlock-publish.py:1292-1302`; P: `apps/publish/backend/airlock-publish.py:1732-1736`; I: `infra/dev-hub/bin/setup-md-notebook.sh:513-530`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:2064-2067` |
| PB-C1 | config | defaults differ | Public share root is configurable as `share_dir`, default `/opt/airlock/share`; backend, upload, and identity paths are injected through environment. Among the corresponding internal local share/upload/identity settings, root is fixed at `~/public_html`, uploads at `~/uploads`, and only the backend port is configurable through `PUBLISH_MANAGER_PORT`. | P: `apps/publish/airlock-app.toml:18-38`; P: `apps/publish/backend/airlock-publish.py:55-59`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:26-34`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1816-1821` |
| PB-C2 | config | public | Public `public_target` explicitly selects `local` or `remote` and configures ingest/base URL, token env name, public/gated/auth directories, and htpasswd binary. Internal reads fixed `DOCPUB_*` and `HTTPSHARE_URL` remote-client settings from `doc-public.env`. | P: `apps/publish/airlock-app.toml:36-38`; P: `apps/publish/install.sh:49-78`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:30-34`; I: `infra/dev-hub/bin/setup-md-notebook.sh:487-499` |
| PB-S1 | state | public | Local-mode publication content, owner/source/expiry, slug-specific htpasswd, and state persist in public/gated slug directories and `~/.local/state/airlock/publish-public.json`. Startup/cleanup reloads state, quarantines corruption, reconciles orphan dirs/transaction backups, and expires entries. Internal app scope has no on-box local-publication state layer. | P: `apps/publish/backend/airlock-publish.py:71-99`; P: `apps/publish/backend/airlock-publish.py:746-768`; P: `apps/publish/backend/airlock-publish.py:828-865`; P: `apps/publish/backend/airlock-publish.py:900-1004`; P: `apps/publish/backend/airlock-publish.py:1292-1320`; Z38 |
| PB-S2 | state | filename differs | For arbitrary upload names, public keeps an ASCII allowlist and falls back to `file`; internal preserves Hangul and falls back to `파일`. | P: `apps/publish/backend/airlock-publish.py:1517-1518`; P: `apps/publish/backend/airlock-publish.py:1585-1588`; P: `apps/publish/backend/airlock-publish.py:1591-1622`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1890-1898`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1901-1931` |
| PB-S3 | state | namespace differs | Clipboard-image auto-save and sequence scan use public `imageNNN-...jpg` versus internal `이미지NNN-...jpg`. | P: `apps/publish/backend/airlock-publish.py:1513-1516`; P: `apps/publish/backend/airlock-publish.py:1538-1581`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1816-1821`; I: `infra/dev-hub/publish-manager/backend/publish-manager.py:1842-1887` |

Difference count: **26 entries**.

## Final total

The nine apps contain **134 evidence-backed difference entries**:

- `devterm`: 14
- `dev-monitor`: 19
- `code-server`: 11
- `feedback`: 7
- `markwand`: 14
- `notepad`: 9
- `orca`: 12
- `paseo`: 22
- `publish`: 26
