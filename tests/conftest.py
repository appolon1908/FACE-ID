"""Dedicated ephemeral database only; no app startup, cameras or external engine."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

DATABASE = os.environ.get('DATABASE_URL', '')
parsed = urlsplit(DATABASE)
if parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or not parsed.path.endswith('_test'):
    pytest.exit('Source tests require an explicit loopback-only *_test database', returncode=2)
if 'FACEID_EVENT_DIR' not in os.environ:
    pytest.exit('Source tests require an explicit temporary event directory', returncode=2)

from app import main


def sql(query, params=()):
    with psycopg.connect(DATABASE) as connection:
        cursor = connection.execute(query, params)
        return cursor.fetchall() if cursor.description else None


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('Hardware, worker or external HTTP execution is forbidden in source CI')
    monkeypatch.setattr(main.cv2, 'VideoCapture', forbidden)
    monkeypatch.setattr(main.httpx, 'get', forbidden)
    monkeypatch.setattr(main.httpx, 'post', forbidden)
    monkeypatch.setattr(main, '_worker', forbidden)
    # Tests intentionally do not enter TestClient as a context manager. Any
    # accidental lifespan startup fails instead of launching a worker thread.
    monkeypatch.setattr(main.app.router, 'on_startup', [forbidden])
    monkeypatch.setattr(main, 'EVENT_DIR', str(tmp_path / 'events'))
    monkeypatch.setattr(main, 'REGISTRATION_SECRET', '')
    main._last_events.clear()
    main._latest_jpegs.clear()
    with psycopg.connect(DATABASE) as connection:
        connection.execute('drop schema if exists public cascade')
        connection.execute('create schema public')
    main.init_db()


@pytest.fixture
def client():
    return TestClient(main.app, client=('127.0.0.1', 50000))


@pytest.fixture
def remote():
    return TestClient(main.app, client=('203.0.113.8', 50000))


@pytest.fixture
def engine(monkeypatch):
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        assert url.startswith(main.ENGINE + '/')
        if url.endswith('/v1/embeddings'):
            return httpx.Response(200, json={'embedding': [1.0, 0.0], 'bbox': [1, 2, 3, 4]})
        if url.endswith('/v1/search'):
            gallery = kwargs['json']['gallery']
            return httpx.Response(200, json={'hits': [{'subject_id': gallery[0]['subject_id'], 'match': True, 'score': 0.9}] if gallery else []})
        if url.endswith('/readyz'):
            return httpx.Response(200, json={'ok': True})
        raise AssertionError('Unexpected engine fixture operation')
    monkeypatch.setattr(main.httpx, 'post', request)
    monkeypatch.setattr(main.httpx, 'get', request)
    return calls
