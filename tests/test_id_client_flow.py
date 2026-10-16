from app import main


def handoff(**overrides):
    body = {
        "schema_ref": "codestra.document.face-id-handoff/v1",
        "scan_id": "dscan_test12345",
        "tenant_id": "tenant-a",
        "ready": True,
        "status": "confirmed",
        "document": {
            "document_type": "driver_license",
            "country": "DO",
            "number_last4": "9999",
            "document_hash": "hmac-sha256:" + "a" * 64,
        },
        "subject": {
            "given_names": "QA",
            "surnames": "CLIENT",
            "full_name": "QA CLIENT",
            "date_of_birth": "2000-01-01",
            "sex": "M",
        },
        "portrait_detected": True,
        "portrait_side": "front",
        "front_image_sha256": "b" * 64,
        "back_image_sha256": None,
        "operator_ref": "qa",
    }
    body.update(overrides)
    return body


def test_confirmed_document_handoff_creates_client_without_ocr(client):
    response = client.post("/v1/clients/from-document-handoff", json=handoff())
    assert response.status_code == 200, response.text
    payload = response.json()
    client_id = payload["client_id"]
    assert payload["display_name"] == "QA CLIENT"
    assert payload["document_last4"] == "9999"
    assert payload["source"] == "document-intelligence"

    got = client.get(f"/v1/clients/{client_id}")
    assert got.status_code == 200
    record = got.json()
    assert record["document_type"] == "driver_license"
    assert record["document_last4"] == "9999"
    assert record["source"] == "document-intelligence"
    assert record["attributes"]["document_scan_ref"] == "dscan_test12345"
    assert record["attributes"]["document_tenant_ref"] == "tenant-a"
    assert "document_number" not in record["attributes"]
    assert record["face_enrolled"] is False


def test_handoff_must_be_confirmed_and_ready(client):
    body = handoff(status="pending_review", ready=False)
    response = client.post("/v1/clients/from-document-handoff", json=body)
    assert response.status_code == 409


def test_handoff_schema_is_pinned(client):
    body = handoff(schema_ref="codestra.document.face-id-handoff/v2")
    response = client.post("/v1/clients/from-document-handoff", json=body)
    assert response.status_code == 422


def test_duplicate_document_hash_cannot_create_second_client(client):
    doc = {
        "document_type": "driver_license",
        "country": "DO",
        "number_last4": "1111",
        "document_hash": "hmac-sha256:" + "c" * 64,
    }
    first = handoff(client_id="client-one", scan_id="dscan_dup11111", document=doc)
    second = handoff(client_id="client-two", scan_id="dscan_dup22222", document=doc)
    assert client.post("/v1/clients/from-document-handoff", json=first).status_code == 200
    response = client.post("/v1/clients/from-document-handoff", json=second)
    assert response.status_code == 409


def test_face_enrollment_requires_explicit_consent(client):
    response = client.post(
        "/v1/clients/not-found/face-enrollment",
        json={
            "image_base64": "x",
            "consent_obtained": False,
            "consent_reference": "qa",
        },
    )
    assert response.status_code == 400


def test_document_handoff_and_clients_are_local_admin_only(lan):
    assert lan.get("/v1/clients").status_code == 403
    assert (
        lan.post("/v1/clients/from-document-handoff", json=handoff()).status_code
        == 403
    )
    assert (
        lan.get(
            "/v1/clients/by-document-scan/dscan_test12345?tenant_ref=tenant-a"
        ).status_code
        == 403
    )


def test_face_id_no_longer_imports_ocr_runtime():
    assert not hasattr(main, "scan_license")


def test_document_handoff_readback_is_tenant_bound(client):
    created = client.post("/v1/clients/from-document-handoff", json=handoff())
    assert created.status_code == 200
    found = client.get(
        "/v1/clients/by-document-scan/dscan_test12345?tenant_ref=tenant-a"
    )
    assert found.status_code == 200
    body = found.json()
    assert body["client_id"] == created.json()["client_id"]
    assert body["id_scan_id"] == "dscan_test12345"
    assert body["attributes"]["document_tenant_ref"] == "tenant-a"

    foreign = client.get(
        "/v1/clients/by-document-scan/dscan_test12345?tenant_ref=tenant-b"
    )
    assert foreign.status_code == 404


def test_document_handoff_readback_missing_is_404(client):
    response = client.get(
        "/v1/clients/by-document-scan/dscan_missing?tenant_ref=tenant-a"
    )
    assert response.status_code == 404
