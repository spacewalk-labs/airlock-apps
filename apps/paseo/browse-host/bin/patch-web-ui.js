#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-only
"use strict";
// Deterministic, fail-loud web-ui bundle patcher for Level 2 (task doc §14.3).
//
// Usage: node bin/patch-web-ui.js <web-ui-dir> <companion-js-path>
//
// Applies THREE minimal, verified-unique edits to the pinned paseo web-ui bundle
// so the self-hosted web runtime can open live browser panels:
//   1+2. un-gate the "New browser" button callbacks (vo/Wo) on web;
//   3.   mark the BrowserPane container with data-paseo-* so the companion mounts.
// Then injects the companion <script> into index.html and installs the companion.
//
// Fail-loud (the depth4 patch was warn-only; §14.2 requires the opposite): if the
// bundle SHA does not match the pin AND the bundle is not already patched, we
// REFUSE (exit 1) rather than run an unpatched/half-patched build. On a
// @getpaseo/cli version bump the SHA changes -> this fails -> a human re-derives
// the anchors using the coordinates in task doc §14.3.

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

// SHA-256 of the ORIGINAL (unpatched) bundle we derived anchors against.
const PINNED_SHA = "719b916584eb2258b2454ed97de0fb40c50bf38b542acc49d0fd3ea3ad71a9d0";
const PINNED_VERSION = "@getpaseo/cli@0.1.110 (index-8cd48fdd)";

// Each anchor MUST occur exactly once in the pinned bundle (verified).
const PATCHES = [
  {
    name: "new-browser-gate-vo",
    find: 'if(!ze||!(0,Re.getIsElectron)())return;e?.paneId&&qe(ze,e.paneId);const{browserId:t}=(0,ie.createWorkspaceBrowser)()',
    repl: 'if(!ze)return;e?.paneId&&qe(ze,e.paneId);const{browserId:t}=(0,ie.createWorkspaceBrowser)()',
  },
  {
    name: "new-browser-gate-Wo",
    find: 'if(!ze||!(0,Re.getIsElectron)())return;const{browserId:t}=(0,ie.createWorkspaceBrowser)({initialUrl:e})',
    repl: 'if(!ze)return;const{browserId:t}=(0,ie.createWorkspaceBrowser)({initialUrl:e})',
  },
  {
    name: "browserpane-marker",
    find: '{style:u.container,children:[S,_,I]})',
    repl: '{style:u.container,dataSet:{paseoBrowserId:w,paseoWorkspaceId:f.workspaceId,paseoServerId:f.serverId},children:[S,_,I]})',
  },
];
const PATCHED_MARKER = "dataSet:{paseoBrowserId:";
const SCRIPT_TAG = '<script src="/browse-view-client.js" defer></script>';

function die(msg) {
  console.error("[patch-web-ui] FATAL: " + msg);
  process.exit(1);
}
function log(msg) { console.log("[patch-web-ui] " + msg); }

function occurrences(hay, needle) {
  let n = 0, i = 0;
  for (;;) {
    const j = hay.indexOf(needle, i);
    if (j < 0) break;
    n++; i = j + needle.length;
  }
  return n;
}

function removeSiblings(file) {
  for (const ext of [".br", ".gz"]) {
    try { fs.rmSync(file + ext, { force: true }); } catch {}
  }
}

function findBundle(webuiDir) {
  const dir = path.join(webuiDir, "_expo", "static", "js", "web");
  // Prefer the bundle index.html actually references. This is robust to a
  // half-done cache-bust rename (old + new bundle can briefly coexist after a
  // crash): index.html is the single source of truth for what is served.
  try {
    const html = fs.readFileSync(path.join(webuiDir, "index.html"), "utf8");
    const m = html.match(/index-[0-9a-f]+\.js/);
    if (m && fs.existsSync(path.join(dir, m[0]))) return path.join(dir, m[0]);
  } catch {}
  let files = [];
  try { files = fs.readdirSync(dir); } catch { die(`web-ui js dir not found: ${dir}`); }
  const idx = files.filter((f) => /^index-[0-9a-f]+\.js$/.test(f));
  if (idx.length !== 1) die(`cannot resolve web-ui bundle: index.html references none on disk and found ${idx.length} index-*.js in ${dir}`);
  return path.join(dir, idx[0]);
}

// The patched bundle's cache-busting filename = index-<md5(patched)>.js. Expo
// serves it `immutable, max-age=1yr`, so the URL MUST change when content does.
function patchedName(src) {
  return "index-" + crypto.createHash("md5").update(src).digest("hex") + ".js";
}

// Patch the bundle AND cache-bust it. Expo serves index-<hash>.js as
// `immutable, max-age=1yr`; patching in place keeps the same URL, so browsers
// that cached the pre-patch bundle serve STALE bytes forever (dead "New browser"
// button — observed live 2026-07-22). We write the patched bytes under a NEW
// content-hash filename. Crash-safety (adversarial review P1): we WRITE the new
// bundle but keep the old one — the caller repoints index.html FIRST, then
// cleanupOldBundles() removes stragglers. So at every crash point index.html
// still references a bundle that exists on disk, and a re-run self-heals
// (findBundle keys off index.html). Returns {filename, oldFilename}.
function patchBundle(bundlePath) {
  const dir = path.dirname(bundlePath);
  const curName = path.basename(bundlePath);
  let src = fs.readFileSync(bundlePath, "utf8");

  if (src.includes(PATCHED_MARKER)) {
    for (const p of PATCHES) {
      if (!src.includes(p.repl)) die(`bundle half-patched: ${p.name} replacement missing — restore from a clean install`);
    }
    // Already patched. Migrate a bundle patched in place under the ORIGINAL name
    // to its content-hash name so immutable-cached clients stop getting stale bytes.
    const want = patchedName(src);
    if (curName === want) { log("bundle already patched + cache-busted (idempotent) ✓"); return { filename: curName, oldFilename: curName }; }
    fs.writeFileSync(path.join(dir, want), src); // keep curName until index.html is repointed
    removeSiblings(path.join(dir, want));
    log(`bundle already patched → cache-busting rename ✓ ${curName} → ${want}`);
    return { filename: want, oldFilename: curName };
  }

  const sha = crypto.createHash("sha256").update(src).digest("hex");
  if (sha !== PINNED_SHA) {
    die(`bundle SHA mismatch — got ${sha}, pinned ${PINNED_SHA} (${PINNED_VERSION}).\n` +
        `  The @getpaseo/cli web-ui bundle changed. Re-derive the 3 anchors using task doc §14.3 coordinates, ` +
        `update PINNED_SHA/PATCHES, then re-run. Refusing to run an unpatched build.`);
  }
  for (const p of PATCHES) {
    const c = occurrences(src, p.find);
    if (c !== 1) die(`anchor ${p.name} found ${c}× (expected exactly 1) — refusing`);
  }
  for (const p of PATCHES) src = src.replace(p.find, p.repl);
  for (const p of PATCHES) {
    if (occurrences(src, p.find) !== 0) die(`post-patch: original anchor ${p.name} still present`);
    if (!src.includes(p.repl)) die(`post-patch: replacement ${p.name} not applied`);
  }
  const newName = patchedName(src);
  fs.writeFileSync(path.join(dir, newName), src); // keep curName until index.html is repointed
  removeSiblings(path.join(dir, newName));         // no stale compressed siblings for the new bundle
  log(`bundle patched (${PATCHES.length} edits) + cache-busted ✓ ${curName} → ${newName}`);
  return { filename: newName, oldFilename: curName };
}

// Repoint index.html's bundle reference to the cache-busted filename. index.html
// is served no-cache, so this is what makes every client re-fetch the new URL.
function updateBundleRef(webuiDir, oldFilename, newFilename) {
  if (oldFilename === newFilename) return;
  const htmlPath = path.join(webuiDir, "index.html");
  let html = fs.readFileSync(htmlPath, "utf8");
  if (!html.includes(oldFilename)) {
    if (html.includes(newFilename)) { log("index.html bundle ref already cache-busted ✓"); return; }
    die(`index.html references neither ${oldFilename} nor ${newFilename} — cannot repoint bundle`);
  }
  html = html.split(oldFilename).join(newFilename);
  fs.writeFileSync(htmlPath, html);
  removeSiblings(htmlPath);
  log(`index.html bundle ref cache-busted ✓ ${oldFilename} → ${newFilename}`);
}

// Remove every index-*.js (and compressed siblings) that is NOT the served
// bundle. Runs AFTER index.html is repointed, so deleting the old bundle can
// never leave index.html pointing at a missing file. Idempotent.
function cleanupOldBundles(webuiDir, keepFilename) {
  const dir = path.join(webuiDir, "_expo", "static", "js", "web");
  let files = [];
  try { files = fs.readdirSync(dir); } catch { return; }
  for (const f of files) {
    if (/^index-[0-9a-f]+\.js$/.test(f) && f !== keepFilename) {
      try { fs.rmSync(path.join(dir, f), { force: true }); } catch {}
      removeSiblings(path.join(dir, f));
      log(`removed stale bundle ${f}`);
    }
  }
}

function injectHtml(webuiDir) {
  const htmlPath = path.join(webuiDir, "index.html");
  let html;
  try { html = fs.readFileSync(htmlPath, "utf8"); } catch { die(`index.html not found: ${htmlPath}`); }
  if (html.includes(SCRIPT_TAG)) { log("index.html already injected (idempotent) ✓"); return; }
  if (!html.includes("</body>")) die("index.html has no </body> to inject before");
  html = html.replace("</body>", "  " + SCRIPT_TAG + "\n</body>");
  fs.writeFileSync(htmlPath, html);
  removeSiblings(htmlPath); // force plaintext serve so the <script> takes effect
  log("index.html companion <script> injected ✓");
}

function installCompanion(webuiDir, companionPath) {
  if (!fs.existsSync(companionPath)) die(`companion js not found: ${companionPath}`);
  const dest = path.join(webuiDir, "browse-view-client.js");
  fs.copyFileSync(companionPath, dest);
  removeSiblings(dest);
  log("companion browse-view-client.js installed ✓");
}

function main() {
  const webuiDir = process.argv[2];
  const companionPath = process.argv[3];
  if (!webuiDir || !companionPath) die("usage: patch-web-ui.js <web-ui-dir> <companion-js-path>");
  if (!fs.existsSync(webuiDir)) die(`web-ui dir not found: ${webuiDir}`);
  const bundlePath = findBundle(webuiDir);
  const { filename, oldFilename } = patchBundle(bundlePath);
  updateBundleRef(webuiDir, oldFilename, filename); // repoint FIRST (index.html is no-cache)
  cleanupOldBundles(webuiDir, filename);            // THEN drop the old bundle — never orphan index.html
  injectHtml(webuiDir);
  installCompanion(webuiDir, companionPath);
  log("done.");
}

main();
