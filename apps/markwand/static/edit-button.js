/* edit-button.js — Markwand Dev Server (markwand-aware)
 * Injected into every markserv-rendered .md page by nginx sub_filter.
 * Floats top-right "✏️ Edit" → opens same file in filebrowser editor.
 *
 * iframe 안 (split-pane viewer) 에서는 parent 의 topbar ✏️ Edit 가 있으니
 * 중복/문서 가림 회피를 위해 X. single-pane viewer (직접 진입) 만 표시.
 */
(function () {
  if (!location.pathname.endsWith('.md')) return;
  // iframe 안에서는 절대 띄우지 않음
  try { if (window.self !== window.top) return; } catch (_) { return; }

  var p = location.pathname;
  if (p.indexOf('/markwand/') === 0) p = p.substring('/markwand'.length);
  var target = location.origin + '/markwand/edit/files' + p + '?edit=true';

  var a = document.createElement('a');
  a.id = 'markwand-edit-btn';
  a.href = target;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = '✏️ Edit';
  a.title = 'Open in filebrowser editor';
  document.body.appendChild(a);
})();
