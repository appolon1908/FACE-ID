#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel); cd "$root"
sha=${1:-$(git rev-parse HEAD)}
test -z "$(git status --porcelain)" || { echo CERTIFY_FAIL_CONTAMINATED_SOURCE; exit 51; }
git cat-file -e "$sha^{commit}"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/codestra-cert.XXXXXX")
cleanup(){ git worktree remove --force "$tmp/worktree" >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
git worktree add --detach "$tmp/worktree" "$sha" >/dev/null
cd "$tmp/worktree"
test -z "$(git status --porcelain)" || { echo CERTIFY_FAIL_DIRTY_FRESH_WORKTREE; exit 52; }
branch=$(python3 -c 'import json;print(json.load(open(".governance/authority.json"))["active_branch"])')
bash scripts/agent_preflight.sh --ci "$branch" --certify
git diff --check
echo "CERTIFICATION_COMMIT_SHA=$sha"
echo "CERTIFICATION_TREE_SHA=$(git rev-parse "$sha^{tree}")"
echo CERTIFICATION_MODE=ISOLATED_EXACT_SHA_CONTROL_GATE
echo CERTIFICATION_REPOSITORY_TESTS=REQUIRE_REPO_SPECIFIC_COMMAND
