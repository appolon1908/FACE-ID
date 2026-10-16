$ErrorActionPreference = "Stop"
$root = git rev-parse --show-toplevel
Set-Location $root
$auth = Get-Content ".governance/authority.json" -Raw | ConvertFrom-Json
$branch = (git branch --show-current).Trim()
if ($branch -in @("main","master","production",$auth.base_branch)) { throw "PREFLIGHT_FAIL_PROTECTED_BRANCH" }
if ($branch -ne $auth.active_branch) { throw "PREFLIGHT_FAIL_BRANCH expected=$($auth.active_branch) actual=$branch" }
if ((git status --porcelain)) { throw "PREFLIGHT_FAIL_DIRTY" }
$origin=(git remote get-url origin).Trim()
if ($origin -ne $auth.repository_url) { throw "PREFLIGHT_FAIL_ORIGIN" }
git fetch --quiet origin $auth.base_branch $auth.active_branch
$base=(git rev-parse "origin/$($auth.base_branch)").Trim()
if ($base -ne $auth.base_sha) { throw "PREFLIGHT_FAIL_STALE_BASE expected=$($auth.base_sha) actual=$base" }
if ($env:ALLOW_PRODUCTION_EFFECTS -eq "1") { throw "PREFLIGHT_FAIL_PRODUCTION_EFFECTS_ENABLED" }
Write-Output "PREFLIGHT_PASS repo=$($auth.repository) branch=$branch head=$((git rev-parse HEAD).Trim())"
