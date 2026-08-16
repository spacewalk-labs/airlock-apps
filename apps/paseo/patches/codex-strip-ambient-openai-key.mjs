// SPDX-License-Identifier: AGPL-3.0-only
//
// Idempotent, all-or-nothing patch for Paseo's pinned Codex provider bundle.
// Writes <target>.paseo-new.mjs; the installer syntax-checks and atomically moves it.
// Exit 10 = already applied, 20 = upstream anchors drifted, 0 = candidate written.
import fs from "node:fs";

const F = process.argv[2];
if (!F) {
    console.error("usage: codex-strip-ambient-openai-key.mjs <codex-app-server-agent.js>");
    process.exit(1);
}

const SENTINEL = "[paseo-codex-strip-ambient-openai-key]";
let src;
try { src = fs.readFileSync(F, "utf8"); }
catch (err) { console.error("read failed: " + String(err)); process.exit(1); }

const L = (...lines) => lines.join("\n");
const HELPER_ANCHOR = "export function buildCodexAppServerEnv(runtimeSettings, launchEnv) {";
const FIXED_FUNCTION = L(
    "function paseoAmbientOpenAIKeyOverlay(runtimeSettings) {",
    "    const explicitKey = runtimeSettings?.env?.OPENAI_API_KEY;",
    "    if (typeof explicitKey === \"string\" && explicitKey.trim()) {",
    "        return { OPENAI_API_KEY: explicitKey };",
    "    }",
    "    return { OPENAI_API_KEY: undefined };",
    "}",
);
const HELPER = L(
    "// [paseo-codex-strip-ambient-openai-key] Remove inherited billing credentials at the spawn boundary.",
    "// A non-empty runtimeSettings key is intentional configuration and must survive.",
    FIXED_FUNCTION,
    "",
);
const OLD_SPAWN = L(
    "            ...createProviderEnvSpec({",
    "                runtimeSettings: this.runtimeSettings,",
    "                overlays: [launchEnv],",
    "            }),",
);
const NEW_SPAWN = L(
    "            ...createProviderEnvSpec({",
    "                runtimeSettings: this.runtimeSettings,",
    "                overlays: [launchEnv, paseoAmbientOpenAIKeyOverlay(this.runtimeSettings)],",
    "            }),",
);

const count = (haystack, needle) => haystack.split(needle).length - 1;
if (src.includes(SENTINEL)) {
    const functionStart = src.indexOf("function paseoAmbientOpenAIKeyOverlay(runtimeSettings) {");
    const functionEndMarker = "\n}\n" + HELPER_ANCHOR;
    const functionEnd = src.indexOf(functionEndMarker, functionStart);
    if (count(src, SENTINEL) !== 1 || count(src, NEW_SPAWN) !== 1
        || functionStart < 0 || functionEnd < 0) {
        console.error("inconsistent partial ambient-key patch");
        process.exit(1);
    }
    const installedFunction = src.slice(functionStart, functionEnd + 2);
    if (installedFunction === FIXED_FUNCTION) {
        console.log("ALREADY");
        process.exit(10);
    }
    // The internal predecessor used the same sentinel but returned {}, allowing a
    // later launchEnv key to override the explicit runtime key. Upgrade it in place
    // instead of declaring ALREADY and letting the behaviour check fail forever.
    if (installedFunction.includes("return {};")) {
        const out = src.slice(0, functionStart) + FIXED_FUNCTION + src.slice(functionEnd + 2);
        try { fs.writeFileSync(F + ".paseo-new.mjs", out); }
        catch (err) { console.error("tmp write failed: " + String(err)); process.exit(1); }
        console.log("PATCHED legacy explicit-key precedence");
        process.exit(0);
    }
    console.error("inconsistent ambient-key helper body");
    process.exit(1);
}

const missing = [
    ["helper insertion", HELPER_ANCHOR],
    ["Codex spawn env", OLD_SPAWN],
].filter(([, anchor]) => count(src, anchor) !== 1).map(([name]) => name);
if (missing.length > 0) {
    console.error("SKIP: anchors missing or ambiguous (upstream drift?): " + missing.join(","));
    process.exit(20);
}

let out = src.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR).replace(OLD_SPAWN, NEW_SPAWN);
if (count(out, SENTINEL) !== 1 || count(out, NEW_SPAWN) !== 1) {
    console.error("post-patch invariant failed");
    process.exit(1);
}
try { fs.writeFileSync(F + ".paseo-new.mjs", out); }
catch (err) { console.error("tmp write failed: " + String(err)); process.exit(1); }
console.log("PATCHED");
