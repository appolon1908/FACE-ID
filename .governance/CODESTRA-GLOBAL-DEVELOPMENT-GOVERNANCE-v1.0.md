# CODESTRA GLOBAL DEVELOPMENT GOVERNANCE

MASTER IMPLEMENTATION DIRECTIVE
VERSION: 1.0
SCOPE: ALL REPOSITORIES, WORKSTATIONS, WORKTREES, IDEs, GIT, CI/CD AND AGENTS

## MISSION

Implement one physically enforced development-governance standard across the entire Codestra engineering environment.

This is NOT a documentation-only mission. The final system must prevent repository drift, abandoned code, accidental dirty worktrees, untracked agent branches, stale-SHA development, incorrect upstreams, unauthorized pushes, merge-conflict accumulation, production side effects, and deletion of unproven historical work.

Every repository must use the same governance model while retaining its own repository-specific build/test/runtime commands.

## 1. NON-NEGOTIABLE GLOBAL PRINCIPLES

1. One governance standard across ALL repositories.
2. One canonical active development lane per repository.
3. One registered active worktree per repository/mission.
4. No agent may create arbitrary development lanes.
5. Never develop directly on main/master.
6. Never force-push.
7. Never reset, stash, discard, overwrite, or delete another agent's work.
8. Never delete unproven history.
9. Dirty work is evidence until reconciled.
10. Historical worktrees are read-only reconciliation sources.
11. New development starts only from a clean governed worktree.
12. Every worktree must have a provable upstream.
13. Every development session must begin with exact SHA verification.
14. Stale-base development must fail closed.
15. Publication is separate from development.
16. Certification is separate from development testing.
17. A development-worktree test is NOT a certification.
18. Production effects default OFF.
19. Protected branches are never modified directly.
20. CI enforcement is authoritative; documentation alone is insufficient.

## 2. WORKSTATION ROLES

Ubuntu desktop role: DEVELOPMENT_AND_CERTIFICATION.

Allowed: fetch, inspect, governed worktrees, edit, test, Docker/local runtime testing, Postman/Newman, PostgreSQL/local dependencies, build, lint, typecheck, deterministic certification, commits, and Git bundles.

Forbidden by default: production mutation, force push, direct main push, ungoverned remote publication.

Appolon laptop role: PUBLICATION_AUTHORITY.

Before every push Appolon must receive an exact Git object/bundle, verify SHA-256, verify repository and branch, fetch remote, record expected remote SHA, compare expected vs actual, refuse stale/divergent publication, require clean local state, perform only a normal non-force push, never automatically push main/master, read back remote SHA, and require remote SHA == intended SHA. If NO_PUSH is active, stop after compare-and-swap verification.

## 3. REQUIRED REPOSITORY GOVERNANCE PACKAGE

Every repository requires:
- AGENTS.md
- .governance/repository.yaml
- .governance/workstation-policy.yaml
- .governance/authority.json
- scripts/agent_preflight.sh
- scripts/agent_finish.sh
- scripts/certify.sh
- scripts/reconcile.sh
- scripts/worktree_guard.sh
- .github/workflows/agent-governance.yml

Where Windows support is required:
- scripts/agent_preflight.ps1
- scripts/agent_finish.ps1
- scripts/certify.ps1

AGENTS.md is mandatory entry authority. Copilot/Codex/Claude instructions must point to AGENTS.md.

## 4. AGENT PREFLIGHT MUST FAIL CLOSED

Before any modification verify repository, workstation role, canonical worktree, expected non-protected branch, clean start, origin, upstream, remote branch, successful fetch, HEAD, remote SHA, merge-base/current base, no detached HEAD outside certification, no merge/rebase/cherry-pick, no ownership conflict, production effects disabled, and forbidden routes/headers absent.

Any mandatory failure means: DO NOT EDIT, RESET, STASH, OR DELETE. Report the exact blocker.

## 5. WORKTREE REGISTRY

Maintain a global machine-readable registry containing repository, URL, canonical path, worktree path, branch, base branch/SHA, head SHA, upstream, mission, owner, agent, workstation, timestamps, status, production-effects permission, and certification status.

Valid status values: ACTIVE, CERTIFICATION, NEEDS_RECONCILIATION, READ_ONLY_PRESERVED, ARCHIVED, SUPERSEDED.

No two agents may own the same ACTIVE worktree simultaneously.

## 6. HISTORICAL WORK POLICY

Do not clean old repositories in place. Inventory path, branch, HEAD, upstream, dirty state, ahead/behind, PR association, merge status, unique commits/patches, untracked files, and active process locks. Unknown state defaults to NEEDS_RECONCILIATION.

## 7. PRESERVATION BEFORE CLEANUP

Preserve exact HEAD and unique refs, save git status and untracked lists, preserve necessary untracked content, create and verify Git bundles where appropriate, compute SHA-256, and record provenance. Remove a worktree only after clean/unlocked/reconciled/reachable/archive-verified proof.

## 8. SEMANTIC RECONCILIATION

Reconcile implementation logic, API contracts, routes, headers, identity, authorization, security boundaries, tests, migrations, runtime configuration, CI behavior, and certification evidence. Do not reconcile based on hashes alone.

## 9. DEVELOPMENT LANE MODEL

Each repository gets one governed active lane. New agents enter through "codestra enter <repo> <mission>". Bootstrap must locate canonical repo, fetch, verify remote/base SHA, refuse dirty state, create/reuse registered worktree, assign ownership, configure upstream, disable production effects, run preflight, record BASE_SHA, and open the governed IDE workspace. No random branch creation.

## 10. GIT RULES

Forbidden: force pushes, direct main development, automatic main push, blind reset --hard, blind stash, deleting unknown branches, deleting dirty worktrees, detached-HEAD editing, stale publication.

Required: fetch before development/publication, exact SHA comparisons, normal non-force pushes, remote SHA verification, clean start, clean finish.

## 11. COMMIT RULES

Commits are narrow, mission-specific, reviewable, reversible, tested, and free of unrelated changes.

## 12. CERTIFICATION MODEL

Certification uses a fresh exact-SHA clone/worktree, detached clean checkout, isolated temp/caches, deterministic dependency install, relevant format/lint/typecheck/unit/security/integration/migration/policy/mTLS/signing/build/Docker/local API/Postman/PostgreSQL gates, authority validation, git diff --check, clean post-state, and repeatable release/remediation runs.

Evidence binds commit SHA, tree SHA, base SHA, test counts, artifact/runtime digests, timestamp, and tool versions.

## 13. MERGE RESULT POLICY

validate-merge-result failure means BASE_RECONCILIATION_REQUIRED. Fetch current base, reconcile semantically, produce exact SHA, re-certify cleanly, publish only the certified SHA.

## 14. CI GOVERNANCE

Every repository has a required governance job rejecting protected-main development, dirty-start assumptions, stale merge base, wrong upstream, forbidden routes/headers, legacy fallback, production-effect flags, unapproved generated drift, and missing governance files. No bypass.

## 15. PRODUCTION EFFECT POLICY

Default ALLOW_PRODUCTION_EFFECTS=0. Unauthorized live PSTN, SMS, email, money movement, billing, production DB writes, production secret rotation, social publishing, or routing changes must fail closed.

## 16. ROUTING / IDENTITY SAFETY

No generic legacy unknown-route fallback. Unknown route = 404 fail closed. /metrics and /internal are never publicly forwarded. Client-asserted identity headers are not trusted blindly. Public edge uses explicit routes/contracts.

## 17. DEPENDENCY REMEDIATION

Trace the exact dependency path, identify patched version, test compatibility in isolation, avoid incompatible major overrides, run deterministic installation/runtime/relevant gates, create exact remediation commit, certify, transfer object to Appolon, CAS verify, publish only when authorized.

## 18. IDE GOVERNANCE

VS Code/Visual Studio opens governed workspaces only. Recommended: git.autofetch=true, git.confirmSync=true, git.enableSmartCommit=false, git.allowForcePush=false. Control center shows repo, mission, branch, HEAD, upstream, dirty state, certification, PR, and CI.

## 19. ONE-LINE COMMANDS

Implement codestra inventory, enter, status, preflight, test, certify, finish, reconcile, archive, and publish-preflight.

## 20. CHRONOLOGICAL AUTHORITY

Maintain a machine-readable mission ledger with sequence, repository, mission_id, base_sha, start_sha, result_sha, PR, certification digest, status, dependency, supersedes, and timestamp.

## 21. GLOBAL DEVELOPMENT HUB

Maintain one control plane per workstation with repo/worktree/mission/certification/archive registries, workspace files, one-line entry commands, and blockers.

## 22. ROLLOUT ORDER

Wave 1 governance infrastructure.
Wave 2 Caddy, Kong, Middleware, Keycloak, Odoo, N8N, OpenBao.
Wave 3 monitoring/observability stack.
Wave 4 product repositories.
Wave 5 all remaining discovered repositories.

## 23. CURRENT MONITORING MIGRATION CHECKPOINT

Do not restart monitoring governance from scratch. Use the registered canonical Monitoring-Active worktrees and preserve historical dirty monitoring work as reconciliation evidence.

## 24. COMPLETION DEFINITION

DONE requires canonical repo/worktree, classified/preserved history, governance manifest, AGENTS, executable preflight/finish/certification, CI governance, protected branch confirmation, IDE registration, registry update, clean baseline certification, one-line entry/finish, publication policy, Linear/Notion update, and no unclassified dirty work.

## 25. REQUIRED FINAL REPORT

Report REPOSITORY, CANONICAL_PATH, ACTIVE_WORKTREE, BRANCH, HEAD, UPSTREAM, DIRTY, HISTORICAL_WORK_CLASSIFIED, ARCHIVE_VERIFIED, GOVERNANCE_INSTALLED, PREFLIGHT_PASS, CI_GOVERNANCE, CERTIFICATION, IDE_REGISTERED, PUBLICATION_AUTHORITY, OPEN_PR, BLOCKERS, NEXT_ACTION.

Never claim completion for an unverified field.

## 26. PRIME DIRECTIVE

DO NOT MAKE THE REPOSITORIES LOOK CLEAN. MAKE THEM PROVABLY CLEAN.

Preserve first. Reconcile second. Certify third. Publish fourth. Retire old work only after proof.

The result must behave like a professional engineering control plane, not a collection of independent agent workspaces.
