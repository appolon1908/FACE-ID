"""Current default implementation behavior, not the older foundation placeholders."""
from pathlib import Path
import time

import httpx
import pytest
from conftest import main, sql


def enroll(client, subject='subject-fixture'):
    return client.post('/v1/faces/enroll', json={'subject_id': subject,
        'display_name': 'Synthetic Fixture', 'image_base64': 'synthetic-image-placeholder',
        'consent_obtained': True, 'consent_reference': 'synthetic-ci-consent', 'retention_days': 30})


def camera(client):
    result = client.post('/v1/cameras', json={'camera_id': 'camera-fixture', 'name': 'Synthetic Camera',
        'host': '192.0.2.1', 'password_env': 'UNSET_SYNTHETIC_CAMERA_REFERENCE', 'enabled': False})
    assert result.status_code == 200
    return 'camera-fixture'


def test_health_and_actual_capabilities(client):
    assert client.get('/healthz').json() == {'ok': True}
    capabilities = client.get('/v1/capabilities').json()
    assert capabilities['storage'] == 'postgresql'
    assert capabilities['liveness'] is False
    assert capabilities['admin_access'] == 'local-only'


def test_database_schema_init_is_idempotent():
    main.init_db()
    assert sql('select count(*) from subjects') == [(0,)]


def test_readiness_requires_engine_fixture(client, engine):
    assert client.get('/readyz').json() == {'ok': True, 'database': True, 'recognition_engine': True}


def test_engine_readiness_failure_is_not_reported_healthy(client, monkeypatch):
    monkeypatch.setattr(main.httpx, 'get', lambda *a, **k: httpx.Response(503, text='fixture unavailable'))
    assert client.get('/readyz').status_code == 503


@pytest.mark.parametrize('path', ['/', '/v1/subjects', '/v1/cameras', '/v1/events', '/v1/audit', '/metrics'])
def test_remote_admin_requests_are_denied(remote, path):
    assert remote.get(path).status_code == 403


def test_enrollment_without_consent_never_reaches_engine(client):
    response = client.post('/v1/faces/enroll', json={'subject_id': 'denied', 'display_name': 'Fixture',
        'image_base64': 'fixture', 'consent_obtained': False})
    assert response.status_code == 400
    assert sql('select count(*) from subjects') == [(0,)]


def test_enrollment_persists_consent_embedding_and_audit(client, engine):
    assert enroll(client).status_code == 200
    assert sql('select embedding, consent_obtained, consent_reference from subjects') == [([1.0, 0.0], True, 'synthetic-ci-consent')]
    assert sql("select action from audit_log where target_id='subject-fixture'") == [('subject.enrolled',)]
    assert client.get('/v1/subjects').json()[0]['subject_id'] == 'subject-fixture'


def test_subject_deletion_removes_data_and_records_audit(client, engine):
    enroll(client)
    assert client.delete('/v1/faces/subject-fixture').json()['deleted'] is True
    assert sql('select count(*) from subjects') == [(0,)]
    assert ('subject.deleted',) in sql('select action from audit_log')


def test_search_and_verify_use_only_mocked_engine_and_owned_gallery(client, engine):
    enroll(client)
    request = {'image_base64': 'fixture'}
    search = client.post('/v1/faces/search', json=request)
    assert search.json()['hits'][0]['display_name'] == 'Synthetic Fixture'
    assert client.post('/v1/faces/verify', json=request).json()['recognized'] is True
    assert any(call[0].endswith('/v1/search') for call in engine)


def test_camera_registry_roundtrip_does_not_open_hardware(client):
    identifier = camera(client)
    assert client.get('/v1/cameras').json()[0]['password_env'] == 'UNSET_SYNTHETIC_CAMERA_REFERENCE'
    assert client.delete('/v1/cameras/' + identifier).json()['deleted'] is True
    assert client.get('/v1/cameras').json() == []


@pytest.mark.parametrize('path,method', [('onvif', 'get'), ('test', 'post')])
def test_missing_camera_secret_fails_before_any_hardware(client, monkeypatch, path, method):
    identifier = camera(client)
    monkeypatch.delenv('UNSET_SYNTHETIC_CAMERA_REFERENCE', raising=False)
    url = '/v1/cameras/' + identifier + '/onvif' if path == 'onvif' else '/v1/streams/' + identifier + '/test'
    assert getattr(client, method)(url).status_code == 424


def test_registration_secret_is_required(client):
    assert client.get('/v1/registration/info').status_code == 503
    assert client.get('/v1/registration/qr').status_code == 503


def test_invalid_public_registration_token_fails_without_engine(remote, monkeypatch):
    monkeypatch.setattr(main, 'REGISTRATION_SECRET', 'synthetic-ci-registration-only')
    response = remote.post('/v1/public/enroll', json={'full_name': 'Synthetic Person', 'id_hash': 'a' * 64,
        'id_last4': '0000', 'image_base64': 'fixture', 'consent_obtained': True, 'token': 'not-valid'})
    assert response.status_code == 403
    assert sql('select count(*) from registration_requests') == [(0,)]


def test_registration_approval_preserves_consent_and_audit(client):
    sql("insert into registration_requests(request_id,display_name,id_hash,id_last4,embedding,consent_reference) values(%s,%s,%s,%s,%s::jsonb,%s)",
        ('registration-fixture', 'Synthetic Person', 'a' * 64, '0000', '[1,0]', 'synthetic-consent'))
    response = client.post('/v1/registrations/registration-fixture/decision', json={'action': 'approve'})
    assert response.status_code == 200
    assert response.json()['status'] == 'approved'
    assert sql('select consent_obtained, consent_reference from subjects') == [(True, 'synthetic-consent')]
    assert client.post('/v1/registrations/registration-fixture/decision', json={'action': 'approve'}).status_code == 409


def test_event_review_updates_owned_state_and_audit(client):
    main._record_event('camera-fixture', None, None, 'unknown_face')
    event = client.get('/v1/events').json()[0]
    response = client.post('/v1/events/' + event['event_id'] + '/review', json={'status': 'dismissed', 'note': 'Synthetic review'})
    assert response.json()['review_status'] == 'dismissed'
    assert sql('select review_status from events') == [('dismissed',)]
    assert ('event.reviewed',) in sql('select action from audit_log')


def test_invalid_event_review_is_rejected(client):
    assert client.post('/v1/events/absent/review', json={'status': 'unreviewed-arbitrary'}).status_code == 400


def test_expired_subjects_are_removed_and_retention_is_audited(client, engine):
    enroll(client)
    sql("update subjects set created_at=now()-interval '40 days'")
    main._cleanup_last = 0
    main._cleanup_expired()
    assert sql('select count(*) from subjects') == [(0,)]
    assert ('subject.retention_expired',) in sql('select action from audit_log')


def test_missing_snapshot_is_a_truthful_not_found(client):
    assert client.get('/v1/events/absent/snapshot').status_code == 404


def test_local_dashboard_and_openapi_are_generated_from_actual_source(client):
    assert client.get('/').status_code == 200
    assert client.get('/v1/dashboard').status_code == 200
    assert '/v1/faces/enroll' in client.get('/openapi.json').json()['paths']
