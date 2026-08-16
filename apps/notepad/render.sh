#!/usr/bin/env bash
# Sourceable render helpers for the Notepad compatibility route.

render_notepad_nginx() {
  cat <<'NGINX'
# Legacy Dev Hub entrypoint; the app-scoped path is canonical.
location = /notepad.html {
    return 308 /notepad/;
}
NGINX
}
