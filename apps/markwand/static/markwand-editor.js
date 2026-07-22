/* markwand-editor.js — filebrowser editor 에서 저장하면 markserv 뷰어로 자동 복귀
 *
 * nginx sub_filter 로 /markwand/edit/ (filebrowser SPA) 의 HTML 응답에 주입.
 * filebrowser v2.63.4 는 branding 으로 custom.css 만 자동 주입(custom.js 미지원)
 * → markserv 뷰어의 __markwand.js 와 동일하게 nginx sub_filter 로 주입.
 *
 * 동작: 에디터에서 저장(Ctrl+S / 상단 저장 버튼) → filebrowser 가
 *   PUT /markwand/edit/api/resources/<path> 호출 → 2xx 성공 시
 *   그 파일의 markserv 뷰어(/markwand/<path>)로 navigate.
 *   filebrowser 는 저장에 fetch·XHR 를 혼용하므로 둘 다 가로챈다.
 *   .md 만 대상(markserv 렌더 대상) — 그 외 확장자는 그대로 둔다.
 */
(function () {
  var EDIT_PREFIX = '/markwand/edit/files';   // 에디터 파일 라우트
  var VIEW_PREFIX = '/markwand';               // markserv 뷰어 prefix

  // /markwand/edit/files/foo/bar.md → /markwand/foo/bar.md (md 만, 아니면 null)
  function viewerUrlFor(editorPath) {
    if (editorPath.indexOf(EDIT_PREFIX) !== 0) return null;
    var rel = editorPath.substring(EDIT_PREFIX.length);   // /foo/bar.md
    if (!/\.md$/i.test(rel)) return null;
    return VIEW_PREFIX + rel;
  }

  function goViewer() {
    var u = viewerUrlFor(location.pathname);
    if (u) location.assign(u);
  }

  function isSavePut(method, url) {
    return !!method && String(method).toUpperCase() === 'PUT'
        && /\/api\/resources\//.test(url || '');
  }

  // 1) fetch 경로
  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (input, init) {
      var url = (typeof input === 'string') ? input : (input && input.url) || '';
      var method = (init && init.method) || (input && input.method) || 'GET';
      var p = origFetch.apply(this, arguments);
      if (isSavePut(method, url)) {
        p.then(function (res) { if (res && res.ok) goViewer(); }, function () {});
      }
      return p;
    };
  }

  // 2) XHR 경로
  var XHR = window.XMLHttpRequest;
  if (XHR && XHR.prototype) {
    var open = XHR.prototype.open;
    var send = XHR.prototype.send;
    XHR.prototype.open = function (method, url) {
      this.__mwSave = isSavePut(method, url);
      return open.apply(this, arguments);
    };
    XHR.prototype.send = function () {
      if (this.__mwSave) {
        this.addEventListener('load', function () {
          if (this.status >= 200 && this.status < 300) goViewer();
        });
      }
      return send.apply(this, arguments);
    };
  }
})();
