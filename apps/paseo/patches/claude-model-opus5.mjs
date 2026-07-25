// SPDX-License-Identifier: AGPL-3.0-only
//
// claude-model-opus5 — backport Claude Opus 5 into the pinned paseo model list.
//
// Target: @getpaseo/server .../agent/providers/claude/model-manifest.js
//         (CLAUDE_MODEL_MANIFEST). This edits paseo's own bundle and is therefore
//         a derivative work of paseo — AGPL-3.0-only, see README.md.
//
// Why: paseo's model list is HARDCODED in its dist. The version Airlock pins
//      (0.1.110) shipped before Opus 5 existed, so Opus 5 is simply absent from
//      the web-UI model dropdown — restarting the daemon changes nothing, because
//      the list is compiled into the installed bundle, not discovered at runtime.
//      Upstream added it in 0.2.x; this backports those two entries (200K + 1M)
//      to the pinned build and moves the default from Opus 4.8 to Opus 5.
//
// Who actually runs the model: the Claude Code CLI resolved from the daemon's
//      PATH (paseo spawns it via pathToClaudeCodeExecutable — NOT the SDK's
//      bundled binary). Upstream marks Opus 5 as requiring CLI >= 2.1.219, so
//      ../install.sh gates on the measured CLI version before applying this patch:
//      an older CLI means the patch is skipped and the model never appears
//      (degrade to the old list) rather than appearing and failing at spawn time.
//
// Contract: argv[2] = target model-manifest.js. One stdout line + exit code:
//   exit 10 = already patched (sentinel) -> skip
//   exit 20 = anchor missing (upstream drift, e.g. a paseo that already has
//             Opus 5) -> write nothing, skip (feature degrade, install continues)
//   exit  0 = candidate written to <target>.paseo-new.mjs (install.sh runs
//             `node --check` before mv; the .mjs suffix makes that an ESM check)
//   exit  1 = usage / IO / logic error
// All-or-nothing: both anchors must match, so the list can never gain Opus 5
// while the default stays on Opus 4.8 (or vice versa).
import fs from "node:fs";

const F = process.argv[2];
if (!F) { console.error("usage: claude-model-opus5.mjs <model-manifest.js>"); process.exit(1); }

const SENTINEL = "[airlock-model-opus5]";
let src;
try { src = fs.readFileSync(F, "utf8"); }
catch (err) { console.error("read failed: " + String(err)); process.exit(1); }

if (src.includes(SENTINEL)) { console.log("ALREADY"); process.exit(10); }

const L = (...lines) => lines.join("\n");

// Entries transcribed from upstream 0.2.x, minus fields the pinned build does not
// understand: defaultPriority / minimumClaudeCodeVersion (no gating logic in
// 0.1.110 — install.sh does that check) and supportsThinkingDisabled (no UI).
// effortLevels: xhigh also enables the "Ultra Code" thinking option.
const OLD_HEAD = "export const CLAUDE_MODEL_MANIFEST = [\n";
const NEW_HEAD = L(
    'export const CLAUDE_MODEL_MANIFEST = [',
    '    // [airlock-model-opus5] backported from upstream 0.2.x — absent in the pinned build.',
    '    {',
    '        id: "claude-opus-5[1m]",',
    '        label: "Opus 5 1M",',
    '        description: "Opus 5 with 1M context window",',
    '        contextWindowMaxTokens: 1000000,',
    '        effortLevels: CLAUDE_EFFORT_LEVELS.xhigh,',
    '    },',
    '    {',
    '        id: "claude-opus-5",',
    '        label: "Opus 5",',
    '        description: "Opus 5 · Latest release",',
    '        isDefault: true,',
    '        contextWindowMaxTokens: 200000,',
    '        effortLevels: CLAUDE_EFFORT_LEVELS.xhigh,',
    '    },',
    '',
);

// Exactly one entry may carry isDefault — move it off Opus 4.8 (this mirrors the
// defaultPriority ordering upstream uses once Opus 5 is present).
const OLD_DEFAULT = L(
    '        id: "claude-opus-4-8",',
    '        label: "Opus 4.8",',
    '        description: "Opus 4.8 · Latest release",',
    '        isDefault: true,',
);
const NEW_DEFAULT = L(
    '        id: "claude-opus-4-8",',
    '        label: "Opus 4.8",',
    '        description: "Opus 4.8 · Previous release",',
);

const edits = [
    ["head", OLD_HEAD, NEW_HEAD],
    ["default", OLD_DEFAULT, NEW_DEFAULT],
];

const missing = edits.filter(([, oldStr]) => !src.includes(oldStr)).map(([name]) => name);
if (missing.length > 0) {
    console.error("SKIP: anchor missing (upstream drift?): " + missing.join(","));
    process.exit(20);
}

let out = src;
for (const [name, oldStr, newStr] of edits) {
    const before = out;
    out = out.replace(oldStr, newStr);
    if (out === before) { console.error("replace failed: " + name); process.exit(1); }
}
if (!out.includes(SENTINEL)) { console.error("sentinel absent after apply — logic error"); process.exit(1); }
// Count only array entries (8-space indent). getClaudeManifestModels() spreads the
// same literal (`...("isDefault" in model ...`), so a plain substring count overcounts.
const defaults = (out.match(/^ {8}isDefault: true,$/gm) ?? []).length;
if (defaults !== 1) { console.error(`isDefault count after apply = ${defaults} (want 1)`); process.exit(1); }

try { fs.writeFileSync(F + ".paseo-new.mjs", out); }
catch (err) { console.error("tmp write failed: " + String(err)); process.exit(1); }
console.log("PATCHED");
process.exit(0);
