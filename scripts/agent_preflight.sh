#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"
mode=local
certify=0
ci_branch=
for arg in "$@"; do
  case "$arg" in
    --ci) mode=ci ;;
    --certify) certify=1 ;;
    mission/face-id-middleware-integration-20260924) ci_branch=$arg ;;
    *) echo "PREFLIGHT_FAIL_ARG=$arg"; exit 19 ;;
  esac
done
# CODESTRA_GLOBAL_GOVERNANCE_V1
for required in .governance/repository.yaml .governance/workstation-policy.yaml .governance/authority.json scripts/worktree_guard.sh scripts/agent_finish.sh scripts/certify.sh scripts/reconcile.sh; do
 test -f "$required" || { echo "PREFLIGHT_FAIL_GOVERNANCE_FILE=$required"; exit 18; }
done
if env | grep -q '^ALLOW_PRODUCTION_EFFECTS=1$'; then echo PREFLIGHT_FAIL_PRODUCTION_EFFECTS_ENABLED; exit 17; fi
if test "$mode" = local; then scripts/worktree_guard.sh; fi
authority="$root/.codestra-mission/ACTIVE-LANE.env"
test -f "$authority" || { echo PREFLIGHT_FAIL_AUTHORITY_MISSING; exit 20; }
. "$authority"
actual_origin=$(git remote get-url origin 2>/dev/null || true)
test "$actual_origin" = "$EXPECTED_ORIGIN" || { echo "PREFLIGHT_FAIL_ORIGIN expected=$EXPECTED_ORIGIN actual=$actual_origin"; exit 21; }
if test "$mode" = ci; then branch=$ci_branch; else branch=$(git branch --show-current); fi
test -n "$branch" || { echo PREFLIGHT_FAIL_DETACHED; exit 22; }
test "$branch" = "$ACTIVE_BRANCH" || { echo "PREFLIGHT_FAIL_BRANCH expected=$ACTIVE_BRANCH actual=$branch"; exit 23; }
test "$branch" != "$BASE_REF" && test "$branch" != main && test "$branch" != master || { echo PREFLIGHT_FAIL_PROTECTED_BRANCH; exit 24; }
if test "$mode" = local && test -n "$(git status --porcelain)"; then echo PREFLIGHT_FAIL_DIRTY; exit 25; fi
git cat-file -e "$BASE_SHA^{commit}" 2>/dev/null || { echo "PREFLIGHT_FAIL_BASE_SHA_MISSING=$BASE_SHA"; exit 26; }
git merge-base --is-ancestor "$BASE_SHA" HEAD || { echo "PREFLIGHT_FAIL_BASE_NOT_ANCESTOR=$BASE_SHA"; exit 27; }
tracking="refs/remotes/origin/$BASE_REF"
if git show-ref --verify --quiet "$tracking"; then
  tracked_sha=$(git rev-parse "$tracking")
  test "$tracked_sha" = "$BASE_SHA" || { echo "PREFLIGHT_FAIL_STALE_BASE expected=$BASE_SHA tracked=$tracked_sha"; exit 28; }
fi
if test "$mode" = local; then
  upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
  if test -n "$upstream" && test "$upstream" != "origin/$ACTIVE_BRANCH"; then echo "PREFLIGHT_FAIL_UPSTREAM expected=origin/$ACTIVE_BRANCH actual=$upstream"; exit 29; fi
fi
if git grep -n -E '^(<<<<<<< |>>>>>>> )' -- . ':!docs/RECONCILIATION-LANES.md' >/tmp/codestra-conflicts.$$ 2>/dev/null; then
  cat /tmp/codestra-conflicts.$$; rm -f /tmp/codestra-conflicts.$$; echo PREFLIGHT_FAIL_CONFLICT_MARKERS; exit 30
fi
rm -f /tmp/codestra-conflicts.$$ 2>/dev/null || true
added=$(git diff --unified=0 "$BASE_SHA"...HEAD -- '*.sh' '*.bash' '*.ps1' '*.py' '*.js' '*.ts' '*.yml' '*.yaml' 'Dockerfile*' 'Makefile*' '.github/workflows/*' ':!scripts/agent_preflight.sh' ':!.github/workflows/agent-governance.yml' | sed -n 's/^+\([^+]\)/\1/p')
if printf '%s
' "$added" | grep -Eqi '(/metrics|/internal).*(public|expose|0\.0\.0\.0)|0\.0\.0\.0.*(/metrics|/internal)|Access-Control-Allow-Origin[^[:alnum:]]*\*'; then echo PREFLIGHT_FAIL_FORBIDDEN_ROUTE_OR_HEADER; exit 31; fi
if printf '%s\n' "$added" | grep -Eqi '(ALLOW_PRODUCTION_EFFECTS|production_authorized|runtimeApplyAuthorized|provider_effects_enabled|live_effects_enabled)[[:space:]]*[:=][[:space:]]*(1|true|yes)'; then echo PREFLIGHT_FAIL_PRODUCTION_EFFECT_FLAG; exit 32; fi
if test "$certify" -eq 1; then
  git diff --check "$BASE_SHA"...HEAD
  test -z "$(git status --porcelain)" || { echo PREFLIGHT_FAIL_CERT_DIRTY; exit 33; }
  echo "CERT_BASE_SHA=$BASE_SHA"
  echo "CERT_HEAD_SHA=$(git rev-parse HEAD)"
  echo "CERT_ORIGIN=$EXPECTED_ORIGIN"
fi
echo "PREFLIGHT_PASS repo=$REPOSITORY branch=$branch base=$BASE_SHA head=$(git rev-parse HEAD)"
