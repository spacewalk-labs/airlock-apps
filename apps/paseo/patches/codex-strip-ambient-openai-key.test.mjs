// SPDX-License-Identifier: AGPL-3.0-only
// Behaviour check for the emitted Paseo bundle. All key values are invented.
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const F = process.argv[2];
if (!F) {
    console.error("usage: codex-strip-ambient-openai-key.test.mjs <patched-provider.js>");
    process.exit(1);
}
const src = fs.readFileSync(F, "utf8");
const start = src.indexOf("function paseoAmbientOpenAIKeyOverlay(runtimeSettings) {");
const end = src.indexOf("\n}\nexport function buildCodexAppServerEnv", start);
if (start < 0 || end < 0) {
    console.error("could not extract ambient-key overlay from patched bundle");
    process.exit(1);
}
const helperText = src.slice(start, end + 2);
const overlay = new Function(`${helperText}; return paseoAmbientOpenAIKeyOverlay;`)();
const spawnAnchor = "overlays: [launchEnv, paseoAmbientOpenAIKeyOverlay(this.runtimeSettings)],";
if ((src.split(spawnAnchor).length - 1) !== 1) {
    console.error("patched spawn overlay is absent or ambiguous");
    process.exit(1);
}

// Drive the shipped env composer beside the target bundle; do not duplicate its
// overlay/deletion rules in this test. The synthetic parity fixture supplies the
// same module boundary, while an installed bundle resolves Paseo's real modules.
const targetUrl = pathToFileURL(F);
let createProviderEnvSpec;
let createExternalProcessEnv;
try {
    ({ createProviderEnvSpec } = await import(new URL("../provider-launch-config.js", targetUrl)));
    ({ createExternalProcessEnv } = await import(new URL("../../paseo-env.js", targetUrl)));
}
catch (err) {
    console.error("could not load shipped provider env composition: " + String(err));
    process.exit(1);
}
const compose = ({ ambient = {}, runtimeSettings, launchEnv }) => {
    const spec = createProviderEnvSpec({
        runtimeSettings,
        overlays: [launchEnv, overlay(runtimeSettings)],
    });
    return createExternalProcessEnv(ambient, spec.envOverlay);
};
const cases = [
    ["ambient key is stripped", !Object.hasOwn(compose({
        ambient: { OPENAI_API_KEY: "FAKE-ambient", KEEP: "yes" },
    }), "OPENAI_API_KEY")],
    ["incidental launch overlay is stripped", !Object.hasOwn(compose({
        ambient: {}, launchEnv: { OPENAI_API_KEY: "FAKE-launch" },
    }), "OPENAI_API_KEY")],
    ["blank runtime key is stripped", !Object.hasOwn(compose({
        ambient: { OPENAI_API_KEY: "FAKE-ambient" },
        runtimeSettings: { env: { OPENAI_API_KEY: "  " } },
    }), "OPENAI_API_KEY")],
    ["explicit runtime key survives", compose({
        ambient: { OPENAI_API_KEY: "FAKE-ambient" },
        runtimeSettings: { env: { OPENAI_API_KEY: "FAKE-explicit" } },
    }).OPENAI_API_KEY === "FAKE-explicit"],
    ["explicit runtime key wins over incidental launch key", compose({
        ambient: { OPENAI_API_KEY: "FAKE-ambient" },
        runtimeSettings: { env: { OPENAI_API_KEY: "FAKE-explicit" } },
        launchEnv: { OPENAI_API_KEY: "FAKE-launch" },
    }).OPENAI_API_KEY === "FAKE-explicit"],
    ["unrelated environment survives", compose({
        ambient: { KEEP: "yes", OPENAI_API_KEY: "FAKE-ambient" },
    }).KEEP === "yes"],
];
let failed = 0;
for (const [name, pass] of cases) {
    console.log(`${pass ? "PASS" : "FAIL"}: ${name}`);
    if (!pass) failed += 1;
}
process.exit(failed === 0 ? 0 : 1);
