#!/usr/bin/env bash
# notepad deactivate — no app-specific stop step. notepad has no unit and no
# background process of its own. Its declared webroot and compatibility nginx
# fragment are removed by the ledger's generic artifact classes (D5:
# "deactivate.sh is the app-specific stop hook ... anything the declared
# classes cannot express"). This script exists only so notepad is NOT
# install/upgrade-only (D6 priority 1) — dropping [apps.notepad] from config
# must be allowed to remove it, not refuse. Idempotent by construction.
set -euo pipefail
exit 0
