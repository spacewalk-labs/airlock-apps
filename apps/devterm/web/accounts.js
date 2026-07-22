'use strict';
/*
 * devterm account pool — split out of app.js. Optional feature (the account icon is
 *   only shown when the accounts feature is enabled). Switch / usage / pool-login UI.
 *   Coupling to the terminal core is only the injected functions below (no core vars).
 * DI factory: window.initAccounts(deps) is the only global. deps =
 *   { flash, postJson, mkFocus, closeTabPops, placePop }; returns 4 API functions.
 * Load order: before app.js in index.html; app.js calls this factory while running.
 */
window.initAccounts = function initAccounts(deps) {
  const flash = deps.flash, postJson = deps.postJson, mkFocus = deps.mkFocus,
        closeTabPops = deps.closeTabPops, placePop = deps.placePop;

// ---- Claude account switch (claude-switch) — click the top square icon ----
// usage color rule: 5h and 7d have different thresholds; the row color is the worse of the two (OR).
//   5h  >=85 amber · >=92 red · **100 = grey (locked feel — not red)**
//   7d  >=92 amber · >=96 red
const C_GRAY = '#8a92a6', C_GREEN = '#7bd88f', C_AMBER = '#e6b34d', C_RED = '#e05a5a';

function usageLevel(kind, p) {   // 0=ok 1=warn 2=critical
  if (p == null) return 0;
  return kind === '5h' ? (p >= 92 ? 2 : p >= 85 ? 1 : 0)
                       : (p >= 96 ? 2 : p >= 92 ? 1 : 0);
}
function levelColor(lv) { return lv === 2 ? C_RED : lv === 1 ? C_AMBER : C_GREEN; }

// row color = OR (the worse of the two). 5h full wins as grey (can't use it now anyway).
function usageColor(u5, u7) {
  if (u5 != null && u5 >= 100) return C_GRAY;
  return levelColor(Math.max(usageLevel('5h', u5), usageLevel('7d', u7)));
}

// reset-time formatting — like a statusline (5h = time only / 7d = date + time). ISO(UTC) -> local.
function fmtReset(iso, withDate) {
  if (!iso) return '?';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '?';
  const p = n => String(n).padStart(2, '0');
  const hm = p(d.getHours()) + ':' + p(d.getMinutes());
  return withDate ? p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + hm : hm;
}

// hover tip text — two lines like a statusline. Unused (0%) window has resets_at=null -> '—'.
// A refreshToken expiry does NOT slide — it is fixed at login (~30 days) and does not
// refresh. So even a daily-use account dies at ~30 days. Warn ahead of time by days left.
const RT_WARN_DAYS = 5;
function rtLeft(a) {   // days left (fractional) · null if unknown
  return a && a.rtExpiry ? (a.rtExpiry - Date.now()) / 86400000 : null;
}
function rtWarnText(d) {
  if (d <= 0) return '⚠ Expired · re-login';
  if (d < 1) return '⚠ Expires today · re-login';
  return '⚠ Expires in ' + Math.floor(d) + ' days · re-login';
}
function acctTipText(u, a) {
  const L = [];
  if (u.use5h == null && u.use7d == null) {
    L.push(u.err === 'no data' ? 'Collecting usage\n(every minute)' : 'Query failed\n' + (u.err || '?'));
  } else {
    L.push('5h↻ ' + (u.reset5h ? fmtReset(u.reset5h, false) : '—') +
           '\n7d↺ ' + (u.reset7d ? fmtReset(u.reset7d, true) : '—') +
           (u.stale ? '\n(last value)' : ''));
  }
  // who holds it = the shared store's holders. Using the same account in two places burns 5h twice as fast.
  const h = (a && a.holders) || [];
  if (h.length) L.push('In use by\n' + h.map(function (x) { return '· ' + x.who; }).join('\n'));
  const d = rtLeft(a);
  if (d != null) {
    L.push(d <= RT_WARN_DAYS
      ? rtWarnText(d) + '\n(expiry is fixed ~30 days after login —\n it does not extend with use)'
      : 'Login expires in ' + Math.floor(d) + ' days');
  }
  return L.join('\n\n');
}

// If the active account is warn/critical, the top / key-bar Claude icon itself signals it (amber = mild / red = clear).
// 5h full (grey = locked) does not warn — it was already red before locking.
let _acctIconCls = '', _acctIconTimer = null;
function applyAcctIconCls() {
  document.querySelectorAll('[aria-label*="Switch account"]').forEach(function (b) {
    b.classList.toggle('acct-warn', _acctIconCls === 'acct-warn');
    b.classList.toggle('acct-crit', _acctIconCls === 'acct-crit');
  });
}
function refreshAcctIcon() {
  fetch('/accounts').then(function (x) { return x.json(); }).then(function (j) {
    const a = ((j && j.accounts) || []).filter(function (x) { return x.active; })[0];
    const u = (a && a.usage) || {};
    let cls = '';
    if (u.use5h != null || u.use7d != null) {
      const c = usageColor(u.use5h, u.use7d);
      cls = c === C_RED ? 'acct-crit' : c === C_AMBER ? 'acct-warn' : '';
    }
    // active account login expiring soon = warn regardless of usage (else it dies out of nowhere).
    const d = rtLeft(a);
    if (d != null && d <= RT_WARN_DAYS && cls !== 'acct-crit') cls = 'acct-warn';
    _acctIconCls = cls; applyAcctIconCls();
  }).catch(function () {});
}
function startAcctIconWatch() {
  if (_acctIconTimer) return;
  refreshAcctIcon();
  _acctIconTimer = setInterval(refreshAcctIcon, 60000);   // matches the background collection cadence (1 min)
}

// show next to the cursor immediately (native title has ~1s delay + tiny text).
let _acctTipEl = null;
function hideAcctTip() { if (_acctTipEl) { _acctTipEl.remove(); _acctTipEl = null; } }
function placeAcctTip(e) {
  if (!_acctTipEl) return;
  const el = _acctTipEl, pad = 14;
  const x = Math.min(e.clientX + pad, window.innerWidth - el.offsetWidth - 6);
  const y = Math.min(e.clientY + pad, (window.visualViewport ? window.visualViewport.height : window.innerHeight) - el.offsetHeight - 6);   // above the keyboard (visual viewport)
  el.style.left = Math.max(6, x) + 'px';
  el.style.top = Math.max(6, y) + 'px';
}
function showAcctTip(e, u, a) {
  hideAcctTip();
  const el = document.createElement('div'); el.className = 'acct-tip';
  el.textContent = acctTipText(u, a);
  document.body.appendChild(el);   // must attach before measuring
  _acctTipEl = el;
  placeAcctTip(e);
}

// Load the pool from the backend (/accounts) into a popup (left = account, right = 5h/7d usage).
// Selecting one runs `claude-switch swap <name>` server-side. No secrets (plan, health, usage% only).
// Add account = completed inside the popup: the backend runs login-url/login-code; the human just
// approves the link and pastes the returned code.
function startAddAcct(list, addBtn, reflow) {
  postJson('/acct-login-url', {}).then(function (res) {
    if (!res || !res.ok || !res.url) {
      addBtn.disabled = false; addBtn.textContent = '+ Add account (login)';
      flash('Failed to issue login link' + (res && res.error ? ': ' + res.error : ''), 3000); return;
    }
    addBtn.remove();
    const hd = document.createElement('div'); hd.className = 'hd';
    hd.textContent = '(1) Approve the link -> (2) paste the code';
    const a = document.createElement('a'); a.className = 'acct-link';
    a.href = res.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.textContent = '🔗 Open in browser to log in / approve';
    const form = document.createElement('div'); form.className = 'addform';
    const inp = document.createElement('input');
    inp.type = 'text'; inp.placeholder = 'Code from the approval'; inp.autocomplete = 'off'; inp.spellcheck = false;
    const go = document.createElement('button'); go.textContent = 'Register';
    const submit = function () {
      const code = inp.value.trim();
      if (!code) { inp.focus(); return; }
      go.disabled = true; inp.disabled = true; go.textContent = 'Registering…';
      postJson('/acct-login-code', { code: code }).then(function (r) {
        if (r && r.ok) { closeTabPops(); flash('✓ ' + (r.msg || 'Account registered'), 4000); refreshAcctIcon(); mkFocus(); }
        else {
          go.disabled = false; inp.disabled = false; go.textContent = 'Register'; inp.value = '';
          // the code is one-time and short-lived -> on failure, start from the link again. Surface the reason.
          flash('Registration failed' + (r && r.error ? ': ' + r.error : '') + ' — press the link again for a new code', 6000);
        }
      }).catch(function () {
        go.disabled = false; inp.disabled = false; go.textContent = 'Register';
        flash('Registration request failed', 2500);
      });
    };
    go.onclick = submit;
    inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
    form.appendChild(inp); form.appendChild(go);
    list.appendChild(hd); list.appendChild(a); list.appendChild(form);
    if (reflow) reflow();          // the link/form change the height -> re-place
    inp.focus();
  }).catch(function () {
    addBtn.disabled = false; addBtn.textContent = '+ Add account (login)';
    flash('Login link request failed', 2500);
  });
}
// ---- Codex (ChatGPT) — this box's single account. No pool/swap (Codex design) -> status + re-login + logout ----
function renderCodexSection(list, reflow) {
  const sep = document.createElement('div'); sep.className = 'sep'; list.appendChild(sep);
  const hd = document.createElement('div'); hd.className = 'hd'; hd.textContent = 'Codex (ChatGPT) · this box';
  list.appendChild(hd);
  const box = document.createElement('div'); box.className = 'codex-box'; box.textContent = 'Loading…';
  list.appendChild(box);
  fetch('/claude-status').then(function (x) { return x.json(); }).then(function (s) {
    renderCodexBody(box, (s && s.codex) || { state: 'unknown' });
    if (reflow) reflow();          // the Codex section changes the height -> re-place
  }).catch(function () { box.textContent = 'Codex status query failed'; if (reflow) reflow(); });
}
function renderCodexBody(box, cx) {
  box.textContent = '';
  const ok = cx.state === 'ok';
  const row = document.createElement('div'); row.className = 'codex-row';
  const nm = document.createElement('span'); nm.className = 'nm';
  nm.textContent = ok ? (cx.email || '(logged in)')
                      : (cx.state === 'none' ? 'Not logged in' : (cx.reason || cx.state));
  if (!ok) nm.style.color = '#e6b34d';
  const pl = document.createElement('span'); pl.className = 'pl';
  pl.textContent = ok ? ((cx.plan ? cx.plan + ' · ' : '') + 'ChatGPT') : (cx.state === 'none' ? 'codex login required' : '');
  row.appendChild(nm); row.appendChild(pl); box.appendChild(row);
  const btns = document.createElement('div'); btns.className = 'codex-btns';
  const relog = document.createElement('button'); relog.className = 'codex-btn';
  relog.textContent = ok ? 'Re-login' : 'Log in';
  relog.addEventListener('pointerdown', function (e) { e.preventDefault(); });
  relog.onclick = function () { startCodexLogin(box, relog); };
  btns.appendChild(relog);
  if (ok) {
    const lo = document.createElement('button'); lo.className = 'codex-btn danger'; lo.textContent = 'Log out';
    lo.addEventListener('pointerdown', function (e) { e.preventDefault(); });
    lo.onclick = function () {
      if (!window.confirm('Codex logout — auth.json will be removed.\nThe re-login button reconnects. Continue?')) return;
      lo.disabled = true; lo.textContent = '…';
      postJson('/codex-logout', {}).then(function (r) {
        if (r && r.ok) { flash('Codex logged out', 2000); renderCodexBody(box, { state: 'none' }); }
        else { lo.disabled = false; lo.textContent = 'Log out'; flash('Logout failed' + (r && r.error ? ': ' + r.error : ''), 3000); }
      }).catch(function () { lo.disabled = false; lo.textContent = 'Log out'; flash('Logout request failed', 2000); });
    };
    btns.appendChild(lo);
  }
  box.appendChild(btns);
}
// codex login --device-auth = headless device auth: no port-forward/callback. Open the link, enter the code.
// Starting re-login wipes auth.json immediately (backend backs it up) -> [Cancel] restores it if not completed.
function startCodexLogin(box, btn) {
  btn.disabled = true; btn.textContent = 'codex login…';
  postJson('/codex-login-start', {}).then(function (r) {
    if (!r || !r.ok || !r.code) { btn.disabled = false; btn.textContent = 'Re-login';
      flash('codex login failed to start' + (r && r.error ? ': ' + r.error : ''), 4500); return; }
    box.textContent = '';
    const g = document.createElement('div'); g.className = 'codex-guide';
    const warn = document.createElement('div'); warn.className = 'cg-step'; warn.style.color = '#e6b34d';
    warn.textContent = '⚠ Current login is cleared — finish, or press [Cancel] to restore.';
    const s1 = document.createElement('div'); s1.className = 'cg-step'; s1.textContent = '(1) Open in a browser:';
    const a = document.createElement('a'); a.className = 'acct-link'; a.href = r.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.textContent = '🔗 ' + r.url;
    const s2 = document.createElement('div'); s2.className = 'cg-step'; s2.textContent = '(2) Enter this code (within 15 min · click to copy):';
    const codeEl = document.createElement('code'); codeEl.className = 'cg-cmd'; codeEl.textContent = r.code; codeEl.title = 'click to copy';
    codeEl.onclick = function () { if (navigator.clipboard) { navigator.clipboard.writeText(r.code); flash('Copied', 1200); } };
    const s3 = document.createElement('div'); s3.className = 'cg-step'; s3.textContent = '(3) After logging in / approving:';
    const brow = document.createElement('div'); brow.className = 'codex-btns';
    const chk = document.createElement('button'); chk.className = 'codex-btn'; chk.textContent = 'Check';
    chk.addEventListener('pointerdown', function (e) { e.preventDefault(); });
    chk.onclick = function () {
      chk.disabled = true; chk.textContent = 'Checking…';
      fetch('/claude-status').then(function (x) { return x.json(); }).then(function (st) {
        const cx = (st && st.codex) || {};
        if (cx.state === 'ok') { flash('✓ Codex login complete: ' + (cx.email || ''), 3000); renderCodexBody(box, cx); }
        else { chk.disabled = false; chk.textContent = 'Check'; flash('Not logged in yet — enter the code / approve, then check again', 4000); }
      }).catch(function () { chk.disabled = false; chk.textContent = 'Check'; });
    };
    const cancel = document.createElement('button'); cancel.className = 'codex-btn danger'; cancel.textContent = 'Cancel (restore)';
    cancel.addEventListener('pointerdown', function (e) { e.preventDefault(); });
    cancel.onclick = function () {
      cancel.disabled = true; cancel.textContent = '…';
      postJson('/codex-login-cancel', {}).then(function (rr) {
        if (rr && rr.ok) {
          flash(rr.restored ? 'Cancelled — previous login restored' : 'Cancelled', 2500);
          fetch('/claude-status').then(function (x) { return x.json(); })
            .then(function (st) { renderCodexBody(box, (st && st.codex) || { state: 'unknown' }); }).catch(function () {});
        } else { cancel.disabled = false; cancel.textContent = 'Cancel (restore)'; flash('Cancel failed' + (rr && rr.error ? ': ' + rr.error : ''), 3000); }
      }).catch(function () { cancel.disabled = false; cancel.textContent = 'Cancel (restore)'; });
    };
    brow.appendChild(chk); brow.appendChild(cancel);
    g.appendChild(warn); g.appendChild(s1); g.appendChild(a); g.appendChild(s2); g.appendChild(codeEl); g.appendChild(s3); g.appendChild(brow);
    box.appendChild(g);
  }).catch(function () { btn.disabled = false; btn.textContent = 'Re-login'; flash('codex login request failed', 2000); });
}
// account popup placement — under the anchor, but flip above it if there isn't room below (bottom key bar).
// The list/Codex/login form fill async so the height grows; re-place on each render (reflow).
function placeAcctMenu(pop, anchor) {
  const r = anchor.getBoundingClientRect();
  const vh = window.visualViewport ? Math.round(window.visualViewport.height) : window.innerHeight;
  const h = pop.offsetHeight;
  let top = r.bottom + 6;
  if (top + h > vh - 6) top = r.top - h - 6;              // overflow below -> flip above the anchor
  top = Math.max(6, Math.min(top, vh - h - 8));           // still overflowing -> clamp into the viewport (internal scroll)
  pop.style.left = Math.max(6, Math.min(r.right - 320, window.innerWidth - pop.offsetWidth - 8)) + 'px';
  pop.style.top = top + 'px';
}
function openAcctMenu(anchor) {
  closeTabPops();
  const pop = document.createElement('div'); pop.className = 'tab-pop acct';
  const list = document.createElement('div');
  const loading = document.createElement('div'); loading.className = 'sep'; loading.textContent = 'Loading accounts / usage…';
  list.appendChild(loading); pop.appendChild(list);
  const r = anchor.getBoundingClientRect();
  placePop(pop, r.right - 320, r.bottom + 6);   // append to body first so we can measure
  const reflow = function () { placeAcctMenu(pop, anchor); };
  reflow();                                     // place from the loading state — flip above if near the bottom bar
  const render = function (j) {
    list.textContent = '';
    if (j && j.enabled === false) {
      const d = document.createElement('div'); d.className = 'sep'; d.textContent = 'Account switching is disabled';
      list.appendChild(d); reflow(); return;
    }
    const hd = document.createElement('div'); hd.className = 'hd';
    hd.textContent = 'Switch account · right = 5h / 7d usage';
    list.appendChild(hd);
    const accts = (j && j.accounts) || [];
    accts.forEach(function (a) {
      const dead = a.health && a.health.state === 'dead';
      const b = document.createElement('button'); b.className = 'acctrow' + (dead ? ' dead' : '');
      const L = document.createElement('div'); L.className = 'acct-l';
      // label = the real id (email) + kind (personal/team). Fall back to name if no email.
      const nm = document.createElement('span'); nm.className = 'nm';
      nm.textContent = (a.active ? '✓ ' : dead ? '❌ ' : '') + (a.email || a.name);
      const pl = document.createElement('span'); pl.className = 'pl';
      // a dead account shows its reason — without it the user can't act.
      pl.textContent = dead ? (a.health.reason || 'unavailable')
                            : (a.kind ? a.kind + ' · ' : '') + a.sub;
      if (dead) b.title = a.health.reason || '';
      // still alive but expiring soon = re-login now to cross over without interruption.
      const rtd = dead ? null : rtLeft(a);
      if (rtd != null && rtd <= RT_WARN_DAYS) {
        const w = document.createElement('span');
        w.style.color = rtd <= 2 ? C_RED : C_AMBER; w.style.fontWeight = '600';
        w.textContent = ' · ' + rtWarnText(rtd);
        pl.appendChild(w);
      }
      L.appendChild(nm); L.appendChild(pl);
      const R = document.createElement('div'); R.className = 'acct-r';
      const u = a.usage || {};
      if (dead) {
        R.style.color = C_AMBER;      // show the action, not usage (click = re-login flow)
        R.textContent = 'Re-login';
      } else if (u.use5h != null || u.use7d != null) {
        // exhaustion is judged only by utilization (429 is a query throttle, not an exhaustion signal).
        R.style.color = usageColor(u.use5h, u.use7d);
        R.textContent = '5h ' + (u.use5h == null ? '—' : u.use5h + '%') + '\n7d ' + (u.use7d == null ? '—' : u.use7d + '%');
      } else {
        R.style.color = '#8a92a6';
        R.textContent = u.err === 'no data' ? 'Collecting\n(<1 min)' : (u.err ? 'Query failed\n' + u.err : 'Usage\n—');
      }
      // hover = when it recovers + who holds it + expiry. Next to the cursor immediately.
      if (!dead) {
        b.addEventListener('mouseenter', function (e) { showAcctTip(e, u, a); });
        b.addEventListener('mousemove', placeAcctTip);
        b.addEventListener('mouseleave', hideAcctTip);
      }
      b.appendChild(L); b.appendChild(R);
      // remove (x) — non-active slots only (the CLI refuses active). Shown always (touch too).
      if (!a.active) {
        b.classList.add('removable');
        const x = document.createElement('span'); x.className = 'acct-x'; x.textContent = '✕';
        x.title = 'Remove this account from the pool';
        x.addEventListener('pointerdown', function (e) { e.preventDefault(); e.stopPropagation(); });
        x.addEventListener('click', function (e) {
          e.preventDefault(); e.stopPropagation();
          const label = a.email || a.name;
          if (!window.confirm('Remove account: ' + label + '\n\nDeleted from the pool.\nRe-login revives the same slot. Continue?')) return;
          hideAcctTip();
          postJson('/acct-remove', { name: a.name }).then(function (res) {
            if (res && res.ok) { flash('🗑 ' + label + ' removed', 2500); openAcctMenu(anchor); refreshAcctIcon(); }
            else flash('Remove failed' + (res && res.error ? ': ' + res.error : ''), 3500);
          }).catch(function () { flash('Remove request failed', 2000); });
        });
        b.appendChild(x);
      }
      b.addEventListener('pointerdown', function (e) { e.preventDefault(); });
      b.onclick = function () {
        // dead account = switching would fail. Send to re-login instead — name = id, same slot revives.
        if (dead) { startAddAcct(list, b, reflow); return; }
        if (a.active) { closeTabPops(); flash('Already using ' + a.name, 1400); mkFocus(); return; }
        closeTabPops();
        postJson('/acct-switch', { name: a.name }).then(function (res) {
          if (res && res.ok) { flash('✓ Switched to ' + (a.email || a.name) + ' (applies within ~1 min; restart the session for immediate effect)', 3000);
            refreshAcctIcon(); }
          else flash('Switch failed' + (res && res.error ? ': ' + res.error : ''), 2800);
          mkFocus();
        }).catch(function () { flash('Switch request failed', 2000); mkFocus(); });
      };
      list.appendChild(b);
    });
    const sep = document.createElement('div'); sep.className = 'sep'; list.appendChild(sep);
    const add = document.createElement('button'); add.className = 'addacct';
    add.textContent = '+ Add account (login)';
    add.addEventListener('pointerdown', function (e) { e.preventDefault(); });
    add.onclick = function () { add.disabled = true; add.textContent = 'Getting login link…'; startAddAcct(list, add, reflow); };
    list.appendChild(add);
    renderCodexSection(list, reflow);   // Codex (ChatGPT) section under the Claude accounts
    reflow();                           // re-place at the full rendered height (flip above from a bottom key bar)
  };
  fetch('/accounts').then(function (x) { return x.json(); }).then(function (j) {
    render(j);                       // draw with cached values first (keep the popup snappy)
    if (j && j.enabled === false) return;
    // the value at the moment it opened — the timer polls active every minute, so it can be up to 1 min stale.
    postJson('/acct-usage-now', {}).then(function (fresh) {
      if (!document.body.contains(pop)) return;              // already closed -> drop
      if (list.querySelector('.addform')) return;            // login in progress -> don't overwrite
      if (!fresh || !fresh.usage || fresh.usage.err) return;
      (j.accounts || []).forEach(function (a) {
        if (a.email === fresh.email && a.kind === fresh.kind) a.usage = fresh.usage;
      });
      render(j);
    }).catch(function () {});
  }).catch(function () {
    list.textContent = '';
    const d = document.createElement('div'); d.className = 'sep'; d.textContent = 'Failed to load list (check claude-switch)';
    list.appendChild(d);
  });
}

  // expose the 4 the core uses
  return { openAcctMenu: openAcctMenu, applyAcctIconCls: applyAcctIconCls, startAcctIconWatch: startAcctIconWatch, hideAcctTip: hideAcctTip };
};
