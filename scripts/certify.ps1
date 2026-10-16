$ErrorActionPreference = "Stop"
$root = git rev-parse --show-toplevel
Set-Location $root
$sha = if ($args.Count -gt 0) { $args[0] } else { (git rev-parse HEAD).Trim() }
if ((git status --porcelain)) { throw "CERTIFY_FAIL_CONTAMINATED_SOURCE" }
$tree=(git rev-parse "$sha^{tree}").Trim()
Write-Output "CERTIFICATION_COMMIT_SHA=$sha"
Write-Output "CERTIFICATION_TREE_SHA=$tree"
Write-Output "CERTIFICATION_MODE=USE_UBUNTU_ISOLATED_EXACT_SHA_FOR_FULL_CERTIFICATION"
