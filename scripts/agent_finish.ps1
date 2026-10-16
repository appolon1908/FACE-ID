$ErrorActionPreference = "Stop"
$root = git rev-parse --show-toplevel
Set-Location $root
git diff --check
if ((git status --porcelain)) { throw "AGENT_FINISH_FAIL_DIRTY" }
if ((git ls-files -u)) { throw "AGENT_FINISH_FAIL_UNMERGED" }
Write-Output "AGENT_FINISH_PASS head=$((git rev-parse HEAD).Trim())"
