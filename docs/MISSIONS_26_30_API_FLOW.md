# FACE-ID Missions 26–30 — Watchlists, Enrollment Quality, Duplicates, Model Registry, Audit Export

These missions extend Missions 11–25. All rules from `MISSIONS_21_25_API_FLOW.md` still apply:

- Cross-system effects travel only through `Caddy -> Kong -> Middleware V3 :8095 -> FACE-ID API`. None of these features call another application; the only outbound call is to the co-located recognition engine, as before.
- Direct LAN administrative access is denied (HTTP 403). Only `/register`, `/v1/public/enroll`, and `/healthz` are reachable from the LAN.
- Keycloak is the identity and role authority. FACE-ID trusts no role or user headers. Every `*_ref` field is an opaque reference (`[A-Za-z0-9._:@-]`, 1–128 chars).
- New request bodies reject unknown fields (HTTP 422).
- Every mutation writes to `audit_log`. Audit details never contain images or embeddings.
- Schema changes are idempotent `CREATE TABLE/INDEX IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` statements in `init_db()`.

## Mission 26 — Watchlists / subject categories

- `GET /v1/watchlists?category=&status=`, `POST /v1/watchlists`, `GET|PATCH|DELETE /v1/watchlists/{watchlist_id}`
- `GET /v1/watchlists/{watchlist_id}/members?include_expired=`, `POST /v1/watchlists/{watchlist_id}/members`
- `DELETE /v1/watchlists/{watchlist_id}/members/{member_id}`
- `GET /v1/subjects/{subject_id}/watchlists`

Categories: `staff`, `visitor`, `contractor`, `vip`, `review-required`, `denied-access`. Statuses: `active`, `archived` (archived lists reject new members). A list that still has members cannot be deleted (409); remove the members or archive the list.

Members: exactly one of `subject_ref`/`subject_id` (an enrolled subject) or `visitor_pass_id` (an existing visitor pass), plus an optional `note`, `added_by_ref`, and `expires_at`. Adding the same member twice returns the existing row with `created: false`. Expired members stay stored and are flagged `expired: true`.

> **A watchlist is local policy metadata, not proof of identity.** Responses always include `identity_proof: false` and `automatic_actions: false`. Adding someone to `denied-access` does not change `/v1/access/evaluate`, send an alert, or call another system. Any action based on a watchlist is an explicit operator decision.

Privacy export lists a subject's memberships. Privacy delete and retention expiry remove them.

## Mission 27 — Enrollment sessions and image quality

- `POST /v1/enrollment-sessions` `{subject_id, display_name, consent_obtained: true, consent_reference, retention_days, operator_ref?}`
- `GET /v1/enrollment-sessions?status=&subject_id=`, `GET /v1/enrollment-sessions/{session_id}`
- `POST /v1/enrollment-sessions/{session_id}/images` `{image_base64, consent_obtained: true}`
- `POST /v1/enrollment-sessions/{session_id}/finalize`, `POST /v1/enrollment-sessions/{session_id}/cancel`

A subject can have only one open session at a time. Sessions expire after `FACEID_ENROLL_SESSION_TTL_HOURS` (default 24). If `subject_id` already exists, the session is a re-enrollment (`re_enrollment: true`).

### Per-image quality metadata

| field | how it is computed |
| --- | --- |
| `face_count` | 1 for the engine's primary (largest) face, plus any extra frontal faces at least half the primary face's size, found by OpenCV's bundled Haar cascade outside the primary box. The engine reports only its largest face, so FACE-ID runs this check locally. |
| `face_bbox`, `face_min_side_px` | the engine's primary detection, clipped to the image |
| `sharpness` | variance of the Laplacian over the grayscale face crop |
| `brightness` | mean grayscale value (0–255) over the face crop |
| `pose` | `null`, with `pose_supported: false`. The current engine (YuNet + SFace) does not return landmarks or pose. |
| `liveness_checked` | always `false` |

Rejection thresholds (environment variables, defaults shown):

| reason | rule |
| --- | --- |
| `no_face_detected` | engine found no face |
| `multiple_faces` | `face_count > 1` |
| `face_too_small` | `face_min_side_px < FACEID_ENROLL_MIN_FACE_PX` (80) |
| `too_blurry` | `sharpness < FACEID_ENROLL_MIN_SHARPNESS` (40) |
| `too_dark` / `too_bright` | `brightness` outside `FACEID_ENROLL_MIN_BRIGHTNESS`..`FACEID_ENROLL_MAX_BRIGHTNESS` (40..220) |
| `duplicate_image` | byte-identical image already accepted in the session |
| `model_version_changed` | the engine model changed after earlier images in the session were accepted |

Rejected images return HTTP 422 with `detail.reasons` and `detail.quality`. The attempt is recorded with its quality metadata only. Size limit: `FACEID_ENROLL_MAX_IMAGE_BYTES` (6 MiB). At most `FACEID_ENROLL_MAX_IMAGES` (10) accepted images per session. Finalize needs at least `FACEID_ENROLL_MIN_IMAGES` (1).

> **Quality checks are not liveness or presentation-attack detection.** A sharp, well-lit photo of a photo passes. `capabilities.liveness` stays `false`.

### Aggregation (`l2-mean-l2/v1`)

At finalize time, the accepted embeddings (all from the same `model_key`) are combined deterministically:

1. L2-normalise each embedding (float64).
2. Take the element-wise arithmetic mean in image sequence order.
3. L2-normalise the mean.
4. Round each component to 8 decimal places.

The subject then records `embedding_method = l2-mean-l2/v1`, `embedding_image_count`, and the full model and embedding-version metadata (Mission 29).

Privacy: images are never stored. FACE-ID keeps a SHA-256 of each image only to reject duplicates. Per-image embeddings are held only while the session is open, and are purged when it is finalized, cancelled, or expired. Quality metadata is kept.

## Mission 28 — Duplicate enrollment candidates

- `POST /v1/enrollment-sessions/{session_id}/duplicate-check` — run the search on demand
- `GET /v1/duplicate-candidates?status=open|resolved|all&session_id=`
- `POST /v1/duplicate-candidates/{candidate_id}/resolve` `{resolution: not_duplicate|duplicate_confirmed|dismissed, note?, resolver_ref?}`

The session's aggregate embedding is compared by cosine similarity with every other subject, excluding the session's own `subject_id`. The comparison uses `FACEID_DUPLICATE_THRESHOLD` (default **0.30**), which is kept separate from the recognition threshold `FACEID_MATCH_THRESHOLD` (0.363). The service refuses to start if the two are equal. The lower default is meant to surface near-matches for a human to look at; it is not a recognition decision. Subjects with a different `embedding_version` are skipped (`skipped_incompatible_subjects`). Legacy subjects with no version are still compared and flagged `version_unverified: true`. At most `FACEID_DUPLICATE_MAX_CANDIDATES` (20) candidates are recorded, highest score first.

Candidates contain only `subject_ref`, `candidate_subject_ref`, `score`, `threshold`, and review state. They carry no names or templates, and always report `identity_asserted: false` and `auto_merge: false`.

Finalize runs the check again. While any candidate for the session is `open` or resolved as `duplicate_confirmed`, finalize returns **409** with the candidate list and nothing is enrolled. An operator resolves each candidate:

- `not_duplicate` / `dismissed` → finalize may proceed
- `duplicate_confirmed` → finalize stays blocked; cancel the session (and, if appropriate, re-enroll into the existing `subject_id`)

FACE-ID never merges, deletes, or relabels subjects because of a candidate. Detection (`duplicate_candidate.detected`) and resolution (`duplicate_candidate.resolved`) are audited. Cancelling or expiring a session closes its open candidates with `resolution: session_closed`.

## Mission 29 — Model and embedding version registry

Each subject now stores `model_key`, `model_id`, `model_version`, `model_digest`, `embedding_version`, `embedding_dim`, `embedding_method`, `embedding_image_count`, and `embedded_at`. These are set by manual enroll, QR registration approval, enrollment-session finalize, and re-embedding.

| field | value for the current engine |
| --- | --- |
| `model_id` | `opencv-sface/sface-2021dec` |
| `model_version` | `sface-2021dec` |
| `model_digest` | `sha256:` over the canonical engine descriptor `{provider, detector, recognizer, metric}` (`digest_kind: descriptor-sha256`). The engine does not expose model-file hashes. |
| `embedding_version` | `sface-2021dec:cosine:l2norm` (defines which vector space embeddings are compatible with) |
| `model_key` | `opencv-sface:sface-2021dec@<12 hex of digest>` |

Endpoints:

- `GET /v1/models` — the registry of every model that has produced a stored embedding, with subject counts. Read-only: FACE-ID records entries itself, and there is no write endpoint.
- `GET /v1/models/current` — the live engine descriptor and whether it is registered. Performs no writes.
- `GET /v1/models/migration-status` — subjects per `embedding_version`, how many are on the current version or need migration, unversioned legacy subjects, re-embedding job counts, and archived embeddings. `automatic_migration: false`.
- `GET /v1/reembedding-jobs?status=&subject_id=`, `POST /v1/reembedding-jobs` `{subject_ids[≤500], reason, requested_by_ref?}`
- `POST /v1/reembedding-jobs/{job_id}/complete` `{images_base64[1..10], consent_obtained: true, consent_reference?}`, `POST /v1/reembedding-jobs/{job_id}/cancel`

Safety rules:

- Queuing jobs changes nothing (`destructive: false`). Each subject can have at most one queued job.
- FACE-ID does not keep source images, so re-embedding needs **new consented images** supplied by an operator for each job. There is no bulk "re-embed everything" operation.
- On completion the images go through the Mission 27 quality gate. If any image is rejected, the response is 422 and the job stays queued. If the engine's `embedding_version` differs from the job's target, the job becomes `failed` and the subject is not changed.
- The old embedding is copied into `subject_embedding_history` **in the same transaction** that writes the new one. If the replacement fails, the transaction rolls back and the old embedding stays current. After a successful replacement, the archived embedding is kept for `FACEID_EMBEDDING_HISTORY_DAYS` (30 days) and then purged. Privacy delete and subject retention expiry purge it immediately.

## Mission 30 — Audit and compliance export

`GET /v1/audit/export?since=&until=&actor=&action=&target_type=&limit=&cursor=`

- `since` and `until` are required ISO-8601 timestamps with an offset. The range is `[since, until)` and may not exceed `FACEID_AUDIT_EXPORT_MAX_DAYS` (366).
- `action` is an exact match, or a prefix match when it ends in `*` (e.g. `subject.*`). `actor` and `target_type` are exact matches.
- `limit` is 1–1000 (default 500). Records are ordered by `(occurred_at, audit_id)`. `manifest.next_cursor` continues the export; a cursor only works with the same filters (otherwise 400).

Each record has `audit_id, occurred_at (UTC), actor, action, target_type, target_id, details, record_sha256`.

Redaction (`faceid-audit-redaction/v1`) is applied to `details` recursively:

| class | rule | replacement |
| --- | --- | --- |
| biometric | keys such as `embedding(s)`, `template(s)`, `image(s)`, `image_base64`, `snapshot`, `vector`, `feature(s)`, `photo`, `face_crop`, `biometric*`; any numeric list with ≥32 items; `data:image…` strings; base64-like strings ≥512 chars | `[REDACTED:biometric]` |
| secret | keys containing `password`, `secret`, `token`, `api_key`, `authorization`, `credential(s)`, `cookie`, `private_key`, `signature`, `hmac_key` (except `*_env` variable *names*); `Bearer …`/`Basic …` values | `[REDACTED:secret]` |
| identifier | `id_hash` (cédula hash) | `[REDACTED:identifier]` |

Integrity manifest (`manifest.integrity`):

- `record_sha256` = SHA-256 over the canonical JSON of the record without `record_sha256` (sorted keys, `(",", ":")` separators, UTF-8).
- Hash chain: `chain_i = sha256(chain_{i-1} + record_sha256_i)` (hex strings concatenated). Page 1 starts from 64 zeros. Each later page's `chain_seed` equals the previous page's `chain_head`, so the pages of one export verify as a single chain.
- `page_sha256` = SHA-256 over the concatenated record digests of the page.
- If `FACEID_AUDIT_EXPORT_HMAC_KEY` is set, `manifest.signature = {algorithm: hmac-sha256, key_id, value}` over the canonical manifest without `signature`. Otherwise `signature` is `null`. The key is never returned.

The manifest also contains `export_id`, `filters`, `filters_sha256`, `page`, `record_count`, `has_more`, the first and last timestamps, redaction counts, and a copy of the retention readback. Each export page is itself audited as `audit.exported`.

`GET /v1/audit/retention` returns the `audit` retention policy (from `/v1/retention-policies`, if one exists), the record count, the oldest and newest timestamps, and how many records are older than the policy. **`enforced: false`**: FACE-ID never deletes audit records automatically. The policy is advisory; export before any purge an operator runs.

## Capabilities

`GET /v1/capabilities` now also reports `watchlists`, `enrollment_sessions` (thresholds, aggregation method, `liveness: false`), `duplicate_candidates` (both thresholds, `auto_merge: false`), `model_registry`, and `audit_export`.

## Verification

- `scripts/run-tests.sh` runs the pytest suite, including `tests/test_missions_26_30.py`. The recognition engine is replaced by a deterministic fake in most tests, and synthetic noise images are used; no real faces. One test calls the real engine when it is reachable.
- `scripts/smoke-test.sh` runs live GET checks for every new surface and checks that each one returns LAN 403.
