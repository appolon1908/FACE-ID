# Codestra FACE-ID API Contract

Base path: /v1

## Platform
GET /healthz
GET /readyz
GET /metrics
GET /v1/capabilities

## Faces
POST /v1/faces/enroll
DELETE /v1/faces/{subject_id}
POST /v1/faces/detect
POST /v1/faces/verify
POST /v1/faces/search

## Cameras
POST /v1/cameras
GET /v1/cameras
DELETE /v1/cameras/{camera_id}
POST /v1/streams/{camera_id}/test

## Events
GET /v1/events

All authenticated mutations should carry correlation IDs. Sensitive biometric payloads must not be written to ordinary application logs.

## Missions 21-25 (see docs/MISSIONS_21_25_API_FLOW.md)

### Access decisions (decision-only; never actuates hardware)
POST /v1/access/evaluate

### Presence / occupancy
POST /v1/presence/events
GET /v1/presence/current
GET /v1/presence/history

### Unknown clusters (labels are NOT identities)
GET /v1/unknown-clusters
POST /v1/unknown-clusters
GET /v1/unknown-clusters/{cluster_id}
PATCH /v1/unknown-clusters/{cluster_id}
POST /v1/unknown-clusters/{cluster_id}/events
DELETE /v1/unknown-clusters/{cluster_id}/events/{event_id}

### Camera-zone mapping
GET /v1/camera-zones
POST /v1/camera-zones
PATCH /v1/camera-zones/{mapping_id}
DELETE /v1/camera-zones/{mapping_id}

### Review queues
GET /v1/review-queues
POST /v1/review-queues
GET /v1/review-queues/{queue_id}
PATCH /v1/review-queues/{queue_id}
DELETE /v1/review-queues/{queue_id}
GET /v1/review-queues/{queue_id}/items
POST /v1/review-queues/{queue_id}/items
GET /v1/review-queues/{queue_id}/items/{item_id}
PATCH /v1/review-queues/{queue_id}/items/{item_id}

The live OpenAPI document is served at /openapi.json and /docs (local boundary only); Missions 21-25 routes are tagged
access-decisions, presence, unknown-clusters, camera-zones, and review-queues.

## Missions 26-30 (see docs/MISSIONS_26_30_API_FLOW.md)

### Watchlists (local policy metadata; NOT proof of identity, no automatic actions)
GET /v1/watchlists
POST /v1/watchlists
GET /v1/watchlists/{watchlist_id}
PATCH /v1/watchlists/{watchlist_id}
DELETE /v1/watchlists/{watchlist_id}
GET /v1/watchlists/{watchlist_id}/members
POST /v1/watchlists/{watchlist_id}/members
DELETE /v1/watchlists/{watchlist_id}/members/{member_id}
GET /v1/subjects/{subject_id}/watchlists

### Enrollment sessions (multi-image, quality-gated; quality is NOT liveness)
GET /v1/enrollment-sessions
POST /v1/enrollment-sessions
GET /v1/enrollment-sessions/{session_id}
POST /v1/enrollment-sessions/{session_id}/images
POST /v1/enrollment-sessions/{session_id}/finalize
POST /v1/enrollment-sessions/{session_id}/cancel

### Duplicate candidates (operator review only; never auto-merged)
POST /v1/enrollment-sessions/{session_id}/duplicate-check
GET /v1/duplicate-candidates
POST /v1/duplicate-candidates/{candidate_id}/resolve

### Model registry / re-embedding (read-only registry; no automatic migration)
GET /v1/models
GET /v1/models/current
GET /v1/models/migration-status
GET /v1/reembedding-jobs
POST /v1/reembedding-jobs
POST /v1/reembedding-jobs/{job_id}/complete
POST /v1/reembedding-jobs/{job_id}/cancel

### Audit / compliance
GET /v1/audit/export
GET /v1/audit/retention

OpenAPI tags: watchlists, enrollment-sessions, duplicate-candidates, model-registry, audit-compliance.
