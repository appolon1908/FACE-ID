#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel); cd "$root"
echo "REPOSITORY=$(basename "$root")"; echo "PATH=$root"; echo "BRANCH=$(git branch --show-current)"; echo "HEAD=$(git rev-parse HEAD)"
echo "UPSTREAM=$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || echo NONE)"
echo STATUS_BEGIN; git status --short; echo STATUS_END
echo UNMERGED_BEGIN; git ls-files -u; echo UNMERGED_END
echo UNTRACKED_BEGIN; git ls-files --others --exclude-standard; echo UNTRACKED_END
echo RECONCILE_MODE=READ_ONLY_REPORT
