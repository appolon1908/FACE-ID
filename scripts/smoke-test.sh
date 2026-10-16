#!/usr/bin/env bash
set -euo pipefail

BASE="${FACEID_BASE:-http://127.0.0.1:8094}"
LAN_BASE="${FACEID_LAN_BASE:-http://10.0.0.73:8094}"
OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT

check() {
  local name="$1" url="$2" expected="$3"
  local code
  code="$(curl -sS -o "$OUT" -w '%{http_code}' "$url")"
  if [[ "$code" != "$expected" ]]; then
    echo "FAIL $name expected=$expected got=$code"
    cat "$OUT" || true
    exit 1
  fi
  echo "PASS $name ($code)"
}

check "ready" "$BASE/readyz" "200"
check "dashboard" "$BASE/" "200"
check "dashboard-data" "$BASE/v1/dashboard" "200"
check "subjects" "$BASE/v1/subjects" "200"
check "events" "$BASE/v1/events?limit=5" "200"
check "registrations" "$BASE/v1/registrations?status=pending" "200"
check "audit" "$BASE/v1/audit?limit=5" "200"
check "camera-onvif" "$BASE/v1/cameras/ezviz-main/onvif" "200"
check "camera-snapshot" "$BASE/v1/cameras/ezviz-main/snapshot" "200"
check "registration-qr" "$BASE/v1/registration/qr" "200"
check "capabilities" "$BASE/v1/capabilities" "200"
check "camera-zones" "$BASE/v1/camera-zones" "200"
check "presence-current" "$BASE/v1/presence/current" "200"
check "presence-history" "$BASE/v1/presence/history?limit=5" "200"
check "unknown-clusters" "$BASE/v1/unknown-clusters" "200"
check "review-queues" "$BASE/v1/review-queues" "200"
check "watchlists" "$BASE/v1/watchlists" "200"
check "enrollment-sessions" "$BASE/v1/enrollment-sessions" "200"
check "duplicate-candidates" "$BASE/v1/duplicate-candidates" "200"
check "models" "$BASE/v1/models" "200"
check "models-current" "$BASE/v1/models/current" "200"
check "models-migration-status" "$BASE/v1/models/migration-status" "200"
check "reembedding-jobs" "$BASE/v1/reembedding-jobs" "200"
check "audit-retention" "$BASE/v1/audit/retention" "200"
check "clients" "$BASE/v1/clients?limit=5" "200"
SINCE="$(date -u -d '-1 day' +%Y-%m-%dT%H:%M:%SZ)"; UNTIL="$(date -u -d '+1 day' +%Y-%m-%dT%H:%M:%SZ)"
check "audit-export" "$BASE/v1/audit/export?since=$SINCE&until=$UNTIL&limit=5" "200"
if grep -q '"embedding":\[' "$OUT"; then echo "FAIL audit-export leaked an embedding"; exit 1; fi
check "audit-export-unbounded" "$BASE/v1/audit/export?since=2000-01-01T00:00:00Z&until=$UNTIL" "400"

code="$(curl -sS -o "$OUT" -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{"subject_ref":"smoke-nonexistent","zone_id":"smoke-nonexistent","occurred_at":"2026-01-01T00:00:00Z"}' "$BASE/v1/access/evaluate")"
if [[ "$code" != "200" ]] || ! grep -q '"decision":"deny"' "$OUT"; then
  echo "FAIL access-evaluate-fail-closed code=$code"; cat "$OUT"; exit 1
fi
echo "PASS access-evaluate-fail-closed ($code deny)"

REG_URL="$(curl -fsS "$BASE/v1/registration/info" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
check "lan-registration" "$REG_URL" "200"
check "lan-register-no-token" "$LAN_BASE/register" "403"
check "lan-admin-denied" "$LAN_BASE/" "403"
check "lan-camera-zones-denied" "$LAN_BASE/v1/camera-zones" "403"
check "lan-presence-denied" "$LAN_BASE/v1/presence/current" "403"
check "lan-unknown-clusters-denied" "$LAN_BASE/v1/unknown-clusters" "403"
check "lan-review-queues-denied" "$LAN_BASE/v1/review-queues" "403"
check "lan-watchlists-denied" "$LAN_BASE/v1/watchlists" "403"
check "lan-enrollment-sessions-denied" "$LAN_BASE/v1/enrollment-sessions" "403"
check "lan-duplicate-candidates-denied" "$LAN_BASE/v1/duplicate-candidates" "403"
check "lan-models-denied" "$LAN_BASE/v1/models" "403"
check "lan-reembedding-jobs-denied" "$LAN_BASE/v1/reembedding-jobs" "403"
check "lan-audit-export-denied" "$LAN_BASE/v1/audit/export?since=$SINCE&until=$UNTIL" "403"
check "lan-audit-retention-denied" "$LAN_BASE/v1/audit/retention" "403"
check "lan-clients-denied" "$LAN_BASE/v1/clients" "403"

echo "FACE-ID smoke test: PASS"
