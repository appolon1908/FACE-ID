# FACE-ID Missions 21–25 — Decisions, Presence, Clusters, Camera-Zones, Review Queues

These missions extend the Missions 11–20 management APIs. All rules from that document still apply:

- Cross-system effects travel only through `Caddy -> Kong -> Middleware V3 :8095 -> FACE-ID API`. FACE-ID makes no direct app-to-app calls for these features.
- Direct LAN administrative access is denied (HTTP 403). Only `/register`, `/v1/public/enroll`, and `/healthz` are LAN-reachable.
- Keycloak is the identity and role authority. FACE-ID trusts no role/user headers (`X-Role`, `X-User`, `X-Forwarded-For`, ...). Every `*_ref` field is an opaque reference (`[A-Za-z0-9._:@-]`, 1–128 chars) that FACE-ID stores but never interprets as an authorization claim.
- All new request bodies reject unknown fields (HTTP 422), so credentials, embeddings, images, or "unlock" flags cannot be smuggled in.
- Every mutation and every access decision writes to `audit_log`. No raw biometric data (images, embeddings) is stored or audited by these features.
- Schema changes are idempotent `CREATE TABLE/INDEX IF NOT EXISTS` statements in `init_db()`; existing tables and rows are untouched.

## Mission 21 — Access decision API

`POST /v1/access/evaluate`

```json
{"subject_ref":"do-1a2b...","zone_id":"lobby","occurred_at":"2026-09-24T12:00:00Z","visitor_pass_id":null}
```

`subject_id` is accepted as an alias of `subject_ref` (if both are sent they must match). At least one of subject or `visitor_pass_id` is required. `occurred_at` must be ISO-8601 **with** a timezone offset.

Evaluation (fail-closed):

1. Zone must exist and be enabled → otherwise `zone_not_found` / `zone_disabled`.
2. Subject (if given) must be enrolled → otherwise `subject_not_found`.
3. Visitor pass (if given) must exist, be `active`, and `valid_from <= occurred_at < valid_until` → otherwise `visitor_pass_not_found` / `visitor_pass_inactive` / `visitor_pass_not_yet_valid` / `visitor_pass_expired`.
4. Candidate policies: enabled policies for the zone whose `subject_id` equals the subject or is null (general zone rule).
5. Any candidate with an invalid schedule → deny `policy_invalid`. Any matching deny policy → deny `policy_denied` (deny overrides allow). Otherwise any matching allow → allow `policy_allowed` (+ `visitor_pass_valid`). Otherwise deny `no_matching_policy`.

Response:

```json
{"decision_id":"dec-...","decision":"allow","allowed":true,"reason_codes":["policy_allowed"],
 "matched_policy_ids":["pol-lobby"],"matched_visitor_pass_id":null,"subject_id":"...","zone_id":"lobby",
 "visitor_pass_id":null,"occurred_at":"2026-09-24T12:00:00+00:00","decision_only":true,"actuation":"none"}
```

**This endpoint is decision-only.** It never unlocks a door, never calls hardware, and never calls another service. Any actuation must be performed by a separate, authorized system via Middleware V3 using this decision as input.

### Access-policy schedule format

`schedule` on `/v1/access-policies` now accepts only these keys (empty object = always):

| key | meaning |
| --- | --- |
| `days` | non-empty list of `mon`..`sun` (local day of `occurred_at`) |
| `start`, `end` | `HH:MM`, provided together, must differ; `end` exclusive; `start > end` means an overnight window |
| `timezone` | IANA zone, default `UTC` |

Unknown keys or malformed values are rejected at save time (HTTP 400). Legacy rows with invalid schedules make evaluation deny with `policy_invalid`.

## Mission 22 — Presence / occupancy

- `POST /v1/presence/events` — `{event_ref, direction: enter|exit, subject_ref|subject_id|visitor_pass_id, event_id?, camera_id?, zone_id?, occurred_at?}`
- `GET /v1/presence/current?zone_id=` — open sessions and per-zone occupancy counts
- `GET /v1/presence/history?zone_id=&subject_ref=&since=&until=&status=all|open|closed&limit=`

Rules:

- `event_ref` is the idempotency key. Replaying an identical body returns the stored result with `idempotent_replay: true`; a different body for the same `event_ref` is `409`.
- `event_id` (optional) must reference an existing FACE-ID event; it supplies the camera and, if no subject is given, the attributed subject (`reviewed_subject_id`, else `subject_id`).
- Zone resolution: explicit `zone_id` (and, if `camera_id` is also given, an enabled camera-zone mapping must exist), otherwise the preferred enabled mapping for `camera_id` (Mission 24). No zone → 400.
- A partial unique index guarantees at most one open session per (subject, zone). Outcomes: `session_opened`, `already_present`, `session_closed`, `no_open_session`, `exit_before_entry_ignored`.
- Privacy export includes a subject's presence sessions; privacy deletion removes them and their observations.

## Mission 23 — Unknown clusters

- `GET /v1/unknown-clusters?status=`, `POST /v1/unknown-clusters`, `GET|PATCH /v1/unknown-clusters/{cluster_id}`
- `POST /v1/unknown-clusters/{cluster_id}/events` `{event_ids:[...]}` — attach (idempotent for events already in this cluster; `409` if in another cluster)
- `DELETE /v1/unknown-clusters/{cluster_id}/events/{event_id}` — detach

> **A cluster label is NOT a real-world identity.** Clusters are operator-owned working groups of `unknown_face` events ("same jacket at north door, 3 visits"). They carry no `subject_id` (requests containing one are rejected with 422), responses always state `"identity_asserted": false`, and nothing in FACE-ID treats a cluster as enrolled, authorized, or recognized. Turning an unknown person into an identity still requires the consented QR registration / enrollment flow and administrator approval.

Only events with `event_type = unknown_face` may be attached. Cluster membership rows for events deleted by retention are removed automatically. Statuses: `open`, `monitoring`, `resolved`, `dismissed`. `owner_ref` is opaque.

## Mission 24 — Camera-zone mapping

- `GET /v1/camera-zones?camera_id=&zone_id=`
- `POST /v1/camera-zones` `{camera_id, zone_id, priority=100 (0–1000, lower preferred), enabled, notes}` — upsert keyed on (camera_id, zone_id); response `created` indicates insert vs update
- `PATCH /v1/camera-zones/{mapping_id}`, `DELETE /v1/camera-zones/{mapping_id}`

Camera and zone must exist. Mappings are metadata only: no credentials, RTSP paths, or streaming settings are accepted (unknown fields → 422) and camera ingest is unchanged. Deleting a camera removes its mappings. All mutations are audited.

## Mission 25 — Review queues

- `GET|POST /v1/review-queues`, `GET|PATCH|DELETE /v1/review-queues/{queue_id}`
- `GET|POST /v1/review-queues/{queue_id}/items`, `GET|PATCH /v1/review-queues/{queue_id}/items/{item_id}`

Queue: `status` `active|paused|archived`, `default_priority`. Duplicate `queue_id` → 409. A queue with items cannot be deleted (archive it instead); archived queues reject new items (409).

Item: `item_type` ∈ `event | registration | incident | unknown_cluster`, `item_ref` must exist in the corresponding table (else 400). `priority` `low|normal|high|urgent`, `status` `open|in_progress|resolved|dismissed` (`resolved_at` is set/cleared automatically). Creating an item that already exists in the queue returns the existing item with `created: false`. Lists are ordered urgent → low, then oldest first; filter by `status`, `assignee_ref`, `priority`.

`assignee_ref` is an opaque Keycloak-side reference (e.g. `kc:<user-uuid>`); set it to `null` to unassign. FACE-ID does not resolve it, does not derive it from headers, and does not use it for authorization.

## Capabilities

`GET /v1/capabilities` now reports `access_decisions`, `presence`, `unknown_clusters`, `camera_zone_mapping`, `review_queues`, and `middleware_authority`.

## Verification

- `scripts/run-tests.sh` — pytest suite in the FACE-ID image against a dedicated `faceid_test` database (refuses any non-`_test` database).
- `scripts/smoke-test.sh` — live service checks including new GET endpoints, fail-closed evaluation, and LAN 403 for each new surface.
