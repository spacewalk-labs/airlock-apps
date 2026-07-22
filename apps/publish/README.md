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

## Optional: external publishing (pluggable target)

If you configure `[apps.publish.public_target]`, an HTML page in the share
directory can be snapshotted into a single self-contained file (local CSS/JS/
images inlined; external URLs left as-is) and POSTed to *your* ingest endpoint,
which returns a public URL with a TTL. Leave the table out and the manager runs
local-only (the external-publish buttons stay hidden).

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
