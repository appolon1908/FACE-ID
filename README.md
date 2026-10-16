# Codestra FACE-ID

Local-first face recognition, camera ingestion, enrollment, review, and audit service for Codestra.

## Architecture

EZVIZ / ONVIF / RTSP camera → FACE-ID API → Recognition Engine → PostgreSQL → dashboard / events / audit.

## Running services

- FACE-ID dashboard/API: http://127.0.0.1:8094
- LAN self-registration page: http://10.0.0.73:8094/register
- Recognition engine: http://127.0.0.1:8091
- PostgreSQL: internal Docker network only

Camera credentials stay in `.env` and are never committed.

## Current capabilities

- live RTSP camera preview
- ONVIF profile discovery
- face enrollment with explicit consent
- face verification and gallery search
- recognized / unknown event ledger
- event snapshots
- unknown-event review workflow
- QR self-registration for Dominican Republic identity references
- administrator approval / rejection of QR registrations
- cédula privacy design: the full number is hashed in the browser before submission
- people management and retention metadata
- audit trail for administrative actions
- event and identity retention cleanup
- configurable match threshold
- browser notifications for new unknown-face review items
- multi-camera selector in the dashboard
- Prometheus metrics, health, readiness, and OpenAPI documentation
- zones, access policies, visitor passes, alert rules, incidents, retention policies, labels, privacy export/delete (Missions 11-20)
- decision-only access evaluation with reason codes — never actuates doors or hardware (Mission 21)
- idempotent presence sessions and zone occupancy (Mission 22)
- operator-owned unknown clusters — a cluster label is not an identity (Mission 23)
- camera-to-zone mapping metadata (Mission 24)
- review queues with opaque assignee references (Mission 25)
- watchlists / subject categories — local policy metadata, not proof of identity, no automatic actions (Mission 26)
- multi-image enrollment sessions with documented quality thresholds and deterministic embedding aggregation (Mission 27)
- duplicate-enrollment candidates for operator review, with a threshold separate from recognition; never auto-merged (Mission 28)
- model / embedding version registry, migration status, and a non-destructive re-embedding queue (Mission 29)
- bounded, redacted, hash-chained audit export with manifest, plus audit retention readback (Mission 30)

See `docs/MISSIONS_11_20_API_FLOW.md`, `docs/MISSIONS_21_25_API_FLOW.md`, and `docs/MISSIONS_26_30_API_FLOW.md`.

## Tests

`scripts/run-tests.sh` runs the pytest suite inside the service image against a dedicated `faceid_test` database. `scripts/smoke-test.sh` checks the running service.

## Security boundary

The administration dashboard is available only from the local desktop boundary. LAN clients can access the registration page and public registration endpoint, but administrative routes are denied.

QR self-registration does **not** verify an identity against Dominican government or JCE records. It stores a cryptographic cédula reference, the last four digits, consent metadata, and a recognition embedding only after administrator approval.

## Privacy

- explicit consent is required for enrollment
- camera passwords are not returned through APIs
- the full Dominican cédula number is not sent to FACE-ID by the registration page
- event snapshots are retained according to the configured event-retention policy
- enrolled identities are automatically removed when their configured retention period expires
- registration photos are used to derive embeddings and are not persisted by the registration workflow
- enrollment-session images are never stored; per-image embeddings are purged when a session is finalized, cancelled, or expired
- replaced embeddings are archived for `FACEID_EMBEDDING_HISTORY_DAYS` (default 30) and then purged; privacy deletion purges them immediately
- audit exports redact secrets, biometric templates, and cédula hashes

## Production limitations

Liveness / presentation-attack detection is currently **not enabled**. The dashboard reports this explicitly. Do not treat FACE-ID as anti-spoof capable until a tested liveness model and calibration gate are added. Enrollment quality checks (face count, size, sharpness, brightness) are not liveness checks. Head pose is not assessed because the current engine does not expose landmarks.

External SMS/email/push notification delivery and centralized Keycloak RBAC are not enabled in this local deployment.