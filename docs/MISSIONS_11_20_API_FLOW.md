# FACE-ID Missions 11–20 — API and Flow Completion

These ten missions extend Codestra FACE-ID while preserving the standalone-service rule and the canonical cross-system path:

`Caddy -> Kong -> Middleware V3 :8095 -> FACE-ID API`

Direct LAN administrative access remains denied. These endpoints are local/admin service APIs until Middleware contracts, Keycloak workload identity, and release evidence activate them.

## Mission 11 — Zones

Purpose: define physical/security areas independently of cameras.

Endpoints:
- `GET /v1/zones`
- `POST /v1/zones`

Flow: operator -> Middleware policy -> FACE-ID zone registry -> audit.

## Mission 12 — Access policies

Purpose: bind a subject or general rule to a zone with allow/deny and a schedule.

Endpoints:
- `GET /v1/access-policies`
- `POST /v1/access-policies`

Flow: identity reference + zone + schedule -> validated policy -> audit. A policy is not a door-unlock command.

## Mission 13 — Visitor passes

Purpose: create temporary visitor authorization windows without turning the visitor workflow into permanent identity authority.

Endpoints:
- `GET /v1/visitor-passes`
- `POST /v1/visitor-passes`

Flow: host/visitor metadata -> validity window -> optional QR registration request -> pass status -> audit.

## Mission 14 — Alert rules

Purpose: define event-driven alert intent separately from delivery providers.

Endpoints:
- `GET /v1/alert-rules`
- `POST /v1/alert-rules`

Flow: event type + optional camera -> delivery channel + opaque recipient reference -> Middleware/provider delivery later.

No raw provider credentials are accepted.

## Mission 15 — Incidents

Purpose: group recognition/security events into operator cases.

Endpoints:
- `GET /v1/incidents`
- `POST /v1/incidents`

Flow: event references -> severity/status -> notes -> case timeline/audit.

## Mission 16 — Retention policies

Purpose: make retention intent explicit and queryable.

Endpoints:
- `GET /v1/retention-policies`
- `POST /v1/retention-policies`

Supported resource types: events, event snapshots, visitors, incidents, audit.

## Mission 17 — Subject labels

Purpose: add operator-defined non-biometric labels without changing the biometric template.

Endpoints:
- `GET /v1/subjects/{subject_id}/labels`
- `PUT /v1/subjects/{subject_id}/labels`

Labels are bounded, normalized strings and are included in audit.

## Mission 18 — Privacy export

Purpose: allow an administrator to export a person's FACE-ID record and associated event references without exporting raw embeddings.

Endpoint:
- `GET /v1/privacy/subjects/{subject_id}/export`

The export contains identity metadata, consent metadata, labels, and event references. It intentionally excludes the biometric embedding.

## Mission 19 — Privacy deletion

Purpose: remove an enrolled identity and detach related policy/event references.

Endpoint:
- `DELETE /v1/privacy/subjects/{subject_id}`

Flow: delete labels/policies -> detach event subject references -> clear host references -> delete identity -> delete owned event snapshots where applicable -> audit.

## Mission 20 — Integration status

Purpose: answer which FACE-ID dependencies are configured and healthy without exposing credentials.

Endpoint:
- `GET /v1/integrations/status`

Reports:
- recognition-engine readiness
- enabled camera count
- whether liveness, camera-gateway, and PostgreSQL-management bindings are configured
- canonical Middleware V3 authority path

## Environment and user model

Promotion remains:

`development -> testing -> staging -> production`

Keycloak is the identity/role authority. FACE-ID does not trust arbitrary role headers. Multi-user and multi-tenant authorization should be normalized by Middleware and workload identity before production activation of these endpoints.

## Completion gate

Each mission is considered implemented when:
1. its table/schema exists,
2. request validation is fail-closed,
3. endpoint works locally,
4. audit is emitted for mutations,
5. no secret or raw biometric embedding is returned,
6. LAN admin isolation still returns 403,
7. readiness and camera smoke tests remain green,
8. exact branch HEAD is pushed to GitHub.
