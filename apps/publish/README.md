# publish

A static-share manager for your Airlock, plus an **optional, pluggable** way to
publish a page to a public URL.

- **`/publish/`** — manage the share directory (default `/opt/airlock/share`):
  list entries, unpublish (unlink symlinks, keeping the original), delete direct
  files (with a retype-to-confirm step), batch operations, and repair broken
  symlinks.
- **`/publish/files/`** — the share directory served by nginx (behind the hub
  identity gate). Symlink or drop files here to make them reachable in your hub.
- **`/publish/api/upload-*`** — the drop used by [notepad](../notepad): pasted
  images and attached files land in `~/uploads` for a terminal/agent to read by
  path. Everything in `~/uploads` is deleted after 24h (a timer sweeps it).

Everything above is **local** and needs no configuration beyond `[apps.publish]`.

## Optional: external publishing (two modes)

If you configure `[apps.publish.public_target]`, an HTML page in the share
directory can be snapshotted into a single self-contained file (local CSS/JS/
images inlined; external URLs left as-is) and given a public URL with a TTL.
Leave the table out and the manager runs share-only (the external-publish
buttons stay hidden).

`mode` is explicit and never inferred: a half-configured target stays **off** and
says why in the journal, instead of quietly becoming a live public publisher.

### mode = "local" — this box serves the links itself

No second service, no token. Snapshots land in `public_dir`, which **your**
nginx serves at `base_url`. The TTL picker in the UI (24h / 7d / 14d / 30d) is
enforced here: the hourly cleanup timer deletes expired pages from disk, so an
expired link really 404s (within the hour).

```toml
[apps.publish.public_target]
mode       = "local"
base_url   = "https://doc.example.com"       # public URLs are <base_url>/<slug>/
public_dir = "/opt/airlock/share-public"     # default; nginx serves THIS
```

```nginx
server {
    listen 127.0.0.1:80;
    server_name doc.example.com;
    root /opt/airlock/share-public;      # NOT share_dir
    location / { try_files $uri $uri/ $uri/index.html =404; }
}
```

> ⚠️ **`public_dir` must not be `share_dir`** (nor contain it, nor sit inside
> it). `share_dir` is the tailnet-internal share — full of symlinks you added
> for private viewing — and nginx follows symlinks. The installer and the
> backend both refuse an overlapping `public_dir`.

Snapshot metadata (owner, source name, expiry) lives in
`~/.local/state/airlock/publish-public.json`, deliberately **outside** the
served directory. Local snapshots are capped at 25 MB; the remote path is not.

Password-gating is not a feature of this app — put an nginx `auth_basic` in
front of a separate directory if you need it.

### mode = "remote" (default) — you host an ingest service

Snapshots are POSTed to *your* endpoint, which returns the public URL.

```toml
[apps.publish.public_target]
ingest_url = "https://your-ingest.example"   # you host this (protocol below)
base_url   = "https://docs.example"          # public URLs are <base_url>/<slug>/
token_env  = "AIRLOCK_PUBLISH_TOKEN"         # env var holding the auth token
```

The token is **not** stored in the config. Put it in the env var named by
`token_env`, delivered via an EnvironmentFile the installer already wires:

```
# ~/.config/airlock-publish.env   (chmod 600)
AIRLOCK_PUBLISH_TOKEN=…your token…
```

### Ingest protocol (what your target must implement)

JSON over HTTPS. The token is sent in the `X-Airlock-Publish-Token` header.

| Method + path        | Request body                                              | Response                                              |
|----------------------|----------------------------------------------------------|------------------------------------------------------|
| `POST /ingest`       | `{slug, owner, src, title, ttl_hours, html_b64}`         | `{ok, result:{expiry, ttl_hours}}`                   |
| `GET  /list?owner=`  | —                                                        | `{ok, items:[{slug, owner, src, title, expiry, expired}]}` |
| `POST /revoke`       | `{slug, owner}`                                          | `{ok}`                                               |
| `POST /set-expiry`   | `{slug, owner, ttl_hours}`                               | `{ok}`                                               |

- `html_b64` is base64 of the self-contained snapshot.
- `owner` is the identity of the publisher (from the hub identity header); your
  endpoint should scope `list`/`revoke`/`set-expiry` to that owner.
- The public URL shown to the user is `base_url/slug/`; your target decides how
  it actually serves that slug.

A minimal target is just a small web service that stores each `html_b64` under
its `slug`, serves it until `expiry`, and returns 404 afterwards.
