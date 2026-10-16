#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel); cd "$root"
python3 - <<'PY'
import json,subprocess,os,sys
a=json.load(open(".governance/authority.json"))
def g(*x): return subprocess.check_output(["git",*x],text=True).strip()
checks=[("worktree",os.path.realpath(os.getcwd()),os.path.realpath(a["canonical_worktree"])),("branch",g("branch","--show-current"),a["active_branch"]),("origin",g("remote","get-url","origin"),a["repository_url"]),("upstream",g("rev-parse","--abbrev-ref","@{upstream}"),a["upstream_ref"])]
bad=[c for c in checks if c[1]!=c[2]]
if bad:
 [print("WORKTREE_GUARD_FAIL %s expected=%s actual=%s"%(k,e,v)) for k,v,e in bad]; sys.exit(40)
print("WORKTREE_GUARD_PASS")
PY
