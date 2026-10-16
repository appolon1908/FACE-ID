import os, uuid
import psycopg, pytest
from fastapi.testclient import TestClient

DB_URL=os.environ.get("DATABASE_URL","")
if not DB_URL.rsplit("/",1)[-1].endswith("_test"):
    pytest.exit("refusing to run: DATABASE_URL must point at a dedicated *_test database",returncode=2)
os.environ.setdefault("FACEID_EVENT_DIR","/tmp/faceid-test-events")

from app import main  # noqa: E402

@pytest.fixture(scope="session",autouse=True)
def schema():
    with psycopg.connect(DB_URL) as c:
        c.execute("drop schema if exists public cascade")
        c.execute("create schema public")
    main.init_db()

# The startup hook (camera worker + engine) is intentionally not triggered: no `with TestClient(...)`.
@pytest.fixture
def client():
    return TestClient(main.app,client=("127.0.0.1",50000))

@pytest.fixture
def lan():
    return TestClient(main.app,client=("10.0.0.50",50000))

def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"

def sql(query, params=()):
    with psycopg.connect(DB_URL) as c:
        cur=c.execute(query,params)
        return cur.fetchall() if cur.description else None

@pytest.fixture
def subject():
    sid=uid("subj")
    sql("insert into subjects(subject_id,display_name,embedding,consent_obtained,retention_days) values(%s,'Test Person','[]'::jsonb,true,30)",(sid,))
    return sid

@pytest.fixture
def zone(client):
    zid=uid("zone")
    assert client.post("/v1/zones",json={"zone_id":zid,"name":"Zone "+zid}).status_code==200
    return zid

@pytest.fixture
def camera(client):
    cid=uid("cam")
    assert client.post("/v1/cameras",json={"camera_id":cid,"name":"Cam","host":"192.0.2.1","password_env":"UNUSED_TEST_PASSWORD"}).status_code==200
    return cid

def make_event(event_type="unknown_face", subject_id=None, camera_id=None):
    eid=uid("evt")
    sql("insert into events(event_id,camera_id,subject_id,event_type) values(%s,%s,%s,%s)",(eid,camera_id,subject_id,event_type))
    return eid

def audit_for(target_id):
    return sql("select action,details from audit_log where target_id=%s order by occurred_at",(target_id,))
