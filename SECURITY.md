# Security boundaries

Airlock app backends are intended to sit behind the Airlock identity gate. A backend that relies on that gate must bind to loopback; an unavoidable wider bind needs an app-owned firewall rule and regression coverage. Disabling backend authentication is safe only while the gate is the sole reachable path.

`fileview` is deliberately not a filesystem sandbox: it exposes the files reachable by its Unix service account, including dotfiles, and therefore defaults to owner-only access. `dev-monitor` spool writers can create console cards but do not gain command execution through that capability. App READMEs and manifests define the exact per-app boundary.

This repository is public. Never commit credentials or private deployment identifiers. Run the privacy checks in `.github/workflows/ci.yml` before handoff; automated scanning does not replace review of every file derived from a private source.
