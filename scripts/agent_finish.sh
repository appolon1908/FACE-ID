#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel); cd "$root"; scripts/worktree_guard.sh; git diff --check
test -z "$(git status --porcelain)" || { echo AGENT_FINISH_FAIL_DIRTY; git status --short; exit 41; }
test -z "$(git ls-files -u)" || { echo AGENT_FINISH_FAIL_UNMERGED; exit 42; }
echo "AGENT_FINISH_PASS head=$(git rev-parse HEAD)"
