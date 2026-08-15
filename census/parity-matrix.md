# Public ↔ internal app behavior parity matrix

Status: format sample — `devterm`, `dev-monitor`, `code-server` only (3/9 apps)

This census records observable or operational differences only. It does not decide
`keep`, `drop`, or `migrate`, and it does not add contracts or tests.

Inputs inspected:

- Public: `893c4da58f9aecb3d25fd085bbbfd57aeb4518d2`
- Internal: `3ced9d54ceb03b118b2961bf3938252f5f397431`

## Method and evidence convention

- `P:` means the public tree rooted at this repository.
- `I:` means the read-only internal tree rooted at `/home/josh/workspace/swk-devhub`.
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
  `rg -n 'codex-usage\.json|CODEX_USAGE_STATE|_codex_usage_state_(load|save)' /home/josh/workspace/swk-devhub/infra/dev-hub/devterm`

- Z3 — internal dev-monitor token config, units, and state:
  `rg -n 'token[_ -]?fresh|TOKEN_FRESH|token-freshness\.json' /home/josh/workspace/swk-devhub/infra/dev-hub/dev-monitor /home/josh/workspace/swk-devhub/infra/dev-hub/bin/setup-md-notebook.sh`

- Z4 — public dev-monitor system firewall unit:
  `rg -n 'devmon-spool-fw|DEVMON_FW|meta skuid|nft (add|list).*devmon|iptables' apps/dev-monitor`

- Z5 — public dev-monitor skill membership setting:
  `rg -n 'DEV_MONITOR_SKILL_ALLOW|SKILL_ALLOW|allowed_skills' apps/dev-monitor`

- Z6 — public code-server default theme/extension seeding:
  `rg -n 'One Dark Pro|colorTheme|extensions\.json|--install-extension|install-extension' apps/code-server`

- Z7 — public code-server legacy-copy implementation:
  `rg -n 'OLD_UDD|OLD_EXT|cp -an' apps/code-server`

## devterm

| ID | Axis | Only/different on | Behavior difference | Evidence |
|---|---|---|---|---|
| DT-R1 | route | public | Plain HTTP `:9900` is redirect-only: the public manifest maps `public_port` to a separate redirect listener, requests an HTTPS redirect from the platform renderer, and its smoke contract requires 301 plus an HTTPS location. Internal maps `:9900` directly to the owner gate, so the terminal application is served over HTTP as well as HTTPS. | P: `apps/devterm/airlock-app.toml:101-102`; P: `apps/devterm/render.sh:62-68`; P: `apps/devterm/smoke.sh:34-36`; P: `apps/devterm/smoke.sh:65-69`; I: `infra/dev-hub/devterm/bin/install.sh:126-140` |
| DT-R2 | route | internal | `/keytest.html` is an intentional Hangul/input diagnostic page in the internal web root. The public web-root inventory has no corresponding page. | I: `infra/dev-hub/devterm/web/keytest.html:1-6`; P: `apps/devterm/install.sh:147-159`; Z1 |
| DT-A1 | API | internal | `GET /claude-status`, `/claude-usage`, `/claude-usage-store`, and `/codex-usage` admit any authenticated `@spacewalk.tech` identity. Public re-checks every route against the owner allow-list, so these four fleet-readable responses are owner-only there. | I: `infra/dev-hub/devterm/backend/devterm-gate.py:216-220`; I: `infra/dev-hub/devterm/backend/devterm-gate.py:2395-2405`; P: `apps/devterm/backend/devterm-gate.py:2465-2475` |
| DT-A2 | API | internal | A wrong method on `/secret-put`, `/secret-list`, or `/secret-del` returns JSON `405 method not allowed`. Public only dispatches the allowed method and otherwise falls through to static handling, so the same wrong-method request does not have the internal 405 contract. | I: `infra/dev-hub/devterm/backend/devterm-gate.py:2410-2424`; P: `apps/devterm/backend/devterm-gate.py:2518-2523`; P: `apps/devterm/backend/devterm-gate.py:2550-2551` |
| DT-C4 | config | internal | The terminal waits for bundled D2Coding regular/bold fonts and uses D2Coding as its first terminal font. Public uses the platform monospace stack and bundles no D2Coding font files. | I: `infra/dev-hub/devterm/web/index.html:52-57`; I: `infra/dev-hub/devterm/web/app.js:18-24`; I: `infra/dev-hub/devterm/web/app.js:121`; P: `apps/devterm/web/app.js:122`; P: `apps/devterm/install.sh:152-158`; Z1 |
| DT-U2 | UI | internal by default | Internal always renders the account-switch action and installs the status probe; public renders that action only when `accounts=true`, defaults it off, and installs/wires the account tools only when enabled. Both sides deploy the account UI assets, so asset presence is not counted as a difference. | I: `infra/dev-hub/devterm/web/app.js:810-823`; I: `infra/dev-hub/devterm/bin/install.sh:54-67`; P: `apps/devterm/web/app.js:20-22`; P: `apps/devterm/web/app.js:795-803`; P: `apps/devterm/airlock-app.toml:14-19`; P: `apps/devterm/install.sh:131-158` |
| DT-N1 | unit | public | The public gate unit uses `KillMode=process`, explicitly allowing a detached `codex login --device-auth` process to survive a gate redeploy. The internal gate unit has no `KillMode` override, although its ttyd unit does. | P: `apps/devterm/render.sh:46-55`; I: `infra/dev-hub/devterm/bin/install.sh:69-110` |
| DT-N2 | unit | public | Public installation restarts ttyd and gate only when rendered content changed or a unit is inactive. Internal installation unconditionally restarts ttyd and then the gate on every run. | P: `apps/devterm/install.sh:168-186`; P: `apps/devterm/install.sh:253-263`; I: `infra/dev-hub/devterm/bin/install.sh:113-118` |
| DT-N3 | unit | naming differs | Public owns `airlock-devterm.service` and `airlock-devterm-gate.service`; internal owns `swk-devterm-ttyd.service` and `swk-devterm-gate.service`. The ttyd role therefore changes unit identity across trees. | P: `apps/devterm/airlock-app.toml:90-95`; I: `infra/dev-hub/devterm/bin/install.sh:69-110` |
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
| DM-U2 | UI | internal | The services table exposes restart buttons for user services, and the log selector covers markserv, filebrowser, publish-manager, and dev-monitor. Public exposes no restart control and offers only `airlock-dev-monitor` in the log selector. | I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:375`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:557-563`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:644-658`; P: `apps/dev-monitor/frontend/dev-monitor.html:367` |
| DM-U3 | UI | public | A Credentials card displays token expiry/staleness and last-check state. Internal has no Credentials section between Host and CPU. | P: `apps/dev-monitor/frontend/dev-monitor.html:316-321`; P: `apps/dev-monitor/frontend/dev-monitor.html:629-664`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:309-327` |
| DM-U4 | UI | public | Completed-run detail includes “Keep window”; internal detail has stop/view/close but no retention exemption action. | P: `apps/dev-monitor/frontend/dev-monitor.html:394-397`; P: `apps/dev-monitor/frontend/dev-monitor.html:1166-1173`; I: `infra/dev-hub/dev-monitor/frontend/dev-monitor.html:406-408` |
| DM-N1 | unit | public | Public can install three additional user units for credential monitoring: a oneshot checker, an `OnFailure` alarm, and a persistent randomized timer. Internal setup creates no equivalent credential-check units. | P: `apps/dev-monitor/systemd/airlock-token-freshness.service.in:1-29`; P: `apps/dev-monitor/systemd/airlock-token-freshness-failed.service.in:1-10`; P: `apps/dev-monitor/systemd/airlock-token-freshness.timer.in:1-16`; P: `apps/dev-monitor/install-token-timer.sh:55-56`; P: `apps/dev-monitor/install-token-timer.sh:130-150`; Z3 |
| DM-N2 | unit | naming differs | Public owns `airlock-dev-monitor.service`; internal owns `dev-monitor.service`. | P: `apps/dev-monitor/airlock-app.toml:60-69`; I: `infra/dev-hub/bin/setup-md-notebook.sh:500-512` |
| DM-N3 | unit | internal | Internal conditionally owns a system-level `devmon-spool-fw.service` that blocks the low-trust spool UID from all loopback traffic, and disables the message/action feature if that firewall cannot be proven. Public's app package declares only its main user unit and creates a user-owned 0700 spool, with no matching system firewall unit. | I: `infra/dev-hub/bin/setup-md-notebook.sh:375-432`; P: `apps/dev-monitor/airlock-app.toml:60-69`; P: `apps/dev-monitor/install.sh:103-121`; Z4 |
| DM-C1 | config | public | Token monitoring is explicitly configurable with `token_freshness`, warning hours, and stale hours; it defaults off. Internal has no corresponding settings. | P: `apps/dev-monitor/airlock-app.toml:19-29`; P: `apps/dev-monitor/render.sh:25-34`; Z3 |
| DM-C2 | config | internal | `DEV_MONITOR_SKILL_ALLOW` can restrict executable skill names and participates in plan validation. Public validates skill syntax without a membership knob. | I: `infra/dev-hub/dev-monitor/backend/dev-monitor.py:1095-1100`; I: `infra/dev-hub/dev-monitor/backend/devmon_messages.py:616-625`; P: `apps/dev-monitor/airlock-app.toml:13-29`; P: `apps/dev-monitor/backend/devmon_messages.py:712-764`; P: `apps/dev-monitor/backend/airlock-dev-monitor.py:1314-1333`; Z5 |
| DM-C3 | config | deployment differs | Public exposes `messages` as an app setting on any installed box. Internal setup enables the message/action console only when the hostname is exactly `josh-dev` and its firewall precondition passes. | P: `apps/dev-monitor/airlock-app.toml:13-18`; P: `apps/dev-monitor/install.sh:88-117`; I: `infra/dev-hub/bin/setup-md-notebook.sh:362-365`; I: `infra/dev-hub/bin/setup-md-notebook.sh:443-485` |
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
| CS-N1 | unit | naming differs | Public manager controls `airlock-code-server@N.service` and owns `airlock-code-server-manager.service`; internal controls `swk-codeserver@N.service` and owns `swk-codeserver-manager.service`. | P: `apps/code-server/manager/manager.py:51-64`; P: `apps/code-server/airlock-app.toml:106-114`; I: `infra/dev-hub/code-server/manager/manager.py:164-212`; I: `infra/dev-hub/code-server/bin/install.sh:36-40` |
| CS-N2 | unit | public | The public manager unit orders after `network.target`. Internal orders after `default.target` while also being wanted by `default.target`; public comments identify this as the ordering-cycle pattern it avoids. | P: `apps/code-server/render.sh:41-47`; P: `apps/code-server/render.sh:66-68`; I: `infra/dev-hub/code-server/bin/install.sh:161-181` |
| CS-N3 | unit | public | Reinstall restarts manager and slot 1 only when installed content changed; otherwise it only starts them if needed. Internal always restarts both on every install. | P: `apps/code-server/install.sh:95-117`; P: `apps/code-server/install.sh:136-146`; I: `infra/dev-hub/code-server/bin/install.sh:188-200` |
| CS-C1 | config | public | `https_port`, `gate_port`, `backend_port`, `manager_port`, and `slots` are app config with defaults. Internal exposes only owner/gate/HTTPS as shell inputs while manager port, backend slot ports, and slot count remain fixed in code/unit templates. | P: `apps/code-server/airlock-app.toml:13-26`; I: `infra/dev-hub/code-server/bin/install.sh:12-16`; I: `infra/dev-hub/code-server/manager/manager.py:10-18` |
| CS-C2 | config | public | The identity header name is platform-configured, injected into the manager unit, and the manager fails closed if it is absent. Internal hardcodes `tailscale-user-login` and defaults the allowed login to `cho@spacewalk.tech`. | P: `apps/code-server/render.sh:37-56`; P: `apps/code-server/manager/manager.py:41-49`; I: `infra/dev-hub/code-server/manager/manager.py:15-18` |
| CS-C3 | config | public | Pinned binaries support both amd64 and arm64. Internal rejects arm64 and supports only the pinned amd64 asset. | P: `apps/code-server/install.sh:56-63`; I: `infra/dev-hub/code-server/bin/install.sh:17-29` |
| CS-S1 | state | path differs | Public slot user data/extensions live at `~/.local/share/airlock-code-server/{slots/N,extensions}` and tab prefs at `~/.config/airlock-code-server/tabs.json`. Internal uses `~/.local/share/code-server-slots/{N,extensions}` and `~/.config/code-server-tabs/tabs.json`. | P: `apps/code-server/bin/airlock-code-server-slot:22-26`; P: `apps/code-server/manager/manager.py:51-52`; P: `apps/code-server/manager/manager.py:197-204`; I: `infra/dev-hub/code-server/bin/install.sh:15`; I: `infra/dev-hub/code-server/manager/manager.py:15-18` |
| CS-S2 | state | internal | Internal performs a one-time migration from the legacy single-instance `~/.local/share/code-server` into slot 1/shared extensions. Public explicitly treats installation as greenfield and has no legacy-copy implementation in its app-owned scope. | I: `infra/dev-hub/code-server/bin/install.sh:99-110`; P: `apps/code-server/install.sh:8-13`; Z7 |

Sample count: **11 difference entries**.

## Sample total

The first three apps contain **44 evidence-backed difference entries**:

- `devterm`: 14
- `dev-monitor`: 19
- `code-server`: 11

The remaining six apps are intentionally not yet inventoried. This is the requested
format checkpoint before expanding the census.
