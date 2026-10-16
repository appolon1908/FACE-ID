import base64, json, os, re, time, threading, uuid, hashlib, hmac, io, datetime, zoneinfo
from typing import Optional
import cv2, httpx, psycopg
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import qrcode

app=FastAPI(title="Codestra FACE-ID",version="1.1.0")
DB=os.environ["DATABASE_URL"]
ENGINE=os.getenv("RECOGNITION_ENGINE_URL","http://recognition-engine:8080")
EVENT_DIR=os.getenv("FACEID_EVENT_DIR","/data/events")
MATCH_THRESHOLD=float(os.getenv("FACEID_MATCH_THRESHOLD","0.363"))
EVENT_RETENTION_DAYS=int(os.getenv("FACEID_EVENT_RETENTION_DAYS","30"))
REGISTRATION_SECRET=os.environ.get("FACEID_REGISTRATION_SECRET","")
PUBLIC_HOST=os.getenv("FACEID_PUBLIC_HOST","10.0.0.73")
PUBLIC_PORT=int(os.getenv("FACEID_PUBLIC_PORT","8094"))
_cleanup_last=0.0

class Enroll(BaseModel):
    subject_id: str
    display_name: str
    image_base64: str
    consent_obtained: bool
    consent_reference: Optional[str]=None
    retention_days: int=Field(default=365,ge=1,le=3650)
class SearchReq(BaseModel):
    image_base64: str
    threshold: float=0.363
    top_k: int=5
class PublicEnroll(BaseModel):
    full_name: str
    id_hash: str
    id_last4: str
    image_base64: str
    consent_obtained: bool
    consent_text_version: str="2026-09"
    token: str

class RegistrationDecision(BaseModel):
    action: str
    note: Optional[str]=None

class EventReview(BaseModel):
    status: str
    note: Optional[str]=None
    subject_id: Optional[str]=None



class ZoneIn(BaseModel):
    zone_id: str
    name: str
    description: Optional[str]=None
    enabled: bool=True

class AccessPolicyIn(BaseModel):
    policy_id: str
    name: str
    subject_id: Optional[str]=None
    zone_id: str
    allowed: bool=True
    schedule: dict=Field(default_factory=dict)
    enabled: bool=True

class VisitorPassIn(BaseModel):
    pass_id: str
    display_name: str
    host_subject_id: Optional[str]=None
    valid_from: str
    valid_until: str
    registration_request_id: Optional[str]=None
    status: str="active"

class AlertRuleIn(BaseModel):
    rule_id: str
    name: str
    event_type: str
    camera_id: Optional[str]=None
    delivery_channel: str="browser"
    recipient_ref: Optional[str]=None
    enabled: bool=True

class IncidentIn(BaseModel):
    incident_id: str
    title: str
    severity: str="medium"
    status: str="open"
    event_ids: list[str]=Field(default_factory=list)
    notes: Optional[str]=None

class RetentionPolicyIn(BaseModel):
    policy_id: str
    resource_type: str
    days: int=Field(ge=1,le=3650)
    enabled: bool=True

class SubjectLabelsIn(BaseModel):
    labels: list[str]=Field(default_factory=list)

class CameraIn(BaseModel):
    camera_id: str
    name: str
    host: str
    rtsp_path: str="/Streaming/Channels/101"
    username: str="admin"
    password_env: str
    enabled: bool=True

class AccessEvaluateIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    subject_ref: Optional[str]=None
    subject_id: Optional[str]=None
    zone_id: str
    occurred_at: str
    visitor_pass_id: Optional[str]=None

class PresenceEventIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    event_ref: str
    direction: str
    subject_ref: Optional[str]=None
    subject_id: Optional[str]=None
    visitor_pass_id: Optional[str]=None
    event_id: Optional[str]=None
    camera_id: Optional[str]=None
    zone_id: Optional[str]=None
    occurred_at: Optional[str]=None

class UnknownClusterIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    cluster_id: Optional[str]=None
    label: str=Field(min_length=1,max_length=120)
    status: str="open"
    notes: Optional[str]=Field(default=None,max_length=2000)
    owner_ref: Optional[str]=None

class UnknownClusterPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    label: Optional[str]=Field(default=None,min_length=1,max_length=120)
    status: Optional[str]=None
    notes: Optional[str]=Field(default=None,max_length=2000)
    owner_ref: Optional[str]=None

class ClusterEventsIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    event_ids: list[str]=Field(min_length=1,max_length=500)

class CameraZoneIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    camera_id: str
    zone_id: str
    priority: int=Field(default=100,ge=0,le=1000)
    enabled: bool=True
    notes: Optional[str]=Field(default=None,max_length=500)

class CameraZonePatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    priority: Optional[int]=Field(default=None,ge=0,le=1000)
    enabled: Optional[bool]=None
    notes: Optional[str]=Field(default=None,max_length=500)

class ReviewQueueIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    queue_id: str
    name: str=Field(min_length=1,max_length=120)
    description: Optional[str]=Field(default=None,max_length=1000)
    status: str="active"
    default_priority: str="normal"

class ReviewQueuePatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name: Optional[str]=Field(default=None,min_length=1,max_length=120)
    description: Optional[str]=Field(default=None,max_length=1000)
    status: Optional[str]=None
    default_priority: Optional[str]=None

class ReviewItemIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    item_type: str
    item_ref: str
    priority: Optional[str]=None
    assignee_ref: Optional[str]=None
    notes: Optional[str]=Field(default=None,max_length=2000)

class ReviewItemPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    status: Optional[str]=None
    priority: Optional[str]=None
    assignee_ref: Optional[str]=None
    notes: Optional[str]=Field(default=None,max_length=2000)

class WatchlistIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    watchlist_id: str
    name: str=Field(min_length=1,max_length=120)
    category: str
    description: Optional[str]=Field(default=None,max_length=1000)
    status: str="active"

class WatchlistPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name: Optional[str]=Field(default=None,min_length=1,max_length=120)
    category: Optional[str]=None
    description: Optional[str]=Field(default=None,max_length=1000)
    status: Optional[str]=None

class WatchlistMemberIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    subject_ref: Optional[str]=None
    subject_id: Optional[str]=None
    visitor_pass_id: Optional[str]=None
    note: Optional[str]=Field(default=None,max_length=1000)
    added_by_ref: Optional[str]=None
    expires_at: Optional[str]=None

class EnrollmentSessionIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    subject_id: str
    display_name: str=Field(min_length=1,max_length=200)
    consent_obtained: bool
    consent_reference: str=Field(min_length=1,max_length=200)
    retention_days: int=Field(default=365,ge=1,le=3650)
    operator_ref: Optional[str]=None

class EnrollmentImageIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    image_base64: str=Field(min_length=1)
    consent_obtained: bool

class DuplicateResolveIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    resolution: str
    note: Optional[str]=Field(default=None,max_length=2000)
    resolver_ref: Optional[str]=None

class ReembeddingJobsIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    subject_ids: list[str]=Field(min_length=1,max_length=500)
    reason: str=Field(min_length=1,max_length=500)
    requested_by_ref: Optional[str]=None

class ReembeddingCompleteIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    images_base64: list[str]=Field(min_length=1,max_length=10)
    consent_obtained: bool
    consent_reference: Optional[str]=Field(default=None,max_length=200)


class ClientFaceEnrollIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    image_base64: str=Field(min_length=1)
    consent_obtained: bool
    consent_reference: str=Field(min_length=1,max_length=200)
    retention_days: int=Field(default=365,ge=1,le=3650)

class DocumentRefIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    document_type: str
    country: str
    number_last4: Optional[str]=None
    document_hash: Optional[str]=None

class SubjectHintIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    given_names: Optional[str]=None
    surnames: Optional[str]=None
    full_name: Optional[str]=None
    date_of_birth: Optional[str]=None
    sex: Optional[str]=None

class DocumentHandoffIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_ref: str
    scan_id: str
    tenant_id: str
    ready: bool
    status: str
    document: DocumentRefIn
    subject: SubjectHintIn
    portrait_detected: bool=False
    portrait_side: Optional[str]=None
    front_image_sha256: Optional[str]=None
    back_image_sha256: Optional[str]=None
    client_id: Optional[str]=None
    operator_ref: Optional[str]=None


def conn(): return psycopg.connect(DB)
def init_db():
    with conn() as c:
        c.execute("""create table if not exists subjects(subject_id text primary key, display_name text not null, embedding jsonb not null, consent_obtained boolean not null, consent_reference text, retention_days int not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists cameras(camera_id text primary key, name text not null, host text not null, rtsp_path text not null, username text not null, password_env text not null, enabled boolean not null default true, created_at timestamptz not null default now())""")
        c.execute("""create table if not exists events(event_id text primary key, camera_id text, subject_id text, score double precision, event_type text not null, occurred_at timestamptz not null default now(), metadata jsonb not null default '{}'::jsonb)""")
        c.execute("alter table subjects add column if not exists id_country text")
        c.execute("alter table subjects add column if not exists id_type text")
        c.execute("alter table subjects add column if not exists id_hash text")
        c.execute("alter table subjects add column if not exists id_last4 text")
        c.execute("alter table subjects add column if not exists enrollment_source text")
        c.execute("alter table events add column if not exists snapshot_path text")
        c.execute("alter table events add column if not exists review_status text not null default 'pending'")
        c.execute("alter table events add column if not exists reviewed_at timestamptz")
        c.execute("alter table events add column if not exists review_note text")
        c.execute("alter table events add column if not exists reviewed_subject_id text")
        c.execute("""create table if not exists registration_requests(
          request_id text primary key,
          display_name text not null,
          id_country text not null default 'DO',
          id_type text not null default 'cedula',
          id_hash text not null,
          id_last4 text not null,
          embedding jsonb not null,
          consent_reference text not null,
          status text not null default 'pending',
          decision_note text,
          created_at timestamptz not null default now(),
          decided_at timestamptz)""")
        c.execute("create unique index if not exists registration_requests_id_hash_idx on registration_requests(id_hash) where status='pending'")
        c.execute("""create table if not exists audit_log(
          audit_id text primary key,
          actor text not null,
          action text not null,
          target_type text not null,
          target_id text,
          details jsonb not null default '{}'::jsonb,
          occurred_at timestamptz not null default now())""")

        c.execute("""create table if not exists zones(
          zone_id text primary key,
          name text not null,
          description text,
          enabled boolean not null default true,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists access_policies(
          policy_id text primary key,
          name text not null,
          subject_id text,
          zone_id text not null,
          allowed boolean not null default true,
          schedule jsonb not null default '{}'::jsonb,
          enabled boolean not null default true,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists visitor_passes(
          pass_id text primary key,
          display_name text not null,
          host_subject_id text,
          valid_from timestamptz not null,
          valid_until timestamptz not null,
          registration_request_id text,
          status text not null default 'active',
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists alert_rules(
          rule_id text primary key,
          name text not null,
          event_type text not null,
          camera_id text,
          delivery_channel text not null,
          recipient_ref text,
          enabled boolean not null default true,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists incidents(
          incident_id text primary key,
          title text not null,
          severity text not null,
          status text not null,
          event_ids jsonb not null default '[]'::jsonb,
          notes text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists retention_policies(
          policy_id text primary key,
          resource_type text not null unique,
          days int not null,
          enabled boolean not null default true,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists subject_labels(
          subject_id text not null,
          label text not null,
          created_at timestamptz not null default now(),
          primary key(subject_id,label))""")


        c.execute("""create table if not exists id_scan_sessions(
          scan_id text primary key,
          document_type text not null,
          country text not null,
          status text not null default 'scanned',
          fields jsonb not null default '{}'::jsonb,
          document_hash text,
          document_last4 text,
          authority_lookup_hash text,
          warnings jsonb not null default '[]'::jsonb,
          operator_ref text,
          confirmation_note text,
          created_at timestamptz not null default now(),
          confirmed_at timestamptz)""")
        c.execute("""create table if not exists clients(
          client_id text primary key,
          display_name text not null,
          country text not null,
          document_type text not null,
          document_hash text not null unique,
          document_last4 text,
          attributes jsonb not null default '{}'::jsonb,
          id_scan_id text,
          source text not null default 'id-scan',
          subject_id text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists client_subject_links(
          client_id text primary key,
          subject_id text not null unique,
          linked_at timestamptz not null default now())""")
        c.execute("""create table if not exists camera_zones(
          mapping_id text primary key,
          camera_id text not null,
          zone_id text not null,
          priority int not null default 100,
          enabled boolean not null default true,
          notes text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique(camera_id,zone_id))""")
        c.execute("""create table if not exists presence_sessions(
          session_id text primary key,
          subject_kind text not null,
          subject_ref text not null,
          zone_id text not null,
          camera_id text,
          entered_at timestamptz not null,
          exited_at timestamptz,
          enter_event_ref text not null,
          exit_event_ref text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("create unique index if not exists presence_sessions_open_idx on presence_sessions(subject_kind,subject_ref,zone_id) where exited_at is null")
        c.execute("create index if not exists presence_sessions_entered_idx on presence_sessions(entered_at desc)")
        c.execute("""create table if not exists presence_observations(
          event_ref text primary key,
          request_hash text not null,
          direction text not null,
          subject_kind text not null,
          subject_ref text not null,
          zone_id text not null,
          camera_id text,
          event_id text,
          occurred_at timestamptz not null,
          session_id text,
          outcome text not null,
          received_at timestamptz not null default now())""")
        c.execute("""create table if not exists unknown_clusters(
          cluster_id text primary key,
          label text not null,
          status text not null default 'open',
          notes text,
          owner_ref text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists unknown_cluster_events(
          event_id text primary key,
          cluster_id text not null,
          attached_at timestamptz not null default now())""")
        c.execute("create index if not exists unknown_cluster_events_cluster_idx on unknown_cluster_events(cluster_id)")
        c.execute("""create table if not exists review_queues(
          queue_id text primary key,
          name text not null,
          description text,
          status text not null default 'active',
          default_priority text not null default 'normal',
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists review_queue_items(
          item_id text primary key,
          queue_id text not null,
          item_type text not null,
          item_ref text not null,
          status text not null default 'open',
          priority text not null default 'normal',
          assignee_ref text,
          notes text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          resolved_at timestamptz,
          unique(queue_id,item_type,item_ref))""")
        c.execute("""create table if not exists watchlists(
          watchlist_id text primary key,
          name text not null,
          category text not null,
          description text,
          status text not null default 'active',
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now())""")
        c.execute("""create table if not exists watchlist_members(
          member_id text primary key,
          watchlist_id text not null,
          subject_kind text not null,
          subject_ref text not null,
          note text,
          added_by_ref text,
          expires_at timestamptz,
          created_at timestamptz not null default now(),
          unique(watchlist_id,subject_kind,subject_ref))""")
        c.execute("create index if not exists watchlist_members_subject_idx on watchlist_members(subject_kind,subject_ref)")
        c.execute("""create table if not exists recognition_models(
          model_key text primary key,
          provider text not null,
          detector text,
          recognizer text not null,
          metric text,
          model_id text not null,
          model_version text not null,
          model_digest text not null,
          digest_kind text not null,
          embedding_version text not null,
          dimension int,
          first_seen_at timestamptz not null default now(),
          last_seen_at timestamptz not null default now())""")
        for col in ("model_key text","model_id text","model_version text","model_digest text","embedding_version text",
                    "embedding_dim int","embedding_method text","embedding_image_count int","embedded_at timestamptz"):
            c.execute("alter table subjects add column if not exists "+col)
        c.execute("alter table registration_requests add column if not exists model_key text")
        c.execute("""create table if not exists subject_embedding_history(
          history_id text primary key,
          subject_id text not null,
          embedding jsonb not null,
          model_key text,
          embedding_version text,
          embedding_method text,
          reason text not null,
          archived_at timestamptz not null default now())""")
        c.execute("create index if not exists subject_embedding_history_subject_idx on subject_embedding_history(subject_id)")
        c.execute("""create table if not exists enrollment_sessions(
          session_id text primary key,
          subject_id text not null,
          display_name text not null,
          consent_reference text not null,
          retention_days int not null,
          operator_ref text,
          status text not null default 'open',
          subject_existed boolean not null default false,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          expires_at timestamptz not null,
          finalized_at timestamptz)""")
        c.execute("create unique index if not exists enrollment_sessions_open_idx on enrollment_sessions(subject_id) where status='open'")
        c.execute("""create table if not exists enrollment_session_images(
          image_id text primary key,
          session_id text not null,
          seq int not null,
          status text not null,
          reasons jsonb not null default '[]'::jsonb,
          quality jsonb not null default '{}'::jsonb,
          image_sha256 text not null,
          embedding jsonb,
          model_key text,
          created_at timestamptz not null default now(),
          unique(session_id,seq))""")
        c.execute("""create table if not exists duplicate_candidates(
          candidate_id text primary key,
          session_id text not null,
          subject_ref text not null,
          candidate_subject_ref text not null,
          score double precision not null,
          threshold double precision not null,
          embedding_version text,
          version_unverified boolean not null default false,
          status text not null default 'open',
          resolution text,
          note text,
          resolver_ref text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          resolved_at timestamptz,
          unique(session_id,candidate_subject_ref))""")
        c.execute("""create table if not exists reembedding_jobs(
          job_id text primary key,
          subject_id text not null,
          status text not null default 'queued',
          reason text not null,
          requested_by_ref text,
          source_embedding_version text,
          target_embedding_version text not null,
          target_model_key text not null,
          history_id text,
          error text,
          consent_reference text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          completed_at timestamptz)""")
        c.execute("create unique index if not exists reembedding_jobs_queued_idx on reembedding_jobs(subject_id) where status='queued'")
        c.execute("create index if not exists audit_log_occurred_idx on audit_log(occurred_at,audit_id)")

WORKER_INTERVAL=float(os.getenv("FACEID_WORKER_INTERVAL_SECONDS","2"))
EVENT_COOLDOWN=float(os.getenv("FACEID_EVENT_COOLDOWN_SECONDS","15"))
_last_events={}
_latest_jpegs={}
_latest_frame_meta={}
_frame_lock=threading.Lock()

def _gallery():
    with conn() as c:
        rows=c.execute("select subject_id,display_name,embedding from subjects").fetchall()
    return rows

def _audit(action, target_type, target_id=None, details=None, actor="local-admin"):
    with conn() as c:
        c.execute("insert into audit_log(audit_id,actor,action,target_type,target_id,details) values(%s,%s,%s,%s,%s,%s::jsonb)",
                  (str(uuid.uuid4()),actor,action,target_type,target_id,json.dumps(details or {})))

def _cleanup_expired():
    global _cleanup_last
    now=time.time()
    if now-_cleanup_last<3600:
        return
    _cleanup_last=now
    paths=[]
    expired_subjects=[]
    with conn() as c:
        paths=[r[0] for r in c.execute("""select snapshot_path from events
                                          where occurred_at < now() - (%s * interval '1 day')
                                          and snapshot_path is not null""",(EVENT_RETENTION_DAYS,)).fetchall()]
        c.execute("delete from events where occurred_at < now() - (%s * interval '1 day')",(EVENT_RETENTION_DAYS,))
        c.execute("delete from unknown_cluster_events u where not exists (select 1 from events e where e.event_id=u.event_id)")
        expired_subjects=[r[0] for r in c.execute("""select subject_id from subjects
                                                     where created_at + (retention_days * interval '1 day') < now()""").fetchall()]
        for subject_id in expired_subjects:
            _purge_subject_dependents(c,subject_id)
        if expired_subjects:
            c.execute("delete from subjects where subject_id = any(%s)",(expired_subjects,))
        c.execute("delete from subject_embedding_history where archived_at < now() - (%s * interval '1 day')",(EMBEDDING_HISTORY_DAYS,))
        for (session_id,) in c.execute("select session_id from enrollment_sessions where status='open' and expires_at<=now()").fetchall():
            _close_session(c,session_id,"expired")
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    for subject_id in expired_subjects:
        try:
            _audit("subject.retention_expired","subject",subject_id,{"retention_enforced":True},actor="system")
        except Exception:
            pass

def _record_event(camera_id, subject_id, score, event_type, metadata=None, snapshot=None):
    key=(camera_id,subject_id or event_type)
    now=time.time()
    if now-_last_events.get(key,0)<EVENT_COOLDOWN:
        return
    _last_events[key]=now
    event_id=str(uuid.uuid4())
    snapshot_path=None
    if snapshot:
        try:
            os.makedirs(EVENT_DIR,exist_ok=True)
            snapshot_path=os.path.join(EVENT_DIR,event_id+".jpg")
            with open(snapshot_path,"wb") as f:
                f.write(snapshot)
        except Exception:
            snapshot_path=None
    with conn() as c:
        c.execute("insert into events(event_id,camera_id,subject_id,score,event_type,metadata,snapshot_path) values(%s,%s,%s,%s,%s,%s::jsonb,%s)",
                  (event_id,camera_id,subject_id,score,event_type,json.dumps(metadata or {}),snapshot_path))

def _process_camera(row):
    camera_id,name,host,path,user,pwenv,enabled=row
    if not enabled: return
    pw=os.getenv(pwenv)
    if not pw: return
    url=f"rtsp://{user}:{pw}@{host}:554{path}"
    cap=cv2.VideoCapture(url,cv2.CAP_FFMPEG)
    ok,frame=cap.read(); cap.release()
    if not ok or frame is None: return
    ok,jpg=cv2.imencode(".jpg",frame,[int(cv2.IMWRITE_JPEG_QUALITY),82])
    if not ok: return
    with _frame_lock:
        _latest_jpegs[camera_id]=jpg.tobytes()
        _latest_frame_meta[camera_id]={"width":int(frame.shape[1]),"height":int(frame.shape[0]),"updated_at":time.time()}
    b64=base64.b64encode(jpg).decode()
    er=httpx.post(ENGINE+"/v1/embeddings",json={"image_base64":b64},timeout=20)
    if er.status_code==422: return
    if not er.is_success: return
    embedding=er.json()["embedding"]
    rows=_gallery()
    if not rows:
        _record_event(camera_id,None,None,"unknown_face",{"camera_name":name},jpg.tobytes())
        return
    gallery=[{"subject_id":r[0],"embedding":r[2]} for r in rows]
    rr=httpx.post(ENGINE+"/v1/search",json={"embedding":embedding,"gallery":gallery,"threshold":MATCH_THRESHOLD,"top_k":1},timeout=20)
    if not rr.is_success: return
    hits=rr.json().get("hits",[])
    top=hits[0] if hits else None
    if top and top.get("match"):
        _record_event(camera_id,top["subject_id"],top["score"],"recognized_face",{"camera_name":name},jpg.tobytes())
    else:
        _record_event(camera_id,None,top.get("score") if top else None,"unknown_face",{"camera_name":name},jpg.tobytes())

def _worker():
    time.sleep(3)
    while True:
        try:
            _cleanup_expired()
            with conn() as c:
                cameras=c.execute("select camera_id,name,host,rtsp_path,username,password_env,enabled from cameras where enabled=true").fetchall()
            for row in cameras:
                try: _process_camera(row)
                except Exception: pass
        except Exception: pass
        time.sleep(WORKER_INTERVAL)

@app.on_event("startup")
def startup():
    last=None
    for _ in range(30):
        try:
            init_db()
            os.makedirs(EVENT_DIR,exist_ok=True)
            threading.Thread(target=_worker,daemon=True).start()
            return
        except Exception as e:
            last=e; time.sleep(1)
    raise last

def _registration_token(day=None):
    if not REGISTRATION_SECRET:
        raise HTTPException(503,"registration secret is not configured")
    day=day or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    return hmac.new(REGISTRATION_SECRET.encode(),("faceid-registration:"+day).encode(),hashlib.sha256).hexdigest()[:32]

def _valid_registration_token(token:str):
    today=datetime.datetime.now(datetime.timezone.utc)
    for delta in (0,1):
        day=(today-datetime.timedelta(days=delta)).strftime("%Y-%m-%d")
        if hmac.compare_digest(token or "",_registration_token(day)):
            return True
    return False

@app.get("/v1/registration/info")
def registration_info():
    token=_registration_token()
    return {"url":f"http://{PUBLIC_HOST}:{PUBLIC_PORT}/register?token={token}","expires":"daily","country":"DO","id_type":"cedula"}

@app.get("/v1/registration/qr")
def registration_qr():
    token=_registration_token()
    url=f"http://{PUBLIC_HOST}:{PUBLIC_PORT}/register?token={token}"
    qr=qrcode.QRCode(version=None,box_size=8,border=3,error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url); qr.make(fit=True)
    img=qr.make_image(fill_color="black",back_color="white")
    buf=io.BytesIO(); img.save(buf,format="PNG")
    return Response(buf.getvalue(),media_type="image/png",headers={"Cache-Control":"no-store"})

@app.middleware("http")
async def local_admin_boundary(request:Request, call_next):
    path=request.url.path
    public = path == "/register" or path == "/v1/public/enroll" or path == "/healthz"
    host = request.client.host if request.client else ""
    local = host in {"127.0.0.1","::1","localhost"} or host.startswith("172.")
    if not public and not local:
        return Response("Local admin access only",status_code=403,media_type="text/plain")
    return await call_next(request)

@app.post("/v1/public/enroll")
def public_enroll(req:PublicEnroll):
    if not _valid_registration_token(req.token):
        raise HTTPException(403,"invalid or expired registration token")
    if not req.consent_obtained:
        raise HTTPException(400,"explicit consent is required")
    name=req.full_name.strip()
    if len(name)<2:
        raise HTTPException(400,"full name is required")
    id_hash=req.id_hash.lower().strip()
    if len(id_hash)!=64 or any(c not in "0123456789abcdef" for c in id_hash):
        raise HTTPException(400,"invalid identity reference")
    if len(req.id_last4)!=4 or not req.id_last4.isdigit():
        raise HTTPException(400,"invalid ID reference")
    er=httpx.post(ENGINE+"/v1/embeddings",json={"image_base64":req.image_base64},timeout=25)
    if not er.is_success:
        raise HTTPException(er.status_code,er.text)
    emb=er.json()["embedding"]
    meta=_try_model_meta()
    request_id="reg-"+uuid.uuid4().hex[:16]
    consent_ref=f"qr-do-self-registration:{req.consent_text_version}"
    with conn() as c:
        if meta: _register_model(c,meta,len(emb))
        existing=c.execute("select request_id,status from registration_requests where id_hash=%s order by created_at desc limit 1",(id_hash,)).fetchone()
        if existing and existing[1]=="pending":
            request_id=existing[0]
            c.execute("""update registration_requests set display_name=%s,id_last4=%s,embedding=%s::jsonb,consent_reference=%s,created_at=now(),
                         model_key=%s where request_id=%s""",(name,req.id_last4,json.dumps(emb),consent_ref,meta and meta["model_key"],request_id))
        else:
            c.execute("""insert into registration_requests(request_id,display_name,id_hash,id_last4,embedding,consent_reference,model_key)
                         values(%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                      (request_id,name,id_hash,req.id_last4,json.dumps(emb),consent_ref,meta and meta["model_key"]))
    _audit("registration.submitted","registration_request",request_id,{"display_name":name,"id_country":"DO","id_type":"cedula","id_last4":req.id_last4},actor="self-registration")
    return {"submitted":True,"request_id":request_id,"status":"pending_review","display_name":name}

@app.get("/register", response_class=HTMLResponse)
def registration_page(token:str=""):
    if not _valid_registration_token(token):
        return HTMLResponse("<h2>Registration link is invalid or expired.</h2>",status_code=403)
    page=os.path.join(os.path.dirname(__file__),"static","register.html")
    with open(page,"r",encoding="utf-8") as f:
        return HTMLResponse(f.read().replace("__REG_TOKEN__",token),headers={"Cache-Control":"no-store"})

@app.get("/", response_class=HTMLResponse)
def dashboard():
    page=os.path.join(os.path.dirname(__file__),"static","dashboard.html")
    with open(page,"r",encoding="utf-8") as f:
        return HTMLResponse(f.read())

def _camera_row(camera_id:str):
    with conn() as c:
        row=c.execute("select camera_id,name,host,rtsp_path,username,password_env,enabled from cameras where camera_id=%s",(camera_id,)).fetchone()
    if not row: raise HTTPException(404,"camera not found")
    return row

def _read_camera_jpeg(camera_id:str):
    with _frame_lock:
        cached=_latest_jpegs.get(camera_id)
        meta=_latest_frame_meta.get(camera_id)
        if cached and meta and time.time()-meta.get("updated_at",0)<5:
            return cached,meta
    _,name,host,path,user,pwenv,enabled=_camera_row(camera_id)
    pw=os.getenv(pwenv)
    if not pw: raise HTTPException(424,f"required secret environment variable {pwenv} is not set")
    url=f"rtsp://{user}:{pw}@{host}:554{path}"
    cap=cv2.VideoCapture(url,cv2.CAP_FFMPEG)
    ok,frame=cap.read(); cap.release()
    if not ok or frame is None: raise HTTPException(502,"unable to read RTSP frame")
    ok,jpg=cv2.imencode(".jpg",frame,[int(cv2.IMWRITE_JPEG_QUALITY),82])
    if not ok: raise HTTPException(500,"unable to encode camera frame")
    data=jpg.tobytes()
    meta={"width":int(frame.shape[1]),"height":int(frame.shape[0]),"updated_at":time.time()}
    with _frame_lock:
        _latest_jpegs[camera_id]=data
        _latest_frame_meta[camera_id]=meta
    return data,meta

@app.get("/v1/cameras/{camera_id}/snapshot")
def camera_snapshot(camera_id:str):
    data,_=_read_camera_jpeg(camera_id)
    return Response(content=data,media_type="image/jpeg",headers={"Cache-Control":"no-store, no-cache, must-revalidate"})

@app.get("/v1/cameras/{camera_id}/stream.mjpg")
def camera_mjpeg(camera_id:str):
    _camera_row(camera_id)
    def frames():
        while True:
            try:
                with _frame_lock:
                    data=_latest_jpegs.get(camera_id)
                if not data:
                    data,_=_read_camera_jpeg(camera_id)
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "+str(len(data)).encode()+b"\r\n\r\n"+data+b"\r\n"
            except Exception:
                pass
            time.sleep(.35)
    return StreamingResponse(frames(),media_type="multipart/x-mixed-replace; boundary=frame",headers={"Cache-Control":"no-store"})

@app.get("/v1/dashboard")
def dashboard_data():
    with conn() as c:
        subjects_count=c.execute("select count(*) from subjects").fetchone()[0]
        events_count=c.execute("select count(*) from events").fetchone()[0]
        recognized_count=c.execute("select count(*) from events where event_type='recognized_face'").fetchone()[0]
        unknown_count=c.execute("select count(*) from events where event_type='unknown_face'").fetchone()[0]
        pending_unknown=c.execute("select count(*) from events where event_type='unknown_face' and review_status='pending'").fetchone()[0]
        pending_registrations=c.execute("select count(*) from registration_requests where status='pending'").fetchone()[0]
        cams=c.execute("select camera_id,name,host,enabled from cameras order by camera_id").fetchall()
        recent=c.execute("""select e.event_id,e.camera_id,e.subject_id,e.score,e.event_type,e.occurred_at,e.metadata,s.display_name,
                                   e.snapshot_path,e.review_status
                            from events e left join subjects s on s.subject_id=e.subject_id
                            order by e.occurred_at desc limit 12""").fetchall()
    with _frame_lock:
        frame_meta=dict(_latest_frame_meta)
    return {"stats":{"subjects":subjects_count,"events":events_count,"recognized":recognized_count,"unknown":unknown_count,
                     "pending_unknown":pending_unknown,"pending_registrations":pending_registrations},
            "cameras":[{"camera_id":r[0],"name":r[1],"host":r[2],"enabled":r[3],"frame":frame_meta.get(r[0])} for r in cams],
            "recent":[{"event_id":r[0],"camera_id":r[1],"subject_id":r[2],"score":r[3],"event_type":r[4],"occurred_at":r[5],
                       "metadata":r[6],"display_name":r[7],"has_snapshot":bool(r[8]),"review_status":r[9]} for r in recent]}

@app.get("/healthz")
def healthz(): return {"ok":True}
@app.get("/readyz")
@app.get("/health/ready")
def readyz():
    try:
        with conn() as c: c.execute("select 1")
        r=httpx.get(ENGINE+"/readyz",timeout=3)
        if not r.is_success: raise RuntimeError("recognition engine not ready")
        return {"ok":True,"database":True,"recognition_engine":True}
    except Exception as e: raise HTTPException(503,str(e))
@app.get("/metrics",response_class=PlainTextResponse)
def metrics(): return PlainTextResponse(generate_latest().decode(),media_type=CONTENT_TYPE_LATEST)
@app.get("/v1/capabilities")
def capabilities(): return {"camera_ingest":["rtsp","onvif"],"recognition":["enroll","verify","search"],"review_workflow":True,"registration_approval":True,"event_snapshots":True,"audit_log":True,"browser_notifications":True,"multi_camera_dashboard":True,"liveness":False,"match_threshold":MATCH_THRESHOLD,"event_retention_days":EVENT_RETENTION_DAYS,"admin_access":"local-only","storage":"postgresql","local_first":True,
    "access_decisions":{"endpoint":"/v1/access/evaluate","decision_only":True,"actuation":False,"fail_closed":True,"audited":True,"schedule_keys":sorted(_SCHEDULE_KEYS)},
    "presence":{"endpoints":["/v1/presence/events","/v1/presence/current","/v1/presence/history"],"idempotency_key":"event_ref","single_open_session_per_subject_zone":True},
    "unknown_clusters":{"endpoint":"/v1/unknown-clusters","identity_assertion":False,"attachable_event_types":["unknown_face"]},
    "camera_zone_mapping":{"endpoint":"/v1/camera-zones","priority":"lower value preferred","stores_camera_credentials":False},
    "review_queues":{"endpoint":"/v1/review-queues","item_types":sorted(_REVIEW_ITEM_TYPES),"priorities":list(_REVIEW_PRIORITIES),"assignee_ref":"opaque","identity_authority":"keycloak","trusts_role_headers":False},
    "watchlists":{"endpoint":"/v1/watchlists","categories":list(_WATCHLIST_CATEGORIES),"member_kinds":["subject","visitor_pass"],"identity_proof":False,"automatic_actions":False,"used_by_access_decisions":False},
    "enrollment_sessions":{"endpoint":"/v1/enrollment-sessions","multi_image":True,"quality_thresholds":_quality_thresholds(),"aggregation_method":_AGGREGATION_METHOD,"images_persisted":False,"liveness":False},
    "duplicate_candidates":{"endpoint":"/v1/duplicate-candidates","threshold":DUPLICATE_THRESHOLD,"recognition_threshold":MATCH_THRESHOLD,"max_candidates":DUPLICATE_MAX_CANDIDATES,"auto_merge":False,"identity_assertion":False},
    "model_registry":{"endpoints":["/v1/models","/v1/models/current","/v1/models/migration-status","/v1/reembedding-jobs"],"registry_read_only":True,"automatic_migration":False,"digest_kind":"descriptor-sha256","embedding_history_retention_days":EMBEDDING_HISTORY_DAYS},
    "document_intelligence":{"ownership":"standalone-external-product","ocr_in_face_id":False,"client_handoff_endpoint":"/v1/clients/from-document-handoff","direct_service_call":False,"middleware_authority":True},
    "client_database":{"endpoint":"/v1/clients","document_handoff":"/v1/clients/from-document-handoff","document_handoff_readback":"/v1/clients/by-document-scan/{scan_id}","face_enrollment":"/v1/clients/{client_id}/face-enrollment","requires_explicit_biometric_consent":True,"document_photo_auto_enrollment":False},
    "audit_export":{"endpoint":"/v1/audit/export","retention_endpoint":"/v1/audit/retention","max_range_days":AUDIT_EXPORT_MAX_DAYS,"max_page_size":1000,"redaction_policy":_REDACTION_POLICY,"integrity":"sha256 record digests + hash chain","signed":bool(AUDIT_EXPORT_HMAC_KEY)},
    "middleware_authority":"Caddy -> Kong -> Middleware V3 :8095 -> service API"}

@app.post("/v1/clients/from-document-handoff")
def create_client_from_document_handoff(req:DocumentHandoffIn):
    if req.schema_ref!="codestra.document.face-id-handoff/v1":
        raise HTTPException(422,"unsupported document handoff schema")
    if not req.ready or req.status!="confirmed":
        raise HTTPException(409,"document handoff must be confirmed and ready")
    doc_hash=(req.document.document_hash or "").strip()
    last4=(req.document.number_last4 or "").strip()
    if not doc_hash or len(doc_hash)>160:
        raise HTTPException(422,"document hash reference is required")
    if last4 and (len(last4)!=4 or not last4.isdigit()):
        raise HTTPException(422,"document last4 must contain four digits")
    full_name=(req.subject.full_name or "").strip()
    if not full_name:
        full_name=" ".join(x for x in [(req.subject.given_names or "").strip(),(req.subject.surnames or "").strip()] if x).strip()
    if len(full_name)<2:
        raise HTTPException(422,"reviewed subject name is required")
    attrs={
        "given_names":req.subject.given_names,
        "surnames":req.subject.surnames,
        "full_name":full_name,
        "date_of_birth":req.subject.date_of_birth,
        "sex":req.subject.sex,
        "document_scan_ref":req.scan_id,
        "document_tenant_ref":req.tenant_id,
        "portrait_detected":req.portrait_detected,
        "portrait_side":req.portrait_side,
    }
    client_id=(req.client_id or ("doc-"+hashlib.sha256((req.tenant_id+"|"+req.scan_id).encode()).hexdigest()[:20])).strip()
    if not client_id:
        raise HTTPException(422,"client_id is invalid")
    with conn() as c:
        existing=c.execute("select client_id from clients where document_hash=%s",(doc_hash,)).fetchone()
        if existing and existing[0]!=client_id:
            raise HTTPException(409,"a client already exists for this document")
        c.execute("""insert into clients(client_id,display_name,country,document_type,document_hash,document_last4,
                     attributes,id_scan_id,source) values(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'document-intelligence')
                     on conflict(client_id) do update set display_name=excluded.display_name,
                     document_last4=excluded.document_last4,attributes=excluded.attributes,id_scan_id=excluded.id_scan_id,
                     source='document-intelligence',updated_at=now()""",
                  (client_id,full_name,req.document.country,req.document.document_type,doc_hash,last4 or None,
                   json.dumps(attrs),req.scan_id))
    _audit("client.created_from_document_handoff","client",client_id,{
        "scan_ref":req.scan_id,"tenant_ref":req.tenant_id,"document_last4":last4 or None,
        "operator_ref":req.operator_ref,"source":"document-intelligence"})
    return {"client_id":client_id,"display_name":full_name,"document_last4":last4 or None,
            "face_enrolled":False,"source":"document-intelligence"}

@app.get("/v1/clients")
def list_clients(limit:int=200):
    limit=max(1,min(limit,1000))
    with conn() as c:
        rows=c.execute("""select client_id,display_name,country,document_type,document_last4,attributes,id_scan_id,
                          source,subject_id,created_at,updated_at from clients order by created_at desc limit %s""",(limit,)).fetchall()
    return [{"client_id":r[0],"display_name":r[1],"country":r[2],"document_type":r[3],"document_last4":r[4],
             "attributes":r[5],"id_scan_id":r[6],"source":r[7],"subject_id":r[8],
             "face_enrolled":bool(r[8]),"created_at":r[9],"updated_at":r[10]} for r in rows]

@app.get("/v1/clients/by-document-scan/{scan_id}")
def get_client_by_document_scan(scan_id:str, tenant_ref:str):
    with conn() as c:
        r=c.execute("""select client_id,display_name,country,document_type,document_last4,attributes,id_scan_id,
                       source,subject_id,created_at,updated_at from clients
                       where id_scan_id=%s and source='document-intelligence'
                         and attributes->>'document_tenant_ref'=%s""",(scan_id,tenant_ref)).fetchone()
    if not r: raise HTTPException(404,"client not found")
    return {"client_id":r[0],"display_name":r[1],"country":r[2],"document_type":r[3],"document_last4":r[4],
            "attributes":r[5],"id_scan_id":r[6],"source":r[7],"subject_id":r[8],
            "face_enrolled":bool(r[8]),"created_at":r[9],"updated_at":r[10]}

@app.get("/v1/clients/{client_id}")
def get_client(client_id:str):
    with conn() as c:
        r=c.execute("""select client_id,display_name,country,document_type,document_last4,attributes,id_scan_id,
                       source,subject_id,created_at,updated_at from clients where client_id=%s""",(client_id,)).fetchone()
    if not r: raise HTTPException(404,"client not found")
    return {"client_id":r[0],"display_name":r[1],"country":r[2],"document_type":r[3],"document_last4":r[4],
            "attributes":r[5],"id_scan_id":r[6],"source":r[7],"subject_id":r[8],
            "face_enrolled":bool(r[8]),"created_at":r[9],"updated_at":r[10]}

@app.post("/v1/clients/{client_id}/face-enrollment")
def enroll_client_face(client_id:str, req:ClientFaceEnrollIn):
    if not req.consent_obtained:
        raise HTTPException(400,"explicit biometric enrollment consent is required")
    with conn() as c:
        row=c.execute("select display_name,subject_id from clients where client_id=%s",(client_id,)).fetchone()
    if not row: raise HTTPException(404,"client not found")
    display_name,linked_subject=row
    subject_id=linked_subject or ("client-"+client_id)
    er=httpx.post(ENGINE+"/v1/embeddings",json={"image_base64":req.image_base64},timeout=20)
    if not er.is_success: raise HTTPException(er.status_code,er.text)
    payload=er.json()
    emb=payload["embedding"]
    meta=_try_model_meta()
    with conn() as c:
        if meta: _register_model(c,meta,len(emb))
        _archive_embedding(c,subject_id,"client_face_enrollment")
        c.execute("""insert into subjects(subject_id,display_name,embedding,consent_obtained,consent_reference,retention_days,
                     enrollment_source) values(%s,%s,%s::jsonb,true,%s,%s,'client-live-enrollment')
                     on conflict(subject_id) do update set display_name=excluded.display_name,embedding=excluded.embedding,
                     consent_obtained=true,consent_reference=excluded.consent_reference,retention_days=excluded.retention_days,
                     enrollment_source='client-live-enrollment',updated_at=now()""",
                  (subject_id,display_name,json.dumps(emb),req.consent_reference,req.retention_days))
        _stamp_subject(c,subject_id,meta,len(emb),"single-image",1)
        c.execute("""insert into client_subject_links(client_id,subject_id) values(%s,%s)
                     on conflict(client_id) do update set subject_id=excluded.subject_id,linked_at=now()""",(client_id,subject_id))
        c.execute("update clients set subject_id=%s,updated_at=now() where client_id=%s",(subject_id,client_id))
    _audit("client.face_enrolled","client",client_id,{"subject_id":subject_id,"consent_reference":req.consent_reference})
    return {"client_id":client_id,"subject_id":subject_id,"display_name":display_name,"face_enrolled":True,
            "notice":"Face enrollment used the supplied consented capture, not the ID-card portrait."}

@app.post("/v1/faces/enroll")
def enroll(req:Enroll):
    if not req.consent_obtained: raise HTTPException(400,"explicit enrollment consent is required")
    er=httpx.post(ENGINE+"/v1/embeddings",json={"image_base64":req.image_base64},timeout=20)
    if not er.is_success: raise HTTPException(er.status_code,er.text)
    emb=er.json()["embedding"]
    meta=_try_model_meta()
    with conn() as c:
        if meta: _register_model(c,meta,len(emb))
        _archive_embedding(c,req.subject_id,"manual_enroll")
        c.execute("""insert into subjects(subject_id,display_name,embedding,consent_obtained,consent_reference,retention_days) values(%s,%s,%s::jsonb,%s,%s,%s) on conflict(subject_id) do update set display_name=excluded.display_name,embedding=excluded.embedding,consent_obtained=excluded.consent_obtained,consent_reference=excluded.consent_reference,retention_days=excluded.retention_days,updated_at=now()""",(req.subject_id,req.display_name,json.dumps(emb),req.consent_obtained,req.consent_reference,req.retention_days))
        _stamp_subject(c,req.subject_id,meta,len(emb),"single-image",1)
    _audit("subject.enrolled","subject",req.subject_id,{"display_name":req.display_name,"source":"manual"})
    return {"subject_id":req.subject_id,"display_name":req.display_name,"enrolled":True}
@app.delete("/v1/faces/{subject_id}")
def delete_face(subject_id:str):
    with conn() as c:
        _purge_subject_dependents(c,subject_id)
        c.execute("delete from subjects where subject_id=%s",(subject_id,))
    _audit("subject.deleted","subject",subject_id)
    return {"deleted":True,"subject_id":subject_id}
@app.post("/v1/faces/detect")
def detect(req:SearchReq):
    er=httpx.post(ENGINE+"/v1/embeddings",json={"image_base64":req.image_base64},timeout=20)
    if not er.is_success: raise HTTPException(er.status_code,er.text)
    return {"face_detected":True,"bbox":er.json().get("bbox")}
@app.post("/v1/faces/search")
def search(req:SearchReq):
    with conn() as c: rows=c.execute("select subject_id,display_name,embedding from subjects").fetchall()
    gallery=[{"subject_id":r[0],"embedding":r[2]} for r in rows]
    rr=httpx.post(ENGINE+"/v1/search",json={"image_base64":req.image_base64,"gallery":gallery,"threshold":req.threshold,"top_k":req.top_k},timeout=20)
    if not rr.is_success: raise HTTPException(rr.status_code,rr.text)
    names={r[0]:r[1] for r in rows}; out=rr.json()
    for h in out["hits"]: h["display_name"]=names.get(h["subject_id"])
    return out
@app.post("/v1/faces/verify")
def verify(req:SearchReq):
    out=search(req); top=out["hits"][0] if out["hits"] else None
    return {"recognized":bool(top and top["match"]),"best":top}
@app.get("/v1/subjects")
def subjects():
    with conn() as c:
        rows=c.execute("select subject_id,display_name,consent_obtained,consent_reference,retention_days,created_at,updated_at,id_country,id_type,id_last4,enrollment_source,model_key,embedding_version,embedding_method,embedded_at from subjects order by display_name").fetchall()
    return [{"subject_id":r[0],"display_name":r[1],"consent_obtained":r[2],"consent_reference":r[3],"retention_days":r[4],
             "created_at":r[5],"updated_at":r[6],"id_country":r[7],"id_type":r[8],"id_last4":r[9],"enrollment_source":r[10],
             "model_key":r[11],"embedding_version":r[12],"embedding_method":r[13],"embedded_at":r[14]} for r in rows]

@app.get("/v1/registrations")
def registration_requests(status:str="pending", limit:int=200):
    limit=max(1,min(limit,1000))
    with conn() as c:
        rows=c.execute("""select request_id,display_name,id_country,id_type,id_last4,consent_reference,status,decision_note,created_at,decided_at
                          from registration_requests
                          where (%s='all' or status=%s)
                          order by created_at desc limit %s""",(status,status,limit)).fetchall()
    return [{"request_id":r[0],"display_name":r[1],"id_country":r[2],"id_type":r[3],"id_last4":r[4],
             "consent_reference":r[5],"status":r[6],"decision_note":r[7],"created_at":r[8],"decided_at":r[9]} for r in rows]

@app.post("/v1/registrations/{request_id}/decision")
def registration_decision(request_id:str, req:RegistrationDecision):
    action=req.action.lower().strip()
    if action not in {"approve","reject"}:
        raise HTTPException(400,"action must be approve or reject")
    with conn() as c:
        row=c.execute("""select display_name,id_hash,id_last4,embedding,consent_reference,status,model_key
                         from registration_requests where request_id=%s""",(request_id,)).fetchone()
        if not row:
            raise HTTPException(404,"registration request not found")
        if row[5]!="pending":
            raise HTTPException(409,"registration request already decided")
        name,id_hash,id_last4,embedding,consent_ref,_,model_key=row
        if action=="approve":
            subject_id="do-"+id_hash[:16]
            _archive_embedding(c,subject_id,"registration_approved:"+request_id)
            c.execute("""insert into subjects(subject_id,display_name,embedding,consent_obtained,consent_reference,retention_days,
                         id_country,id_type,id_hash,id_last4,enrollment_source)
                         values(%s,%s,%s::jsonb,true,%s,365,'DO','cedula',%s,%s,'qr-self-registration')
                         on conflict(subject_id) do update set display_name=excluded.display_name,embedding=excluded.embedding,
                         consent_obtained=true,consent_reference=excluded.consent_reference,updated_at=now(),
                         id_country='DO',id_type='cedula',id_hash=excluded.id_hash,id_last4=excluded.id_last4,
                         enrollment_source='qr-self-registration'""",
                      (subject_id,name,json.dumps(embedding),consent_ref,id_hash,id_last4))
            _stamp_subject(c,subject_id,_model_from_registry(c,model_key),len(embedding),"single-image",1)
            c.execute("update registration_requests set status='approved',decision_note=%s,decided_at=now() where request_id=%s",(req.note,request_id))
            _audit("registration.approved","registration_request",request_id,{"subject_id":subject_id,"display_name":name})
            return {"request_id":request_id,"status":"approved","subject_id":subject_id,"display_name":name}
        c.execute("update registration_requests set status='rejected',decision_note=%s,decided_at=now() where request_id=%s",(req.note,request_id))
    _audit("registration.rejected","registration_request",request_id,{"display_name":name})
    return {"request_id":request_id,"status":"rejected"}

@app.get("/v1/audit")
def audit_log(limit:int=200):
    limit=max(1,min(limit,1000))
    with conn() as c:
        rows=c.execute("""select audit_id,actor,action,target_type,target_id,details,occurred_at
                          from audit_log order by occurred_at desc limit %s""",(limit,)).fetchall()
    return [{"audit_id":r[0],"actor":r[1],"action":r[2],"target_type":r[3],"target_id":r[4],"details":r[5],"occurred_at":r[6]} for r in rows]


@app.get("/v1/zones")
def list_zones():
    with conn() as c:
        rows=c.execute("select zone_id,name,description,enabled,created_at,updated_at from zones order by name").fetchall()
    return [{"zone_id":r[0],"name":r[1],"description":r[2],"enabled":r[3],"created_at":r[4],"updated_at":r[5]} for r in rows]

@app.post("/v1/zones")
def save_zone(req:ZoneIn):
    with conn() as c:
        c.execute("""insert into zones(zone_id,name,description,enabled) values(%s,%s,%s,%s)
                     on conflict(zone_id) do update set name=excluded.name,description=excluded.description,
                     enabled=excluded.enabled,updated_at=now()""",(req.zone_id,req.name,req.description,req.enabled))
    _audit("zone.saved","zone",req.zone_id,{"name":req.name,"enabled":req.enabled})
    return {"zone_id":req.zone_id,"saved":True}

@app.get("/v1/access-policies")
def list_access_policies():
    with conn() as c:
        rows=c.execute("""select policy_id,name,subject_id,zone_id,allowed,schedule,enabled,created_at,updated_at
                          from access_policies order by name""").fetchall()
    return [{"policy_id":r[0],"name":r[1],"subject_id":r[2],"zone_id":r[3],"allowed":r[4],
             "schedule":r[5],"enabled":r[6],"created_at":r[7],"updated_at":r[8]} for r in rows]

@app.post("/v1/access-policies")
def save_access_policy(req:AccessPolicyIn):
    err=_schedule_error(req.schedule)
    if err:
        raise HTTPException(400,err)
    with conn() as c:
        if not c.execute("select 1 from zones where zone_id=%s",(req.zone_id,)).fetchone():
            raise HTTPException(400,"zone_id does not exist")
        if req.subject_id and not c.execute("select 1 from subjects where subject_id=%s",(req.subject_id,)).fetchone():
            raise HTTPException(400,"subject_id does not exist")
        c.execute("""insert into access_policies(policy_id,name,subject_id,zone_id,allowed,schedule,enabled)
                     values(%s,%s,%s,%s,%s,%s::jsonb,%s)
                     on conflict(policy_id) do update set name=excluded.name,subject_id=excluded.subject_id,
                     zone_id=excluded.zone_id,allowed=excluded.allowed,schedule=excluded.schedule,
                     enabled=excluded.enabled,updated_at=now()""",
                  (req.policy_id,req.name,req.subject_id,req.zone_id,req.allowed,json.dumps(req.schedule),req.enabled))
    _audit("access_policy.saved","access_policy",req.policy_id,{"zone_id":req.zone_id,"allowed":req.allowed})
    return {"policy_id":req.policy_id,"saved":True}

@app.get("/v1/visitor-passes")
def list_visitor_passes():
    with conn() as c:
        rows=c.execute("""select pass_id,display_name,host_subject_id,valid_from,valid_until,registration_request_id,status,
                          created_at,updated_at from visitor_passes order by created_at desc""").fetchall()
    return [{"pass_id":r[0],"display_name":r[1],"host_subject_id":r[2],"valid_from":r[3],"valid_until":r[4],
             "registration_request_id":r[5],"status":r[6],"created_at":r[7],"updated_at":r[8]} for r in rows]

@app.post("/v1/visitor-passes")
def save_visitor_pass(req:VisitorPassIn):
    try:
        start=datetime.datetime.fromisoformat(req.valid_from.replace("Z","+00:00"))
        end=datetime.datetime.fromisoformat(req.valid_until.replace("Z","+00:00"))
    except ValueError:
        raise HTTPException(400,"valid_from and valid_until must be ISO-8601 timestamps")
    if end <= start:
        raise HTTPException(400,"valid_until must be after valid_from")
    with conn() as c:
        if req.host_subject_id and not c.execute("select 1 from subjects where subject_id=%s",(req.host_subject_id,)).fetchone():
            raise HTTPException(400,"host_subject_id does not exist")
        c.execute("""insert into visitor_passes(pass_id,display_name,host_subject_id,valid_from,valid_until,registration_request_id,status)
                     values(%s,%s,%s,%s,%s,%s,%s)
                     on conflict(pass_id) do update set display_name=excluded.display_name,
                     host_subject_id=excluded.host_subject_id,valid_from=excluded.valid_from,valid_until=excluded.valid_until,
                     registration_request_id=excluded.registration_request_id,status=excluded.status,updated_at=now()""",
                  (req.pass_id,req.display_name,req.host_subject_id,start,end,req.registration_request_id,req.status))
    _audit("visitor_pass.saved","visitor_pass",req.pass_id,{"display_name":req.display_name,"status":req.status})
    return {"pass_id":req.pass_id,"saved":True}

@app.get("/v1/alert-rules")
def list_alert_rules():
    with conn() as c:
        rows=c.execute("""select rule_id,name,event_type,camera_id,delivery_channel,recipient_ref,enabled,created_at,updated_at
                          from alert_rules order by name""").fetchall()
    return [{"rule_id":r[0],"name":r[1],"event_type":r[2],"camera_id":r[3],"delivery_channel":r[4],
             "recipient_ref":r[5],"enabled":r[6],"created_at":r[7],"updated_at":r[8]} for r in rows]

@app.post("/v1/alert-rules")
def save_alert_rule(req:AlertRuleIn):
    allowed_channels={"browser","email","sms","webhook"}
    if req.delivery_channel not in allowed_channels:
        raise HTTPException(400,"unsupported delivery_channel")
    with conn() as c:
        if req.camera_id and not c.execute("select 1 from cameras where camera_id=%s",(req.camera_id,)).fetchone():
            raise HTTPException(400,"camera_id does not exist")
        c.execute("""insert into alert_rules(rule_id,name,event_type,camera_id,delivery_channel,recipient_ref,enabled)
                     values(%s,%s,%s,%s,%s,%s,%s)
                     on conflict(rule_id) do update set name=excluded.name,event_type=excluded.event_type,
                     camera_id=excluded.camera_id,delivery_channel=excluded.delivery_channel,
                     recipient_ref=excluded.recipient_ref,enabled=excluded.enabled,updated_at=now()""",
                  (req.rule_id,req.name,req.event_type,req.camera_id,req.delivery_channel,req.recipient_ref,req.enabled))
    _audit("alert_rule.saved","alert_rule",req.rule_id,{"event_type":req.event_type,"channel":req.delivery_channel})
    return {"rule_id":req.rule_id,"saved":True}

@app.get("/v1/incidents")
def list_incidents():
    with conn() as c:
        rows=c.execute("""select incident_id,title,severity,status,event_ids,notes,created_at,updated_at
                          from incidents order by updated_at desc""").fetchall()
    return [{"incident_id":r[0],"title":r[1],"severity":r[2],"status":r[3],"event_ids":r[4],
             "notes":r[5],"created_at":r[6],"updated_at":r[7]} for r in rows]

@app.post("/v1/incidents")
def save_incident(req:IncidentIn):
    if req.severity not in {"low","medium","high","critical"}:
        raise HTTPException(400,"unsupported severity")
    if req.status not in {"open","investigating","resolved","closed"}:
        raise HTTPException(400,"unsupported status")
    with conn() as c:
        if req.event_ids:
            found={r[0] for r in c.execute("select event_id from events where event_id = any(%s)",(req.event_ids,)).fetchall()}
            missing=[x for x in req.event_ids if x not in found]
            if missing:
                raise HTTPException(400,"one or more event_ids do not exist")
        c.execute("""insert into incidents(incident_id,title,severity,status,event_ids,notes)
                     values(%s,%s,%s,%s,%s::jsonb,%s)
                     on conflict(incident_id) do update set title=excluded.title,severity=excluded.severity,
                     status=excluded.status,event_ids=excluded.event_ids,notes=excluded.notes,updated_at=now()""",
                  (req.incident_id,req.title,req.severity,req.status,json.dumps(req.event_ids),req.notes))
    _audit("incident.saved","incident",req.incident_id,{"severity":req.severity,"status":req.status})
    return {"incident_id":req.incident_id,"saved":True}

@app.get("/v1/retention-policies")
def list_retention_policies():
    with conn() as c:
        rows=c.execute("""select policy_id,resource_type,days,enabled,created_at,updated_at
                          from retention_policies order by resource_type""").fetchall()
    return [{"policy_id":r[0],"resource_type":r[1],"days":r[2],"enabled":r[3],"created_at":r[4],"updated_at":r[5]} for r in rows]

@app.post("/v1/retention-policies")
def save_retention_policy(req:RetentionPolicyIn):
    allowed={"events","event_snapshots","visitors","incidents","audit"}
    if req.resource_type not in allowed:
        raise HTTPException(400,"unsupported resource_type")
    with conn() as c:
        c.execute("""insert into retention_policies(policy_id,resource_type,days,enabled) values(%s,%s,%s,%s)
                     on conflict(policy_id) do update set resource_type=excluded.resource_type,days=excluded.days,
                     enabled=excluded.enabled,updated_at=now()""",(req.policy_id,req.resource_type,req.days,req.enabled))
    _audit("retention_policy.saved","retention_policy",req.policy_id,{"resource_type":req.resource_type,"days":req.days})
    return {"policy_id":req.policy_id,"saved":True}

@app.get("/v1/subjects/{subject_id}/labels")
def get_subject_labels(subject_id:str):
    with conn() as c:
        if not c.execute("select 1 from subjects where subject_id=%s",(subject_id,)).fetchone():
            raise HTTPException(404,"subject not found")
        rows=c.execute("select label,created_at from subject_labels where subject_id=%s order by label",(subject_id,)).fetchall()
    return [{"label":r[0],"created_at":r[1]} for r in rows]

@app.put("/v1/subjects/{subject_id}/labels")
def set_subject_labels(subject_id:str, req:SubjectLabelsIn):
    labels=sorted({x.strip().lower() for x in req.labels if x.strip()})
    if any(len(x)>64 for x in labels):
        raise HTTPException(400,"labels must be 64 characters or fewer")
    with conn() as c:
        if not c.execute("select 1 from subjects where subject_id=%s",(subject_id,)).fetchone():
            raise HTTPException(404,"subject not found")
        c.execute("delete from subject_labels where subject_id=%s",(subject_id,))
        for label in labels:
            c.execute("insert into subject_labels(subject_id,label) values(%s,%s)",(subject_id,label))
    _audit("subject.labels_updated","subject",subject_id,{"labels":labels})
    return {"subject_id":subject_id,"labels":labels}

@app.get("/v1/privacy/subjects/{subject_id}/export")
def privacy_export(subject_id:str):
    with conn() as c:
        s=c.execute("""select subject_id,display_name,consent_obtained,consent_reference,retention_days,created_at,updated_at,
                       id_country,id_type,id_last4,enrollment_source from subjects where subject_id=%s""",(subject_id,)).fetchone()
        if not s:
            raise HTTPException(404,"subject not found")
        labels=[r[0] for r in c.execute("select label from subject_labels where subject_id=%s order by label",(subject_id,)).fetchall()]
        events=c.execute("""select event_id,camera_id,score,event_type,occurred_at,review_status
                            from events where subject_id=%s or reviewed_subject_id=%s order by occurred_at desc limit 1000""",
                         (subject_id,subject_id)).fetchall()
        presence=c.execute("""select session_id,zone_id,camera_id,entered_at,exited_at from presence_sessions
                              where subject_kind='subject' and subject_ref=%s order by entered_at desc limit 1000""",(subject_id,)).fetchall()
        extra=_privacy_export_extra(c,subject_id)
    _audit("privacy.exported","subject",subject_id)
    return {"subject":{"subject_id":s[0],"display_name":s[1],"consent_obtained":s[2],"consent_reference":s[3],
            "retention_days":s[4],"created_at":s[5],"updated_at":s[6],"id_country":s[7],"id_type":s[8],
            "id_last4":s[9],"enrollment_source":s[10],"labels":labels},
            "events":[{"event_id":e[0],"camera_id":e[1],"score":e[2],"event_type":e[3],"occurred_at":e[4],"review_status":e[5]} for e in events],
            "presence_sessions":[{"session_id":p[0],"zone_id":p[1],"camera_id":p[2],"entered_at":p[3],"exited_at":p[4]} for p in presence],
            **extra}

@app.delete("/v1/privacy/subjects/{subject_id}")
def privacy_delete(subject_id:str):
    snapshot_paths=[]
    with conn() as c:
        exists=c.execute("select 1 from subjects where subject_id=%s",(subject_id,)).fetchone()
        if not exists:
            raise HTTPException(404,"subject not found")
        snapshot_paths=[r[0] for r in c.execute("select snapshot_path from events where subject_id=%s and snapshot_path is not null",(subject_id,)).fetchall()]
        c.execute("delete from subject_labels where subject_id=%s",(subject_id,))
        c.execute("update events set subject_id=null,reviewed_subject_id=null where subject_id=%s or reviewed_subject_id=%s",(subject_id,subject_id))
        c.execute("delete from access_policies where subject_id=%s",(subject_id,))
        c.execute("delete from presence_observations where subject_kind='subject' and subject_ref=%s",(subject_id,))
        c.execute("delete from presence_sessions where subject_kind='subject' and subject_ref=%s",(subject_id,))
        c.execute("update visitor_passes set host_subject_id=null where host_subject_id=%s",(subject_id,))
        _purge_subject_dependents(c,subject_id)
        c.execute("delete from subjects where subject_id=%s",(subject_id,))
    for path in snapshot_paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    _audit("privacy.deleted","subject",subject_id)
    return {"subject_id":subject_id,"deleted":True}

@app.get("/v1/integrations/status")
def integrations_status():
    engine={"ready":False}
    try:
        r=httpx.get(ENGINE+"/readyz",timeout=3)
        engine={"ready":r.is_success,"status_code":r.status_code}
    except Exception:
        pass
    with conn() as c:
        cams=c.execute("select count(*) from cameras where enabled=true").fetchone()[0]
    return {"middleware_authority":"Caddy -> Kong -> Middleware V3 :8095 -> service API",
            "recognition_engine":engine,"enabled_cameras":cams,
            "liveness":{"configured":bool(os.getenv("FACEID_LIVENESS_URL"))},
            "camera_gateway":{"configured":bool(os.getenv("FACEID_CAMERA_GATEWAY_URL"))},
            "postgresql_management":{"configured":bool(os.getenv("FACEID_POSTGRESQL_MANAGEMENT_URL"))}}

@app.post("/v1/cameras")
def camera_add(req:CameraIn):
    with conn() as c:
        c.execute("""insert into cameras(camera_id,name,host,rtsp_path,username,password_env,enabled) values(%s,%s,%s,%s,%s,%s,%s) on conflict(camera_id) do update set name=excluded.name,host=excluded.host,rtsp_path=excluded.rtsp_path,username=excluded.username,password_env=excluded.password_env,enabled=excluded.enabled""",(req.camera_id,req.name,req.host,req.rtsp_path,req.username,req.password_env,req.enabled))
    _audit("camera.saved","camera",req.camera_id,{"name":req.name,"host":req.host,"enabled":req.enabled})
    return {"camera_id":req.camera_id,"saved":True}
@app.get("/v1/cameras")
def camera_list():
    with conn() as c: rows=c.execute("select camera_id,name,host,rtsp_path,username,password_env,enabled from cameras order by camera_id").fetchall()
    return [{"camera_id":r[0],"name":r[1],"host":r[2],"rtsp_path":r[3],"username":r[4],"password_env":r[5],"enabled":r[6]} for r in rows]
@app.delete("/v1/cameras/{camera_id}")
def camera_delete(camera_id:str):
    with conn() as c:
        c.execute("delete from camera_zones where camera_id=%s",(camera_id,))
        c.execute("delete from cameras where camera_id=%s",(camera_id,))
    _audit("camera.deleted","camera",camera_id)
    return {"deleted":True,"camera_id":camera_id}

@app.get("/v1/cameras/{camera_id}/onvif")
def camera_onvif(camera_id:str):
    with conn() as c:
        row=c.execute("select host,username,password_env from cameras where camera_id=%s",(camera_id,)).fetchone()
    if not row: raise HTTPException(404,"camera not found")
    host,user,pwenv=row
    pw=os.getenv(pwenv)
    if not pw: raise HTTPException(424,f"required secret environment variable {pwenv} is not set")
    auth=httpx.DigestAuth(user,pw)
    headers_profiles={"Content-Type":'application/soap+xml; charset=utf-8; action="http://www.onvif.org/ver10/media/wsdl/GetProfiles"'}
    body_profiles='<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><trt:GetProfiles xmlns:trt="http://www.onvif.org/ver10/media/wsdl"/></s:Body></s:Envelope>'
    try:
        rp=httpx.post(f"http://{host}/onvif/Media",content=body_profiles,headers=headers_profiles,auth=auth,timeout=10)
    except Exception as e:
        raise HTTPException(502,f"ONVIF GetProfiles failed: {type(e).__name__}")
    if rp.status_code != 200:
        raise HTTPException(rp.status_code,"ONVIF GetProfiles rejected")
    import xml.etree.ElementTree as ET
    root=ET.fromstring(rp.text)
    ns={"trt":"http://www.onvif.org/ver10/media/wsdl","tt":"http://www.onvif.org/ver10/schema"}
    profiles=[]
    for pr in root.findall(".//trt:Profiles",ns):
        token=pr.attrib.get("token")
        name_el=pr.find("tt:Name",ns)
        enc=pr.find("tt:VideoEncoderConfiguration",ns)
        item={"token":token,"name":name_el.text if name_el is not None else None}
        if enc is not None:
            encname=enc.find("tt:Encoding",ns)
            res=enc.find("tt:Resolution",ns)
            item["encoding"]=encname.text if encname is not None else None
            if res is not None:
                w=res.find("tt:Width",ns); h=res.find("tt:Height",ns)
                item["width"]=int(w.text) if w is not None else None
                item["height"]=int(h.text) if h is not None else None
        uri_body=f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><trt:GetStreamUri xmlns:trt="http://www.onvif.org/ver10/media/wsdl"><trt:StreamSetup><tt:Stream xmlns:tt="http://www.onvif.org/ver10/schema">RTP-Unicast</tt:Stream><tt:Transport xmlns:tt="http://www.onvif.org/ver10/schema"><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup><trt:ProfileToken>{token}</trt:ProfileToken></trt:GetStreamUri></s:Body></s:Envelope>'
        headers_uri={"Content-Type":'application/soap+xml; charset=utf-8; action="http://www.onvif.org/ver10/media/wsdl/GetStreamUri"'}
        ru=httpx.post(f"http://{host}/onvif/Media",content=uri_body,headers=headers_uri,auth=auth,timeout=10)
        if ru.status_code==200:
            rr=ET.fromstring(ru.text)
            uri_el=rr.find(".//tt:Uri",ns)
            if uri_el is not None: item["rtsp_uri"]=uri_el.text
        profiles.append(item)
    return {"camera_id":camera_id,"profiles":profiles}

@app.post("/v1/streams/{camera_id}/test")
def stream_test(camera_id:str):
    with conn() as c: row=c.execute("select host,rtsp_path,username,password_env from cameras where camera_id=%s",(camera_id,)).fetchone()
    if not row: raise HTTPException(404,"camera not found")
    host,path,user,pwenv=row; pw=os.getenv(pwenv)
    if not pw: raise HTTPException(424,f"required secret environment variable {pwenv} is not set")
    url=f"rtsp://{user}:{pw}@{host}:554{path}"
    cap=cv2.VideoCapture(url,cv2.CAP_FFMPEG); ok,frame=cap.read(); cap.release()
    if not ok or frame is None: raise HTTPException(502,"unable to read RTSP frame")
    return {"camera_id":camera_id,"ok":True,"width":int(frame.shape[1]),"height":int(frame.shape[0])}
@app.get("/v1/events/{event_id}/snapshot")
def event_snapshot(event_id:str):
    with conn() as c:
        row=c.execute("select snapshot_path from events where event_id=%s",(event_id,)).fetchone()
    if not row:
        raise HTTPException(404,"event not found")
    path=row[0]
    if not path or not os.path.exists(path):
        raise HTTPException(404,"event snapshot not available")
    with open(path,"rb") as f:
        return Response(f.read(),media_type="image/jpeg",headers={"Cache-Control":"no-store"})

@app.post("/v1/events/{event_id}/review")
def review_event(event_id:str, req:EventReview):
    status=req.status.lower().strip()
    if status not in {"reviewed","dismissed","confirmed"}:
        raise HTTPException(400,"status must be reviewed, dismissed, or confirmed")
    with conn() as c:
        row=c.execute("select event_id,event_type,subject_id from events where event_id=%s",(event_id,)).fetchone()
        if not row:
            raise HTTPException(404,"event not found")
        if req.subject_id:
            exists=c.execute("select 1 from subjects where subject_id=%s",(req.subject_id,)).fetchone()
            if not exists:
                raise HTTPException(400,"subject_id does not exist")
        c.execute("""update events set review_status=%s,reviewed_at=now(),review_note=%s,reviewed_subject_id=%s
                     where event_id=%s""",(status,req.note,req.subject_id,event_id))
    _audit("event.reviewed","event",event_id,{"status":status,"subject_id":req.subject_id,"note":req.note})
    return {"event_id":event_id,"review_status":status,"subject_id":req.subject_id}

@app.get("/v1/events")
def events(limit:int=100, review_status:str="all"):
    limit=max(1,min(limit,1000))
    with conn() as c:
        rows=c.execute("""select event_id,camera_id,subject_id,score,event_type,occurred_at,metadata,
                          snapshot_path,review_status,reviewed_at,review_note,reviewed_subject_id
                          from events
                          where (%s='all' or review_status=%s)
                          order by occurred_at desc limit %s""",(review_status,review_status,limit)).fetchall()
    return [{"event_id":r[0],"camera_id":r[1],"subject_id":r[2],"score":r[3],"event_type":r[4],"occurred_at":r[5],
             "metadata":r[6],"has_snapshot":bool(r[7]),"review_status":r[8],"reviewed_at":r[9],
             "review_note":r[10],"reviewed_subject_id":r[11]} for r in rows]

# --- Missions 21-25: access decisions, presence, unknown clusters, camera-zones, review queues ---

_REF_RE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_DAYS=("mon","tue","wed","thu","fri","sat","sun")
_SCHEDULE_KEYS={"days","start","end","timezone"}
_CLUSTER_STATUSES={"open","monitoring","resolved","dismissed"}
_QUEUE_STATUSES={"active","paused","archived"}
_REVIEW_PRIORITIES=("low","normal","high","urgent")
_REVIEW_ITEM_STATUSES={"open","in_progress","resolved","dismissed"}
_REVIEW_ITEM_TYPES={"event":("events","event_id"),"registration":("registration_requests","request_id"),
                    "incident":("incidents","incident_id"),"unknown_cluster":("unknown_clusters","cluster_id")}

def _ref(value, field, required=False):
    """Validate an opaque reference; references are never interpreted as roles or identities."""
    if value is None or (isinstance(value,str) and not value.strip()):
        if required:
            raise HTTPException(400,f"{field} is required")
        return None
    v=value.strip()
    if not _REF_RE.match(v):
        raise HTTPException(400,f"{field} must be an opaque reference of 1-128 characters [A-Za-z0-9._:@-]")
    return v

def _parse_ts(value, field, default_now=False):
    if value is None or not value.strip():
        if default_now:
            return datetime.datetime.now(datetime.timezone.utc)
        raise HTTPException(400,f"{field} is required")
    try:
        ts=datetime.datetime.fromisoformat(value.strip().replace("Z","+00:00"))
    except ValueError:
        raise HTTPException(400,f"{field} must be an ISO-8601 timestamp")
    if ts.tzinfo is None:
        raise HTTPException(400,f"{field} must include a timezone offset")
    return ts

def _hhmm(value):
    try:
        h,m=str(value).split(":")
        h,m=int(h),int(m)
    except ValueError:
        return None
    if not (0<=h<=23 and 0<=m<=59):
        return None
    return h*60+m

def _schedule_error(schedule):
    """Return a validation error for an access-policy schedule, or None. Unknown keys fail closed."""
    if not isinstance(schedule,dict):
        return "schedule must be an object"
    extra=set(schedule)-_SCHEDULE_KEYS
    if extra:
        return "unsupported schedule keys: "+", ".join(sorted(extra))
    days=schedule.get("days")
    if days is not None and (not isinstance(days,list) or not days or any(str(d).lower() not in _DAYS for d in days)):
        return "schedule.days must be a non-empty list of mon,tue,wed,thu,fri,sat,sun"
    if ("start" in schedule)!=("end" in schedule):
        return "schedule.start and schedule.end must be provided together"
    if "start" in schedule:
        start,end=_hhmm(schedule["start"]),_hhmm(schedule["end"])
        if start is None or end is None:
            return "schedule.start and schedule.end must be HH:MM"
        if start==end:
            return "schedule.start and schedule.end must differ"
    if "timezone" in schedule:
        try:
            zoneinfo.ZoneInfo(str(schedule["timezone"]))
        except Exception:
            return "schedule.timezone must be a valid IANA timezone"
    return None

def _schedule_matches(schedule, ts):
    local=ts.astimezone(zoneinfo.ZoneInfo(str(schedule.get("timezone","UTC"))))
    if "days" in schedule and _DAYS[local.weekday()] not in {str(d).lower() for d in schedule["days"]}:
        return False
    if "start" in schedule:
        start,end=_hhmm(schedule["start"]),_hhmm(schedule["end"])
        minute=local.hour*60+local.minute
        return start<=minute<end if start<end else (minute>=start or minute<end)
    return True

def _exists(c, table, column, value):
    return bool(value) and c.execute(f"select 1 from {table} where {column}=%s",(value,)).fetchone() is not None

def _subject_ref(subject_ref, subject_id):
    a=_ref(subject_ref,"subject_ref"); b=_ref(subject_id,"subject_id")
    if a and b and a!=b:
        raise HTTPException(400,"subject_ref and subject_id must match when both are provided")
    return a or b

# Mission 21 - access decisions (decision-only, never actuates hardware)

@app.post("/v1/access/evaluate",tags=["access-decisions"])
def access_evaluate(req:AccessEvaluateIn):
    subject_id=_subject_ref(req.subject_ref,req.subject_id)
    zone_id=_ref(req.zone_id,"zone_id",required=True)
    pass_id=_ref(req.visitor_pass_id,"visitor_pass_id")
    ts=_parse_ts(req.occurred_at,"occurred_at")
    if not subject_id and not pass_id:
        raise HTTPException(400,"subject_ref/subject_id or visitor_pass_id is required")
    reasons=[]; allow_ids=[]; deny_ids=[]; invalid_ids=[]; matched_pass=None
    with conn() as c:
        zone=c.execute("select enabled from zones where zone_id=%s",(zone_id,)).fetchone()
        if not zone: reasons.append("zone_not_found")
        elif not zone[0]: reasons.append("zone_disabled")
        if subject_id and not _exists(c,"subjects","subject_id",subject_id):
            reasons.append("subject_not_found")
        if pass_id:
            vp=c.execute("select status,valid_from,valid_until from visitor_passes where pass_id=%s",(pass_id,)).fetchone()
            if not vp: reasons.append("visitor_pass_not_found")
            elif vp[0]!="active": reasons.append("visitor_pass_inactive")
            elif ts<vp[1]: reasons.append("visitor_pass_not_yet_valid")
            elif ts>=vp[2]: reasons.append("visitor_pass_expired")
            else: matched_pass=pass_id
        if not reasons:
            policies=c.execute("""select policy_id,allowed,schedule from access_policies
                                  where zone_id=%s and enabled=true and (subject_id is null or subject_id=%s)
                                  order by policy_id""",(zone_id,subject_id)).fetchall()
            for policy_id,allowed,schedule in policies:
                if _schedule_error(schedule):
                    invalid_ids.append(policy_id)
                elif _schedule_matches(schedule,ts):
                    (allow_ids if allowed else deny_ids).append(policy_id)
            if invalid_ids: reasons.append("policy_invalid")
            elif deny_ids: reasons.append("policy_denied")
            elif not allow_ids: reasons.append("no_matching_policy")
    allowed=not reasons
    if allowed:
        reasons=["policy_allowed"]+(["visitor_pass_valid"] if matched_pass else [])
    matched=invalid_ids or deny_ids or allow_ids
    decision_id="dec-"+uuid.uuid4().hex[:20]
    result={"decision_id":decision_id,"decision":"allow" if allowed else "deny","allowed":allowed,
            "reason_codes":reasons,"matched_policy_ids":matched,"matched_visitor_pass_id":matched_pass,
            "subject_id":subject_id,"zone_id":zone_id,"visitor_pass_id":pass_id,"occurred_at":ts.isoformat(),
            "decision_only":True,"actuation":"none"}
    _audit("access.evaluated","access_decision",decision_id,{k:result[k] for k in
           ("decision","reason_codes","matched_policy_ids","matched_visitor_pass_id","subject_id","zone_id","visitor_pass_id","occurred_at")})
    return result

# Mission 24 - camera-zone mapping (metadata only; no credentials or stream changes)

def _camera_zone_dict(r):
    return {"mapping_id":r[0],"camera_id":r[1],"zone_id":r[2],"priority":r[3],"enabled":r[4],"notes":r[5],"created_at":r[6],"updated_at":r[7]}
_CAMERA_ZONE_COLS="mapping_id,camera_id,zone_id,priority,enabled,notes,created_at,updated_at"

@app.get("/v1/camera-zones",tags=["camera-zones"])
def list_camera_zones(camera_id:Optional[str]=None, zone_id:Optional[str]=None):
    with conn() as c:
        rows=c.execute(f"""select {_CAMERA_ZONE_COLS} from camera_zones
                           where (%s::text is null or camera_id=%s) and (%s::text is null or zone_id=%s)
                           order by camera_id,priority,zone_id""",(camera_id,camera_id,zone_id,zone_id)).fetchall()
    return [_camera_zone_dict(r) for r in rows]

@app.post("/v1/camera-zones",tags=["camera-zones"])
def save_camera_zone(req:CameraZoneIn):
    camera_id=_ref(req.camera_id,"camera_id",required=True); zone_id=_ref(req.zone_id,"zone_id",required=True)
    with conn() as c:
        if not _exists(c,"cameras","camera_id",camera_id): raise HTTPException(400,"camera_id does not exist")
        if not _exists(c,"zones","zone_id",zone_id): raise HTTPException(400,"zone_id does not exist")
        row=c.execute(f"""insert into camera_zones(mapping_id,camera_id,zone_id,priority,enabled,notes) values(%s,%s,%s,%s,%s,%s)
                          on conflict(camera_id,zone_id) do update set priority=excluded.priority,enabled=excluded.enabled,
                          notes=excluded.notes,updated_at=now()
                          returning {_CAMERA_ZONE_COLS},(xmax=0)""",
                      ("cz-"+uuid.uuid4().hex[:16],camera_id,zone_id,req.priority,req.enabled,req.notes)).fetchone()
    out=_camera_zone_dict(row); out["created"]=row[8]
    _audit("camera_zone.created" if row[8] else "camera_zone.updated","camera_zone",out["mapping_id"],
           {"camera_id":camera_id,"zone_id":zone_id,"priority":req.priority,"enabled":req.enabled})
    return out

@app.patch("/v1/camera-zones/{mapping_id}",tags=["camera-zones"])
def patch_camera_zone(mapping_id:str, req:CameraZonePatch):
    changes=req.model_dump(exclude_unset=True)
    if changes.get("priority",0) is None or changes.get("enabled",False) is None:
        raise HTTPException(400,"priority and enabled cannot be null")
    with conn() as c:
        if not _exists(c,"camera_zones","mapping_id",mapping_id): raise HTTPException(404,"camera-zone mapping not found")
        for k,v in changes.items():
            c.execute(f"update camera_zones set {k}=%s,updated_at=now() where mapping_id=%s",(v,mapping_id))
        row=c.execute(f"select {_CAMERA_ZONE_COLS} from camera_zones where mapping_id=%s",(mapping_id,)).fetchone()
    _audit("camera_zone.updated","camera_zone",mapping_id,{"changes":changes})
    return _camera_zone_dict(row)

@app.delete("/v1/camera-zones/{mapping_id}",tags=["camera-zones"])
def delete_camera_zone(mapping_id:str):
    with conn() as c:
        row=c.execute("delete from camera_zones where mapping_id=%s returning camera_id,zone_id",(mapping_id,)).fetchone()
    if not row: raise HTTPException(404,"camera-zone mapping not found")
    _audit("camera_zone.deleted","camera_zone",mapping_id,{"camera_id":row[0],"zone_id":row[1]})
    return {"mapping_id":mapping_id,"deleted":True}

# Mission 22 - presence sessions and zone occupancy

def _presence_session_dict(r):
    return {"session_id":r[0],"subject_kind":r[1],"subject_ref":r[2],"zone_id":r[3],"camera_id":r[4],"entered_at":r[5],
            "exited_at":r[6],"enter_event_ref":r[7],"exit_event_ref":r[8],"status":"open" if r[6] is None else "closed"}
_PRESENCE_COLS="session_id,subject_kind,subject_ref,zone_id,camera_id,entered_at,exited_at,enter_event_ref,exit_event_ref"

@app.post("/v1/presence/events",tags=["presence"])
def presence_event(req:PresenceEventIn):
    event_ref=_ref(req.event_ref,"event_ref",required=True)
    direction=req.direction.strip().lower()
    if direction not in {"enter","exit"}:
        raise HTTPException(400,"direction must be enter or exit")
    request_hash=hashlib.sha256(json.dumps(req.model_dump(),sort_keys=True).encode()).hexdigest()
    with conn() as c:
        prior=c.execute("select request_hash,session_id,outcome,direction,subject_kind,subject_ref,zone_id,camera_id,occurred_at from presence_observations where event_ref=%s",(event_ref,)).fetchone()
        if prior:
            if prior[0]!=request_hash:
                raise HTTPException(409,"event_ref already recorded with a different payload")
            return {"event_ref":event_ref,"session_id":prior[1],"outcome":prior[2],"direction":prior[3],"subject_kind":prior[4],
                    "subject_ref":prior[5],"zone_id":prior[6],"camera_id":prior[7],"occurred_at":prior[8],"idempotent_replay":True}
        subject_id=_subject_ref(req.subject_ref,req.subject_id)
        pass_id=_ref(req.visitor_pass_id,"visitor_pass_id")
        event_id=_ref(req.event_id,"event_id")
        camera_id=_ref(req.camera_id,"camera_id")
        zone_id=_ref(req.zone_id,"zone_id")
        ts=_parse_ts(req.occurred_at,"occurred_at",default_now=True)
        if event_id:
            ev=c.execute("select camera_id,coalesce(reviewed_subject_id,subject_id) from events where event_id=%s",(event_id,)).fetchone()
            if not ev: raise HTTPException(400,"event_id does not exist")
            camera_id=camera_id or ev[0]
            if not subject_id and not pass_id: subject_id=ev[1]
        if subject_id and pass_id:
            raise HTTPException(400,"provide either a subject reference or visitor_pass_id, not both")
        if subject_id:
            if not _exists(c,"subjects","subject_id",subject_id): raise HTTPException(400,"subject reference does not exist")
            kind,subject=("subject",subject_id)
        elif pass_id:
            if not _exists(c,"visitor_passes","pass_id",pass_id): raise HTTPException(400,"visitor_pass_id does not exist")
            kind,subject=("visitor_pass",pass_id)
        else:
            raise HTTPException(400,"a subject reference, visitor_pass_id, or attributed event_id is required")
        if camera_id and not _exists(c,"cameras","camera_id",camera_id): raise HTTPException(400,"camera_id does not exist")
        if zone_id:
            if not _exists(c,"zones","zone_id",zone_id): raise HTTPException(400,"zone_id does not exist")
            if camera_id and not c.execute("select 1 from camera_zones where camera_id=%s and zone_id=%s and enabled=true",(camera_id,zone_id)).fetchone():
                raise HTTPException(400,"camera_id is not mapped to zone_id")
        elif camera_id:
            m=c.execute("select zone_id from camera_zones where camera_id=%s and enabled=true order by priority,zone_id limit 1",(camera_id,)).fetchone()
            if not m: raise HTTPException(400,"camera_id has no enabled zone mapping")
            zone_id=m[0]
        else:
            raise HTTPException(400,"zone_id or a mapped camera_id is required")
        open_row=c.execute("select session_id,entered_at from presence_sessions where subject_kind=%s and subject_ref=%s and zone_id=%s and exited_at is null for update",
                           (kind,subject,zone_id)).fetchone()
        session_id=open_row[0] if open_row else None
        if direction=="enter":
            if open_row:
                outcome="already_present"
            else:
                session_id="ps-"+uuid.uuid4().hex[:20]
                inserted=c.execute("""insert into presence_sessions(session_id,subject_kind,subject_ref,zone_id,camera_id,entered_at,enter_event_ref)
                                      values(%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning session_id""",
                                   (session_id,kind,subject,zone_id,camera_id,ts,event_ref)).fetchone()
                if inserted:
                    outcome="session_opened"
                else:
                    session_id=c.execute("select session_id from presence_sessions where subject_kind=%s and subject_ref=%s and zone_id=%s and exited_at is null",
                                         (kind,subject,zone_id)).fetchone()[0]
                    outcome="already_present"
        elif not open_row:
            outcome="no_open_session"
        elif ts<open_row[1]:
            outcome="exit_before_entry_ignored"
        else:
            c.execute("update presence_sessions set exited_at=%s,exit_event_ref=%s,updated_at=now() where session_id=%s",(ts,event_ref,session_id))
            outcome="session_closed"
        inserted=c.execute("""insert into presence_observations(event_ref,request_hash,direction,subject_kind,subject_ref,zone_id,camera_id,event_id,occurred_at,session_id,outcome)
                              values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(event_ref) do nothing returning event_ref""",
                           (event_ref,request_hash,direction,kind,subject,zone_id,camera_id,event_id,ts,session_id,outcome)).fetchone()
        if not inserted:
            raise HTTPException(409,"event_ref was recorded concurrently; retry to read the stored result")
    _audit("presence.observed","presence_observation",event_ref,{"direction":direction,"subject_kind":kind,"subject_ref":subject,
           "zone_id":zone_id,"camera_id":camera_id,"session_id":session_id,"outcome":outcome})
    return {"event_ref":event_ref,"session_id":session_id,"outcome":outcome,"direction":direction,"subject_kind":kind,
            "subject_ref":subject,"zone_id":zone_id,"camera_id":camera_id,"occurred_at":ts,"idempotent_replay":False}

@app.get("/v1/presence/current",tags=["presence"])
def presence_current(zone_id:Optional[str]=None):
    with conn() as c:
        rows=c.execute(f"""select {_PRESENCE_COLS} from presence_sessions where exited_at is null and (%s::text is null or zone_id=%s)
                           order by zone_id,entered_at""",(zone_id,zone_id)).fetchall()
        zones=c.execute("select zone_id,name,enabled from zones where (%s::text is null or zone_id=%s) order by zone_id",(zone_id,zone_id)).fetchall()
    counts={}
    for r in rows: counts[r[3]]=counts.get(r[3],0)+1
    return {"occupancy":[{"zone_id":z[0],"name":z[1],"enabled":z[2],"count":counts.get(z[0],0)} for z in zones],
            "total":len(rows),"sessions":[_presence_session_dict(r) for r in rows]}

@app.get("/v1/presence/history",tags=["presence"])
def presence_history(zone_id:Optional[str]=None, subject_ref:Optional[str]=None, since:Optional[str]=None, until:Optional[str]=None,
                     status:str="all", limit:int=200):
    if status not in {"all","open","closed"}: raise HTTPException(400,"status must be all, open, or closed")
    since_ts=_parse_ts(since,"since") if since else None
    until_ts=_parse_ts(until,"until") if until else None
    limit=max(1,min(limit,1000))
    with conn() as c:
        rows=c.execute(f"""select {_PRESENCE_COLS} from presence_sessions
                           where (%s::text is null or zone_id=%s) and (%s::text is null or subject_ref=%s)
                           and (%s::timestamptz is null or entered_at>=%s) and (%s::timestamptz is null or entered_at<%s)
                           and (%s='all' or (%s='open' and exited_at is null) or (%s='closed' and exited_at is not null))
                           order by entered_at desc limit %s""",
                       (zone_id,zone_id,subject_ref,subject_ref,since_ts,since_ts,until_ts,until_ts,status,status,status,limit)).fetchall()
    return [_presence_session_dict(r) for r in rows]

# Mission 23 - operator-owned unknown clusters. A cluster label is an operator note,
# NOT a real-world identity: clusters never carry subject_id and never assert who someone is.

def _cluster_dict(r, event_count=None):
    out={"cluster_id":r[0],"label":r[1],"status":r[2],"notes":r[3],"owner_ref":r[4],"created_at":r[5],"updated_at":r[6],
         "identity_asserted":False}
    if event_count is not None: out["event_count"]=event_count
    return out
_CLUSTER_COLS="cluster_id,label,status,notes,owner_ref,created_at,updated_at"

def _cluster_or_404(c, cluster_id):
    row=c.execute(f"select {_CLUSTER_COLS} from unknown_clusters where cluster_id=%s",(cluster_id,)).fetchone()
    if not row: raise HTTPException(404,"unknown cluster not found")
    return row

@app.get("/v1/unknown-clusters",tags=["unknown-clusters"])
def list_unknown_clusters(status:str="all"):
    with conn() as c:
        rows=c.execute(f"""select {",".join("u."+x for x in _CLUSTER_COLS.split(","))},count(e.event_id)
                           from unknown_clusters u left join unknown_cluster_events e on e.cluster_id=u.cluster_id
                           where (%s='all' or u.status=%s) group by u.cluster_id order by u.updated_at desc""",(status,status)).fetchall()
    return [_cluster_dict(r,r[7]) for r in rows]

@app.post("/v1/unknown-clusters",tags=["unknown-clusters"])
def create_unknown_cluster(req:UnknownClusterIn):
    cluster_id=_ref(req.cluster_id,"cluster_id") or "uc-"+uuid.uuid4().hex[:16]
    if req.status not in _CLUSTER_STATUSES: raise HTTPException(400,"unsupported cluster status")
    owner_ref=_ref(req.owner_ref,"owner_ref")
    with conn() as c:
        row=c.execute(f"""insert into unknown_clusters(cluster_id,label,status,notes,owner_ref) values(%s,%s,%s,%s,%s)
                          on conflict(cluster_id) do nothing returning {_CLUSTER_COLS}""",
                      (cluster_id,req.label.strip(),req.status,req.notes,owner_ref)).fetchone()
    if not row: raise HTTPException(409,"cluster_id already exists; use PATCH to update it")
    _audit("unknown_cluster.created","unknown_cluster",cluster_id,{"label":row[1],"status":row[2],"owner_ref":owner_ref})
    return _cluster_dict(row,0)

@app.get("/v1/unknown-clusters/{cluster_id}",tags=["unknown-clusters"])
def get_unknown_cluster(cluster_id:str):
    with conn() as c:
        row=_cluster_or_404(c,cluster_id)
        evs=c.execute("""select e.event_id,e.camera_id,e.occurred_at,e.review_status,e.snapshot_path is not null,u.attached_at
                         from unknown_cluster_events u join events e on e.event_id=u.event_id
                         where u.cluster_id=%s order by e.occurred_at desc""",(cluster_id,)).fetchall()
    out=_cluster_dict(row,len(evs))
    out["events"]=[{"event_id":e[0],"camera_id":e[1],"occurred_at":e[2],"review_status":e[3],"has_snapshot":e[4],"attached_at":e[5]} for e in evs]
    return out

@app.patch("/v1/unknown-clusters/{cluster_id}",tags=["unknown-clusters"])
def patch_unknown_cluster(cluster_id:str, req:UnknownClusterPatch):
    changes=req.model_dump(exclude_unset=True)
    if "label" in changes:
        if changes["label"] is None or not changes["label"].strip(): raise HTTPException(400,"label cannot be empty")
        changes["label"]=changes["label"].strip()
    if "status" in changes and changes["status"] not in _CLUSTER_STATUSES: raise HTTPException(400,"unsupported cluster status")
    if "owner_ref" in changes: changes["owner_ref"]=_ref(changes["owner_ref"],"owner_ref")
    with conn() as c:
        _cluster_or_404(c,cluster_id)
        for k,v in changes.items():
            c.execute(f"update unknown_clusters set {k}=%s,updated_at=now() where cluster_id=%s",(v,cluster_id))
        row=_cluster_or_404(c,cluster_id)
    _audit("unknown_cluster.updated","unknown_cluster",cluster_id,{"changes":changes})
    return _cluster_dict(row)

@app.post("/v1/unknown-clusters/{cluster_id}/events",tags=["unknown-clusters"])
def attach_cluster_events(cluster_id:str, req:ClusterEventsIn):
    event_ids=list(dict.fromkeys(_ref(x,"event_id",required=True) for x in req.event_ids))
    with conn() as c:
        _cluster_or_404(c,cluster_id)
        found={r[0]:r[1] for r in c.execute("select event_id,event_type from events where event_id = any(%s)",(event_ids,)).fetchall()}
        if any(x not in found for x in event_ids): raise HTTPException(400,"one or more event_ids do not exist")
        if any(found[x]!="unknown_face" for x in event_ids): raise HTTPException(400,"only unknown_face events can be attached to unknown clusters")
        owners={r[0]:r[1] for r in c.execute("select event_id,cluster_id from unknown_cluster_events where event_id = any(%s)",(event_ids,)).fetchall()}
        if any(v!=cluster_id for v in owners.values()): raise HTTPException(409,"one or more events are already attached to another cluster")
        attached=[x for x in event_ids if x not in owners]
        for x in attached:
            c.execute("insert into unknown_cluster_events(event_id,cluster_id) values(%s,%s)",(x,cluster_id))
        if attached: c.execute("update unknown_clusters set updated_at=now() where cluster_id=%s",(cluster_id,))
    if attached: _audit("unknown_cluster.events_attached","unknown_cluster",cluster_id,{"event_ids":attached})
    return {"cluster_id":cluster_id,"attached":attached,"already_attached":[x for x in event_ids if x in owners]}

@app.delete("/v1/unknown-clusters/{cluster_id}/events/{event_id}",tags=["unknown-clusters"])
def detach_cluster_event(cluster_id:str, event_id:str):
    with conn() as c:
        _cluster_or_404(c,cluster_id)
        if not c.execute("delete from unknown_cluster_events where cluster_id=%s and event_id=%s returning event_id",(cluster_id,event_id)).fetchone():
            raise HTTPException(404,"event is not attached to this cluster")
        c.execute("update unknown_clusters set updated_at=now() where cluster_id=%s",(cluster_id,))
    _audit("unknown_cluster.event_detached","unknown_cluster",cluster_id,{"event_id":event_id})
    return {"cluster_id":cluster_id,"event_id":event_id,"detached":True}

# Mission 25 - review queues. assignee_ref is an opaque reference; Keycloak remains the identity authority
# and no request header is trusted as a role or user assertion.

_QUEUE_COLS="queue_id,name,description,status,default_priority,created_at,updated_at"
_ITEM_COLS="item_id,queue_id,item_type,item_ref,status,priority,assignee_ref,notes,created_at,updated_at,resolved_at"
_PRIORITY_ORDER="case priority when 'urgent' then 0 when 'high' then 1 when 'normal' then 2 else 3 end"

def _queue_dict(r):
    return {"queue_id":r[0],"name":r[1],"description":r[2],"status":r[3],"default_priority":r[4],"created_at":r[5],"updated_at":r[6]}

def _item_dict(r):
    return {"item_id":r[0],"queue_id":r[1],"item_type":r[2],"item_ref":r[3],"status":r[4],"priority":r[5],"assignee_ref":r[6],
            "notes":r[7],"created_at":r[8],"updated_at":r[9],"resolved_at":r[10]}

def _queue_or_404(c, queue_id):
    row=c.execute(f"select {_QUEUE_COLS} from review_queues where queue_id=%s",(queue_id,)).fetchone()
    if not row: raise HTTPException(404,"review queue not found")
    return row

def _check_priority(p):
    if p not in _REVIEW_PRIORITIES: raise HTTPException(400,"priority must be one of low, normal, high, urgent")

@app.get("/v1/review-queues",tags=["review-queues"])
def list_review_queues(status:str="all"):
    with conn() as c:
        rows=c.execute(f"""select {",".join("q."+x for x in _QUEUE_COLS.split(","))},
                           count(i.item_id) filter (where i.status in ('open','in_progress'))
                           from review_queues q left join review_queue_items i on i.queue_id=q.queue_id
                           where (%s='all' or q.status=%s) group by q.queue_id order by q.name""",(status,status)).fetchall()
    return [{**_queue_dict(r),"open_items":r[7]} for r in rows]

@app.post("/v1/review-queues",tags=["review-queues"])
def create_review_queue(req:ReviewQueueIn):
    queue_id=_ref(req.queue_id,"queue_id",required=True)
    if req.status not in _QUEUE_STATUSES: raise HTTPException(400,"status must be active, paused, or archived")
    _check_priority(req.default_priority)
    with conn() as c:
        row=c.execute(f"""insert into review_queues(queue_id,name,description,status,default_priority) values(%s,%s,%s,%s,%s)
                          on conflict(queue_id) do nothing returning {_QUEUE_COLS}""",
                      (queue_id,req.name.strip(),req.description,req.status,req.default_priority)).fetchone()
    if not row: raise HTTPException(409,"queue_id already exists; use PATCH to update it")
    _audit("review_queue.created","review_queue",queue_id,{"name":row[1],"status":row[3]})
    return _queue_dict(row)

@app.get("/v1/review-queues/{queue_id}",tags=["review-queues"])
def get_review_queue(queue_id:str):
    with conn() as c:
        row=_queue_or_404(c,queue_id)
        counts=dict(c.execute("select status,count(*) from review_queue_items where queue_id=%s group by status",(queue_id,)).fetchall())
    return {**_queue_dict(row),"item_counts":counts}

@app.patch("/v1/review-queues/{queue_id}",tags=["review-queues"])
def patch_review_queue(queue_id:str, req:ReviewQueuePatch):
    changes=req.model_dump(exclude_unset=True)
    if "name" in changes and (changes["name"] is None or not changes["name"].strip()): raise HTTPException(400,"name cannot be empty")
    if "status" in changes and changes["status"] not in _QUEUE_STATUSES: raise HTTPException(400,"status must be active, paused, or archived")
    if "default_priority" in changes: _check_priority(changes["default_priority"])
    with conn() as c:
        _queue_or_404(c,queue_id)
        for k,v in changes.items():
            c.execute(f"update review_queues set {k}=%s,updated_at=now() where queue_id=%s",(v,queue_id))
        row=_queue_or_404(c,queue_id)
    _audit("review_queue.updated","review_queue",queue_id,{"changes":changes})
    return _queue_dict(row)

@app.delete("/v1/review-queues/{queue_id}",tags=["review-queues"])
def delete_review_queue(queue_id:str):
    with conn() as c:
        _queue_or_404(c,queue_id)
        if c.execute("select 1 from review_queue_items where queue_id=%s limit 1",(queue_id,)).fetchone():
            raise HTTPException(409,"queue has items; archive it with PATCH status=archived instead")
        c.execute("delete from review_queues where queue_id=%s",(queue_id,))
    _audit("review_queue.deleted","review_queue",queue_id)
    return {"queue_id":queue_id,"deleted":True}

@app.get("/v1/review-queues/{queue_id}/items",tags=["review-queues"])
def list_review_items(queue_id:str, status:str="all", assignee_ref:Optional[str]=None, priority:Optional[str]=None, limit:int=200):
    limit=max(1,min(limit,1000))
    with conn() as c:
        _queue_or_404(c,queue_id)
        rows=c.execute(f"""select {_ITEM_COLS} from review_queue_items
                           where queue_id=%s and (%s='all' or status=%s) and (%s::text is null or assignee_ref=%s)
                           and (%s::text is null or priority=%s)
                           order by {_PRIORITY_ORDER},created_at limit %s""",
                       (queue_id,status,status,assignee_ref,assignee_ref,priority,priority,limit)).fetchall()
    return [_item_dict(r) for r in rows]

@app.post("/v1/review-queues/{queue_id}/items",tags=["review-queues"])
def create_review_item(queue_id:str, req:ReviewItemIn):
    if req.item_type not in _REVIEW_ITEM_TYPES: raise HTTPException(400,"item_type must be one of "+", ".join(sorted(_REVIEW_ITEM_TYPES)))
    item_ref=_ref(req.item_ref,"item_ref",required=True)
    assignee_ref=_ref(req.assignee_ref,"assignee_ref")
    with conn() as c:
        queue=_queue_or_404(c,queue_id)
        if queue[3]=="archived": raise HTTPException(409,"queue is archived")
        priority=req.priority or queue[4]
        _check_priority(priority)
        table,column=_REVIEW_ITEM_TYPES[req.item_type]
        if not _exists(c,table,column,item_ref): raise HTTPException(400,f"{req.item_type} reference does not exist")
        row=c.execute(f"""insert into review_queue_items(item_id,queue_id,item_type,item_ref,priority,assignee_ref,notes)
                          values(%s,%s,%s,%s,%s,%s,%s) on conflict(queue_id,item_type,item_ref) do nothing returning {_ITEM_COLS}""",
                      ("rqi-"+uuid.uuid4().hex[:16],queue_id,req.item_type,item_ref,priority,assignee_ref,req.notes)).fetchone()
        created=row is not None
        if not created:
            row=c.execute(f"select {_ITEM_COLS} from review_queue_items where queue_id=%s and item_type=%s and item_ref=%s",
                          (queue_id,req.item_type,item_ref)).fetchone()
    if created: _audit("review_item.created","review_queue_item",row[0],{"queue_id":queue_id,"item_type":req.item_type,"item_ref":item_ref,"priority":priority,"assignee_ref":assignee_ref})
    return {**_item_dict(row),"created":created}

@app.get("/v1/review-queues/{queue_id}/items/{item_id}",tags=["review-queues"])
def get_review_item(queue_id:str, item_id:str):
    with conn() as c:
        row=c.execute(f"select {_ITEM_COLS} from review_queue_items where queue_id=%s and item_id=%s",(queue_id,item_id)).fetchone()
    if not row: raise HTTPException(404,"review item not found")
    return _item_dict(row)

@app.patch("/v1/review-queues/{queue_id}/items/{item_id}",tags=["review-queues"])
def patch_review_item(queue_id:str, item_id:str, req:ReviewItemPatch):
    changes=req.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in _REVIEW_ITEM_STATUSES: raise HTTPException(400,"status must be open, in_progress, resolved, or dismissed")
    if "priority" in changes: _check_priority(changes["priority"])
    if "assignee_ref" in changes: changes["assignee_ref"]=_ref(changes["assignee_ref"],"assignee_ref")
    with conn() as c:
        if not c.execute("select 1 from review_queue_items where queue_id=%s and item_id=%s",(queue_id,item_id)).fetchone():
            raise HTTPException(404,"review item not found")
        for k,v in changes.items():
            c.execute(f"update review_queue_items set {k}=%s,updated_at=now() where item_id=%s",(v,item_id))
        if "status" in changes:
            c.execute("update review_queue_items set resolved_at=case when status in ('resolved','dismissed') then now() else null end where item_id=%s",(item_id,))
        row=c.execute(f"select {_ITEM_COLS} from review_queue_items where item_id=%s",(item_id,)).fetchone()
    _audit("review_item.updated","review_queue_item",item_id,{"queue_id":queue_id,"changes":changes})
    return _item_dict(row)

# --- Missions 26-30: watchlists, enrollment quality, duplicate candidates, model registry, audit export ---

_WATCHLIST_CATEGORIES=("staff","visitor","contractor","vip","review-required","denied-access")
_WATCHLIST_STATUSES={"active","archived"}
ENROLL_MIN_FACE_PX=int(os.getenv("FACEID_ENROLL_MIN_FACE_PX","80"))
ENROLL_MIN_SHARPNESS=float(os.getenv("FACEID_ENROLL_MIN_SHARPNESS","40"))
ENROLL_MIN_BRIGHTNESS=float(os.getenv("FACEID_ENROLL_MIN_BRIGHTNESS","40"))
ENROLL_MAX_BRIGHTNESS=float(os.getenv("FACEID_ENROLL_MAX_BRIGHTNESS","220"))
ENROLL_MAX_FACES=1
ENROLL_MIN_IMAGES=int(os.getenv("FACEID_ENROLL_MIN_IMAGES","1"))
ENROLL_MAX_IMAGES=int(os.getenv("FACEID_ENROLL_MAX_IMAGES","10"))
ENROLL_MAX_IMAGE_BYTES=int(os.getenv("FACEID_ENROLL_MAX_IMAGE_BYTES",str(6*1024*1024)))
ENROLL_SESSION_TTL_HOURS=int(os.getenv("FACEID_ENROLL_SESSION_TTL_HOURS","24"))
DUPLICATE_THRESHOLD=float(os.getenv("FACEID_DUPLICATE_THRESHOLD","0.30"))
DUPLICATE_MAX_CANDIDATES=int(os.getenv("FACEID_DUPLICATE_MAX_CANDIDATES","20"))
EMBEDDING_HISTORY_DAYS=int(os.getenv("FACEID_EMBEDDING_HISTORY_DAYS","30"))
AUDIT_EXPORT_MAX_DAYS=int(os.getenv("FACEID_AUDIT_EXPORT_MAX_DAYS","366"))
AUDIT_EXPORT_HMAC_KEY=os.getenv("FACEID_AUDIT_EXPORT_HMAC_KEY","")
AUDIT_EXPORT_KEY_ID=os.getenv("FACEID_AUDIT_EXPORT_KEY_ID","local")
if DUPLICATE_THRESHOLD==MATCH_THRESHOLD:
    raise RuntimeError("FACEID_DUPLICATE_THRESHOLD must differ from FACEID_MATCH_THRESHOLD")
_AGGREGATION_METHOD="l2-mean-l2/v1"
_DUPLICATE_RESOLUTIONS={"not_duplicate","duplicate_confirmed","dismissed"}
_JOB_STATUSES={"queued","succeeded","failed","cancelled"}
_REDACTION_POLICY="faceid-audit-redaction/v1"

def _canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()

def _iso(ts):
    return ts.astimezone(datetime.timezone.utc).isoformat() if ts else None

def _purge_subject_dependents(c, subject_id):
    """Remove Mission 26-29 rows tied to a subject: memberships, archived templates, sessions, candidates, jobs."""
    c.execute("delete from watchlist_members where subject_kind='subject' and subject_ref=%s",(subject_id,))
    c.execute("delete from subject_embedding_history where subject_id=%s",(subject_id,))
    sessions=[r[0] for r in c.execute("select session_id from enrollment_sessions where subject_id=%s",(subject_id,)).fetchall()]
    c.execute("delete from enrollment_session_images where session_id = any(%s)",(sessions,))
    c.execute("delete from duplicate_candidates where session_id = any(%s) or candidate_subject_ref=%s",(sessions,subject_id))
    c.execute("delete from enrollment_sessions where session_id = any(%s)",(sessions,))
    c.execute("delete from reembedding_jobs where subject_id=%s",(subject_id,))

def _privacy_export_extra(c, subject_id):
    s=c.execute("""select model_key,model_id,model_version,model_digest,embedding_version,embedding_dim,embedding_method,
                   embedding_image_count,embedded_at from subjects where subject_id=%s""",(subject_id,)).fetchone()
    members=c.execute("""select m.watchlist_id,w.name,w.category,m.note,m.expires_at,m.created_at from watchlist_members m
                         join watchlists w on w.watchlist_id=m.watchlist_id
                         where m.subject_kind='subject' and m.subject_ref=%s order by m.created_at""",(subject_id,)).fetchall()
    sessions=c.execute("""select s.session_id,s.status,s.created_at,s.finalized_at,count(i.image_id) filter (where i.status='accepted')
                          from enrollment_sessions s left join enrollment_session_images i on i.session_id=s.session_id
                          where s.subject_id=%s group by s.session_id order by s.created_at""",(subject_id,)).fetchall()
    cands=c.execute("""select candidate_id,case when subject_ref=%s then 'enrolling' else 'matched' end,score,status,resolution,created_at
                       from duplicate_candidates where subject_ref=%s or candidate_subject_ref=%s order by created_at""",
                    (subject_id,subject_id,subject_id)).fetchall()
    jobs=c.execute("select job_id,status,target_embedding_version,created_at,completed_at from reembedding_jobs where subject_id=%s order by created_at",(subject_id,)).fetchall()
    archived=c.execute("select count(*) from subject_embedding_history where subject_id=%s",(subject_id,)).fetchone()[0]
    return {"embedding_metadata":{"model_key":s[0],"model_id":s[1],"model_version":s[2],"model_digest":s[3],"embedding_version":s[4],
                                  "embedding_dim":s[5],"embedding_method":s[6],"embedding_image_count":s[7],"embedded_at":s[8],
                                  "archived_embeddings":archived,"template_included":False},
            "watchlist_memberships":[{"watchlist_id":m[0],"name":m[1],"category":m[2],"note":m[3],"expires_at":m[4],"created_at":m[5]} for m in members],
            "enrollment_sessions":[{"session_id":x[0],"status":x[1],"created_at":x[2],"finalized_at":x[3],"accepted_images":x[4]} for x in sessions],
            "duplicate_candidates":[{"candidate_id":x[0],"role":x[1],"score":x[2],"status":x[3],"resolution":x[4],"created_at":x[5]} for x in cands],
            "reembedding_jobs":[{"job_id":j[0],"status":j[1],"target_embedding_version":j[2],"created_at":j[3],"completed_at":j[4]} for j in jobs]}

# Mission 26 - watchlists / subject categories. A watchlist is local policy metadata, NOT proof of identity:
# membership never triggers an external action and is not consulted by access decisions.

_WATCHLIST_COLS="watchlist_id,name,category,description,status,created_at,updated_at"
_MEMBER_COLS="member_id,watchlist_id,subject_kind,subject_ref,note,added_by_ref,expires_at,created_at"

def _watchlist_dict(r, member_count=None):
    out={"watchlist_id":r[0],"name":r[1],"category":r[2],"description":r[3],"status":r[4],"created_at":r[5],"updated_at":r[6],
         "identity_proof":False,"automatic_actions":False}
    if member_count is not None: out["member_count"]=member_count
    return out

def _member_dict(r):
    now=datetime.datetime.now(datetime.timezone.utc)
    return {"member_id":r[0],"watchlist_id":r[1],"subject_kind":r[2],"subject_ref":r[3],"note":r[4],"added_by_ref":r[5],
            "expires_at":r[6],"expired":bool(r[6] and r[6]<=now),"created_at":r[7],"identity_proof":False}

def _watchlist_or_404(c, watchlist_id):
    row=c.execute(f"select {_WATCHLIST_COLS} from watchlists where watchlist_id=%s",(watchlist_id,)).fetchone()
    if not row: raise HTTPException(404,"watchlist not found")
    return row

def _check_category(v):
    if v not in _WATCHLIST_CATEGORIES: raise HTTPException(400,"category must be one of "+", ".join(_WATCHLIST_CATEGORIES))

def _check_watchlist_status(v):
    if v not in _WATCHLIST_STATUSES: raise HTTPException(400,"status must be active or archived")

@app.get("/v1/watchlists",tags=["watchlists"])
def list_watchlists(category:Optional[str]=None, status:str="all"):
    with conn() as c:
        rows=c.execute(f"""select {",".join("w."+x for x in _WATCHLIST_COLS.split(","))},count(m.member_id)
                           from watchlists w left join watchlist_members m on m.watchlist_id=w.watchlist_id
                           where (%s::text is null or w.category=%s) and (%s='all' or w.status=%s)
                           group by w.watchlist_id order by w.name""",(category,category,status,status)).fetchall()
    return [_watchlist_dict(r,r[7]) for r in rows]

@app.post("/v1/watchlists",tags=["watchlists"])
def create_watchlist(req:WatchlistIn):
    watchlist_id=_ref(req.watchlist_id,"watchlist_id",required=True)
    _check_category(req.category); _check_watchlist_status(req.status)
    with conn() as c:
        row=c.execute(f"""insert into watchlists(watchlist_id,name,category,description,status) values(%s,%s,%s,%s,%s)
                          on conflict(watchlist_id) do nothing returning {_WATCHLIST_COLS}""",
                      (watchlist_id,req.name.strip(),req.category,req.description,req.status)).fetchone()
    if not row: raise HTTPException(409,"watchlist_id already exists; use PATCH to update it")
    _audit("watchlist.created","watchlist",watchlist_id,{"name":row[1],"category":row[2],"status":row[4]})
    return _watchlist_dict(row,0)

@app.get("/v1/watchlists/{watchlist_id}",tags=["watchlists"])
def get_watchlist(watchlist_id:str):
    with conn() as c:
        row=_watchlist_or_404(c,watchlist_id)
        count=c.execute("select count(*) from watchlist_members where watchlist_id=%s",(watchlist_id,)).fetchone()[0]
    return _watchlist_dict(row,count)

@app.patch("/v1/watchlists/{watchlist_id}",tags=["watchlists"])
def patch_watchlist(watchlist_id:str, req:WatchlistPatch):
    changes=req.model_dump(exclude_unset=True)
    if "name" in changes:
        if changes["name"] is None or not changes["name"].strip(): raise HTTPException(400,"name cannot be empty")
        changes["name"]=changes["name"].strip()
    if "category" in changes: _check_category(changes["category"])
    if "status" in changes: _check_watchlist_status(changes["status"])
    with conn() as c:
        _watchlist_or_404(c,watchlist_id)
        for k,v in changes.items():
            c.execute(f"update watchlists set {k}=%s,updated_at=now() where watchlist_id=%s",(v,watchlist_id))
        row=_watchlist_or_404(c,watchlist_id)
    _audit("watchlist.updated","watchlist",watchlist_id,{"changes":changes})
    return _watchlist_dict(row)

@app.delete("/v1/watchlists/{watchlist_id}",tags=["watchlists"])
def delete_watchlist(watchlist_id:str):
    with conn() as c:
        _watchlist_or_404(c,watchlist_id)
        if c.execute("select 1 from watchlist_members where watchlist_id=%s limit 1",(watchlist_id,)).fetchone():
            raise HTTPException(409,"watchlist has members; remove them or archive it with PATCH status=archived")
        c.execute("delete from watchlists where watchlist_id=%s",(watchlist_id,))
    _audit("watchlist.deleted","watchlist",watchlist_id)
    return {"watchlist_id":watchlist_id,"deleted":True}

@app.get("/v1/watchlists/{watchlist_id}/members",tags=["watchlists"])
def list_watchlist_members(watchlist_id:str, include_expired:bool=True):
    with conn() as c:
        _watchlist_or_404(c,watchlist_id)
        rows=c.execute(f"""select {_MEMBER_COLS} from watchlist_members where watchlist_id=%s
                           and (%s or expires_at is null or expires_at>now()) order by created_at""",(watchlist_id,include_expired)).fetchall()
    return [_member_dict(r) for r in rows]

@app.post("/v1/watchlists/{watchlist_id}/members",tags=["watchlists"])
def add_watchlist_member(watchlist_id:str, req:WatchlistMemberIn):
    subject=_subject_ref(req.subject_ref,req.subject_id)
    pass_id=_ref(req.visitor_pass_id,"visitor_pass_id")
    if bool(subject)==bool(pass_id): raise HTTPException(400,"provide exactly one of subject_ref/subject_id or visitor_pass_id")
    kind,ref=("subject",subject) if subject else ("visitor_pass",pass_id)
    added_by=_ref(req.added_by_ref,"added_by_ref")
    expires_at=_parse_ts(req.expires_at,"expires_at") if req.expires_at else None
    with conn() as c:
        wl=_watchlist_or_404(c,watchlist_id)
        if wl[4]=="archived": raise HTTPException(409,"watchlist is archived")
        table,column=("subjects","subject_id") if kind=="subject" else ("visitor_passes","pass_id")
        if not _exists(c,table,column,ref): raise HTTPException(400,f"{kind} reference does not exist")
        row=c.execute(f"""insert into watchlist_members(member_id,watchlist_id,subject_kind,subject_ref,note,added_by_ref,expires_at)
                          values(%s,%s,%s,%s,%s,%s,%s) on conflict(watchlist_id,subject_kind,subject_ref) do nothing returning {_MEMBER_COLS}""",
                      ("wlm-"+uuid.uuid4().hex[:16],watchlist_id,kind,ref,req.note,added_by,expires_at)).fetchone()
        created=row is not None
        if not created:
            row=c.execute(f"select {_MEMBER_COLS} from watchlist_members where watchlist_id=%s and subject_kind=%s and subject_ref=%s",
                          (watchlist_id,kind,ref)).fetchone()
        else:
            c.execute("update watchlists set updated_at=now() where watchlist_id=%s",(watchlist_id,))
    if created: _audit("watchlist.member_added","watchlist",watchlist_id,{"member_id":row[0],"subject_kind":kind,"subject_ref":ref,
                       "category":wl[2],"added_by_ref":added_by,"expires_at":_iso(expires_at)})
    return {**_member_dict(row),"created":created}

@app.delete("/v1/watchlists/{watchlist_id}/members/{member_id}",tags=["watchlists"])
def remove_watchlist_member(watchlist_id:str, member_id:str):
    with conn() as c:
        _watchlist_or_404(c,watchlist_id)
        row=c.execute("delete from watchlist_members where watchlist_id=%s and member_id=%s returning subject_kind,subject_ref",(watchlist_id,member_id)).fetchone()
        if not row: raise HTTPException(404,"watchlist member not found")
        c.execute("update watchlists set updated_at=now() where watchlist_id=%s",(watchlist_id,))
    _audit("watchlist.member_removed","watchlist",watchlist_id,{"member_id":member_id,"subject_kind":row[0],"subject_ref":row[1]})
    return {"watchlist_id":watchlist_id,"member_id":member_id,"removed":True}

@app.get("/v1/subjects/{subject_id}/watchlists",tags=["watchlists"])
def subject_watchlists(subject_id:str):
    with conn() as c:
        if not _exists(c,"subjects","subject_id",subject_id): raise HTTPException(404,"subject not found")
        rows=c.execute(f"""select {",".join("m."+x for x in _MEMBER_COLS.split(","))},w.name,w.category,w.status
                           from watchlist_members m join watchlists w on w.watchlist_id=m.watchlist_id
                           where m.subject_kind='subject' and m.subject_ref=%s order by w.name""",(subject_id,)).fetchall()
    return [{**_member_dict(r),"watchlist_name":r[8],"category":r[9],"watchlist_status":r[10]} for r in rows]

# Mission 29 helpers - model / embedding version registry. The engine exposes no model-file hashes, so model_digest
# is SHA-256 over the canonical engine descriptor (digest_kind=descriptor-sha256).

_MODEL_COLS="model_key,provider,detector,recognizer,metric,model_id,model_version,model_digest,digest_kind,embedding_version,dimension,first_seen_at,last_seen_at"

def _engine_status():
    try:
        r=httpx.get(ENGINE+"/v1/model/status",timeout=5)
    except Exception:
        raise HTTPException(503,"recognition engine model status unavailable")
    if not r.is_success: raise HTTPException(503,"recognition engine model status unavailable")
    return r.json()

def _model_meta(status):
    desc={k:str(status.get(k) or "") for k in ("provider","detector","recognizer","metric")}
    if not desc["provider"] or not desc["recognizer"]: raise HTTPException(503,"recognition engine descriptor is incomplete")
    digest=hashlib.sha256(_canonical(desc)).hexdigest()
    return {**desc,"model_id":f"{desc['provider']}/{desc['recognizer']}","model_version":desc["recognizer"],
            "model_digest":"sha256:"+digest,"digest_kind":"descriptor-sha256",
            "model_key":f"{desc['provider']}:{desc['recognizer']}@{digest[:12]}",
            "embedding_version":f"{desc['recognizer']}:{desc['metric'] or 'cosine'}:l2norm"}

def _try_model_meta():
    try: return _model_meta(_engine_status())
    except HTTPException: return None

def _register_model(c, meta, dimension):
    c.execute("""insert into recognition_models(model_key,provider,detector,recognizer,metric,model_id,model_version,model_digest,digest_kind,
                 embedding_version,dimension) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                 on conflict(model_key) do update set last_seen_at=now(),dimension=coalesce(excluded.dimension,recognition_models.dimension)""",
              (meta["model_key"],meta["provider"],meta["detector"],meta["recognizer"],meta["metric"],meta["model_id"],meta["model_version"],
               meta["model_digest"],meta["digest_kind"],meta["embedding_version"],dimension))

def _model_dict(r):
    return dict(zip(_MODEL_COLS.split(","),r))

def _model_from_registry(c, model_key):
    if not model_key: return None
    row=c.execute(f"select {_MODEL_COLS} from recognition_models where model_key=%s",(model_key,)).fetchone()
    return _model_dict(row) if row else None

def _stamp_subject(c, subject_id, meta, dimension, method, image_count):
    m=meta or {}
    c.execute("""update subjects set model_key=%s,model_id=%s,model_version=%s,model_digest=%s,embedding_version=%s,embedding_dim=%s,
                 embedding_method=%s,embedding_image_count=%s,embedded_at=now() where subject_id=%s""",
              (m.get("model_key"),m.get("model_id"),m.get("model_version"),m.get("model_digest"),m.get("embedding_version"),
               dimension,method,image_count,subject_id))

def _archive_embedding(c, subject_id, reason):
    """Copy the current template into subject_embedding_history in the same transaction that replaces it,
    so the old embedding survives unless the replacement commits."""
    row=c.execute("""insert into subject_embedding_history(history_id,subject_id,embedding,model_key,embedding_version,embedding_method,reason)
                     select %s,subject_id,embedding,model_key,embedding_version,embedding_method,%s from subjects
                     where subject_id=%s and jsonb_typeof(embedding)='array' and jsonb_array_length(embedding)>0 returning history_id""",
                  ("eh-"+uuid.uuid4().hex[:20],reason,subject_id)).fetchone()
    return row[0] if row else None

# Mission 27 helpers - enrollment image quality. Quality checks are NOT liveness / presentation-attack detection.

_haar=None

def _engine_embed(image_b64):
    """Return (embedding, bbox) for the engine's largest face, or (None, None) when no face is detected."""
    try:
        r=httpx.post(ENGINE+"/v1/embeddings",json={"image_base64":image_b64},timeout=25)
    except Exception:
        raise HTTPException(503,"recognition engine unavailable")
    if r.status_code==422: return None,None
    if r.status_code==400: raise HTTPException(400,"image could not be decoded by the recognition engine")
    if not r.is_success: raise HTTPException(502,"recognition engine error")
    body=r.json()
    return body.get("embedding"),body.get("bbox")

def _secondary_faces(gray, bbox):
    """Count extra frontal faces of comparable size outside the engine's primary face. The engine reports only its
    largest detection, so the OpenCV-bundled Haar cascade is run locally to reject multi-face images."""
    global _haar
    if _haar is None:
        _haar=cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades,"haarcascade_frontalface_default.xml"))
    x,y,w,h=bbox
    side=max(24,min(w,h)//2)
    extra=0
    for fx,fy,fw,fh in _haar.detectMultiScale(gray,scaleFactor=1.1,minNeighbors=6,minSize=(side,side)):
        cx,cy=fx+fw/2,fy+fh/2
        if not (x<=cx<=x+w and y<=cy<=y+h): extra+=1
    return extra

def _quality_thresholds():
    return {"max_faces":ENROLL_MAX_FACES,"min_face_px":ENROLL_MIN_FACE_PX,"min_sharpness":ENROLL_MIN_SHARPNESS,
            "brightness_range":[ENROLL_MIN_BRIGHTNESS,ENROLL_MAX_BRIGHTNESS],"min_images":ENROLL_MIN_IMAGES,"max_images":ENROLL_MAX_IMAGES,
            "max_image_bytes":ENROLL_MAX_IMAGE_BYTES,"session_ttl_hours":ENROLL_SESSION_TTL_HOURS,
            "face_count_method":"engine primary detection + OpenCV Haar frontal cascade for additional faces",
            "sharpness_metric":"variance of Laplacian over the grayscale face crop",
            "brightness_metric":"mean grayscale value (0-255) over the face crop","pose_supported":False,"liveness":False}

def _analyze_image(image_b64):
    """Return (quality, reasons, embedding|None, image_sha256). The image itself is never stored."""
    if len(image_b64)>ENROLL_MAX_IMAGE_BYTES*4//3+4: raise HTTPException(413,"image exceeds the enrollment size limit")
    try:
        raw=base64.b64decode(image_b64,validate=True)
    except Exception:
        raise HTTPException(400,"image_base64 is not valid base64")
    if len(raw)>ENROLL_MAX_IMAGE_BYTES: raise HTTPException(413,"image exceeds the enrollment size limit")
    sha=hashlib.sha256(raw).hexdigest()
    img=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
    if img is None: raise HTTPException(400,"image could not be decoded")
    h,w=img.shape[:2]
    q={"width":int(w),"height":int(h),"face_count":0,"face_bbox":None,"face_min_side_px":None,"sharpness":None,"brightness":None,
       "pose":None,"pose_supported":False,"liveness_checked":False}
    emb,bbox=_engine_embed(image_b64)
    if emb is None or not bbox or len(bbox)<4: return q,["no_face_detected"],None,sha
    x,y,bw,bh=[int(round(float(v))) for v in bbox[:4]]
    x0,y0,x1,y1=max(0,x),max(0,y),min(w,x+bw),min(h,y+bh)
    if x1<=x0 or y1<=y0: return q,["face_out_of_frame"],None,sha
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    crop=gray[y0:y1,x0:x1]
    q.update(face_count=1+_secondary_faces(gray,(x0,y0,x1-x0,y1-y0)),face_bbox=[x0,y0,x1-x0,y1-y0],face_min_side_px=min(x1-x0,y1-y0),
             sharpness=round(float(cv2.Laplacian(crop,cv2.CV_64F).var()),2),brightness=round(float(crop.mean()),2))
    reasons=[]
    if q["face_count"]>ENROLL_MAX_FACES: reasons.append("multiple_faces")
    if q["face_min_side_px"]<ENROLL_MIN_FACE_PX: reasons.append("face_too_small")
    if q["sharpness"]<ENROLL_MIN_SHARPNESS: reasons.append("too_blurry")
    if q["brightness"]<ENROLL_MIN_BRIGHTNESS: reasons.append("too_dark")
    elif q["brightness"]>ENROLL_MAX_BRIGHTNESS: reasons.append("too_bright")
    vec=np.asarray(emb,dtype=np.float64)
    if vec.ndim!=1 or not vec.size or not np.all(np.isfinite(vec)) or not np.linalg.norm(vec): reasons.append("invalid_embedding")
    return q,reasons,(None if reasons else [float(v) for v in vec]),sha

def _aggregate(vectors):
    """l2-mean-l2/v1: L2-normalise each accepted embedding (float64), take the element-wise arithmetic mean in image
    sequence order, L2-normalise the mean, and round each component to 8 decimal places."""
    arr=[np.asarray(v,dtype=np.float64) for v in vectors]
    if len({a.size for a in arr})!=1: raise HTTPException(409,"accepted embeddings have different dimensions")
    m=np.stack([a/np.linalg.norm(a) for a in arr]).mean(axis=0)
    n=np.linalg.norm(m)
    if not n: raise HTTPException(409,"accepted embeddings cancel out; capture new images")
    return [round(float(x),8) for x in m/n]

def _cosine(a, b):
    a=np.asarray(a,dtype=np.float64); b=np.asarray(b,dtype=np.float64)
    na,nb=np.linalg.norm(a),np.linalg.norm(b)
    return float(a@b/(na*nb)) if na and nb else -1.0

# Mission 27 - multi-image enrollment sessions

_SESSION_COLS="session_id,subject_id,display_name,consent_reference,retention_days,operator_ref,status,subject_existed,created_at,updated_at,expires_at,finalized_at"
_IMAGE_COLS="image_id,seq,status,reasons,quality,model_key,created_at"

def _session_dict(r):
    status=r[6]
    if status=="open" and r[10]<=datetime.datetime.now(datetime.timezone.utc): status="expired"
    return {"session_id":r[0],"subject_id":r[1],"display_name":r[2],"consent_reference":r[3],"retention_days":r[4],"operator_ref":r[5],
            "status":status,"re_enrollment":r[7],"created_at":r[8],"updated_at":r[9],"expires_at":r[10],"finalized_at":r[11],
            "aggregation_method":_AGGREGATION_METHOD,"liveness_checked":False}

def _image_dict(r):
    return {"image_id":r[0],"seq":r[1],"status":r[2],"accepted":r[2]=="accepted","reasons":r[3],"quality":r[4],"model_key":r[5],"created_at":r[6]}

def _session_or_404(c, session_id, lock=False):
    row=c.execute(f"select {_SESSION_COLS} from enrollment_sessions where session_id=%s"+(" for update" if lock else ""),(session_id,)).fetchone()
    if not row: raise HTTPException(404,"enrollment session not found")
    return row

def _open_session(c, session_id, lock=False):
    row=_session_or_404(c,session_id,lock)
    status=_session_dict(row)["status"]
    if status!="open": raise HTTPException(409,f"enrollment session is {status}")
    return row

def _close_session(c, session_id, status):
    """Close a session and purge its per-image templates; quality metadata is kept for audit."""
    c.execute("update enrollment_sessions set status=%s,updated_at=now(),finalized_at=case when %s='finalized' then now() else null end where session_id=%s",
              (status,status,session_id))
    c.execute("update enrollment_session_images set embedding=null where session_id=%s",(session_id,))
    c.execute("""update duplicate_candidates set status='resolved',resolution='session_closed',resolved_at=now(),updated_at=now()
                 where session_id=%s and status='open'""",(session_id,))

@app.get("/v1/enrollment-sessions",tags=["enrollment-sessions"])
def list_enrollment_sessions(status:str="all", subject_id:Optional[str]=None, limit:int=200):
    limit=max(1,min(limit,1000))
    with conn() as c:
        rows=c.execute(f"""select {_SESSION_COLS} from enrollment_sessions where (%s::text is null or subject_id=%s)
                           order by created_at desc limit %s""",(subject_id,subject_id,limit)).fetchall()
    out=[_session_dict(r) for r in rows]
    return [s for s in out if status=="all" or s["status"]==status]

@app.post("/v1/enrollment-sessions",tags=["enrollment-sessions"])
def create_enrollment_session(req:EnrollmentSessionIn):
    if not req.consent_obtained: raise HTTPException(400,"explicit enrollment consent is required")
    subject_id=_ref(req.subject_id,"subject_id",required=True)
    operator_ref=_ref(req.operator_ref,"operator_ref")
    session_id="es-"+uuid.uuid4().hex[:20]
    expires=datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=ENROLL_SESSION_TTL_HOURS)
    with conn() as c:
        for (stale,) in c.execute("select session_id from enrollment_sessions where subject_id=%s and status='open' and expires_at<=now()",(subject_id,)).fetchall():
            _close_session(c,stale,"expired")
        existed=_exists(c,"subjects","subject_id",subject_id)
        row=c.execute(f"""insert into enrollment_sessions(session_id,subject_id,display_name,consent_reference,retention_days,operator_ref,subject_existed,expires_at)
                          values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning {_SESSION_COLS}""",
                      (session_id,subject_id,req.display_name.strip(),req.consent_reference.strip(),req.retention_days,operator_ref,existed,expires)).fetchone()
    if not row: raise HTTPException(409,"an open enrollment session already exists for this subject_id")
    _audit("enrollment_session.created","enrollment_session",session_id,{"subject_id":subject_id,"re_enrollment":existed,
           "operator_ref":operator_ref,"consent_reference":req.consent_reference.strip()})
    return {**_session_dict(row),"thresholds":_quality_thresholds()}

@app.get("/v1/enrollment-sessions/{session_id}",tags=["enrollment-sessions"])
def get_enrollment_session(session_id:str):
    with conn() as c:
        row=_session_or_404(c,session_id)
        images=c.execute(f"select {_IMAGE_COLS} from enrollment_session_images where session_id=%s order by seq",(session_id,)).fetchall()
        cands=c.execute(f"select {_CANDIDATE_COLS} from duplicate_candidates where session_id=%s order by score desc",(session_id,)).fetchall()
    return {**_session_dict(row),"images":[_image_dict(i) for i in images],"accepted_images":sum(1 for i in images if i[2]=="accepted"),
            "duplicate_candidates":[_candidate_dict(x) for x in cands],"thresholds":_quality_thresholds()}

@app.post("/v1/enrollment-sessions/{session_id}/images",tags=["enrollment-sessions"])
def add_enrollment_image(session_id:str, req:EnrollmentImageIn):
    if not req.consent_obtained: raise HTTPException(400,"explicit consent is required for each enrollment image")
    with conn() as c:
        _open_session(c,session_id)
    quality,reasons,vec,sha=_analyze_image(req.image_base64)
    meta=_model_meta(_engine_status()) if vec is not None else None
    with conn() as c:
        _open_session(c,session_id,lock=True)
        accepted=c.execute("select model_key,image_sha256 from enrollment_session_images where session_id=%s and status='accepted'",(session_id,)).fetchall()
        if len(accepted)>=ENROLL_MAX_IMAGES: raise HTTPException(409,f"session already has the maximum of {ENROLL_MAX_IMAGES} accepted images")
        if not reasons and any(a[1]==sha for a in accepted): reasons.append("duplicate_image")
        if not reasons and any(a[0]!=meta["model_key"] for a in accepted): reasons.append("model_version_changed")
        status="rejected" if reasons else "accepted"
        if status=="accepted": _register_model(c,meta,len(vec))
        seq=c.execute("select coalesce(max(seq),0)+1 from enrollment_session_images where session_id=%s",(session_id,)).fetchone()[0]
        row=c.execute(f"""insert into enrollment_session_images(image_id,session_id,seq,status,reasons,quality,image_sha256,embedding,model_key)
                          values(%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s) returning {_IMAGE_COLS}""",
                      ("esi-"+uuid.uuid4().hex[:16],session_id,seq,status,json.dumps(reasons),json.dumps(quality),sha,
                       json.dumps(vec) if status=="accepted" else None,meta["model_key"] if status=="accepted" else None)).fetchone()
        c.execute("update enrollment_sessions set updated_at=now() where session_id=%s",(session_id,))
    out=_image_dict(row)
    _audit("enrollment_image."+status,"enrollment_session",session_id,{"image_id":out["image_id"],"seq":seq,"reasons":reasons,
           "face_count":quality["face_count"],"face_min_side_px":quality["face_min_side_px"],"sharpness":quality["sharpness"],"brightness":quality["brightness"]})
    if reasons: raise HTTPException(422,{"message":"image rejected by enrollment quality checks",**out,"created_at":_iso(out["created_at"])})
    return out

def _session_aggregate(c, session_id):
    rows=c.execute("""select embedding,model_key from enrollment_session_images where session_id=%s and status='accepted'
                      and embedding is not null order by seq""",(session_id,)).fetchall()
    if len(rows)<ENROLL_MIN_IMAGES: raise HTTPException(409,f"at least {ENROLL_MIN_IMAGES} accepted image(s) are required")
    keys={r[1] for r in rows}
    if len(keys)!=1: raise HTTPException(409,"accepted images were embedded by different model versions")
    return _aggregate([r[0] for r in rows]),keys.pop(),len(rows)

# Mission 28 - duplicate enrollment candidates. Candidates are for operator review only: FACE-ID never merges subjects
# and never asserts that two subjects are the same person.

_CANDIDATE_COLS="candidate_id,session_id,subject_ref,candidate_subject_ref,score,threshold,embedding_version,version_unverified,status,resolution,note,resolver_ref,created_at,updated_at,resolved_at"

def _candidate_dict(r):
    return {**dict(zip(_CANDIDATE_COLS.split(","),r)),"identity_asserted":False,"auto_merge":False}

def _run_duplicate_check(c, session_row, aggregate, model_key):
    """Score the session aggregate against other subjects with DUPLICATE_THRESHOLD (distinct from MATCH_THRESHOLD).
    Subjects on a different embedding_version are skipped; unversioned legacy subjects are compared and flagged."""
    version=_model_from_registry(c,model_key)["embedding_version"]
    subjects=c.execute("select subject_id,embedding,embedding_version from subjects where subject_id<>%s",(session_row[1],)).fetchall()
    scored=[]; skipped=0
    for sid,emb,ver in subjects:
        if (ver and ver!=version) or not isinstance(emb,list) or len(emb)!=len(aggregate):
            skipped+=1; continue
        s=_cosine(aggregate,emb)
        if s>=DUPLICATE_THRESHOLD: scored.append((s,sid,ver is None))
    scored.sort(key=lambda x:(-x[0],x[1]))
    new=[]
    for s,sid,unverified in scored[:DUPLICATE_MAX_CANDIDATES]:
        row=c.execute("""insert into duplicate_candidates(candidate_id,session_id,subject_ref,candidate_subject_ref,score,threshold,embedding_version,version_unverified)
                         values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(session_id,candidate_subject_ref) do update set score=excluded.score,
                         threshold=excluded.threshold,updated_at=now() returning candidate_id,(xmax=0)""",
                      ("dc-"+uuid.uuid4().hex[:16],session_row[0],session_row[1],sid,round(s,6),DUPLICATE_THRESHOLD,version,unverified)).fetchone()
        if row[1]: new.append({"candidate_id":row[0],"candidate_subject_ref":sid,"score":round(s,6)})
    return new,skipped,version

@app.post("/v1/enrollment-sessions/{session_id}/duplicate-check",tags=["duplicate-candidates"])
def enrollment_duplicate_check(session_id:str):
    with conn() as c:
        row=_open_session(c,session_id,lock=True)
        aggregate,model_key,count=_session_aggregate(c,session_id)
        new,skipped,version=_run_duplicate_check(c,row,aggregate,model_key)
        cands=c.execute(f"select {_CANDIDATE_COLS} from duplicate_candidates where session_id=%s order by score desc",(session_id,)).fetchall()
    if new: _audit("duplicate_candidate.detected","enrollment_session",session_id,{"subject_ref":row[1],"candidates":new,"threshold":DUPLICATE_THRESHOLD})
    return {"session_id":session_id,"threshold":DUPLICATE_THRESHOLD,"recognition_threshold":MATCH_THRESHOLD,"embedding_version":version,
            "accepted_images":count,"skipped_incompatible_subjects":skipped,"new_candidates":new,"candidates":[_candidate_dict(x) for x in cands],
            "identity_asserted":False,"auto_merge":False}

@app.post("/v1/enrollment-sessions/{session_id}/finalize",tags=["enrollment-sessions"])
def finalize_enrollment_session(session_id:str):
    blocked=None
    with conn() as c:
        row=_open_session(c,session_id,lock=True)
        aggregate,model_key,count=_session_aggregate(c,session_id)
        new,skipped,version=_run_duplicate_check(c,row,aggregate,model_key)
        blocking=c.execute(f"""select {_CANDIDATE_COLS} from duplicate_candidates where session_id=%s
                               and (status='open' or resolution='duplicate_confirmed') order by score desc""",(session_id,)).fetchall()
        if blocking:
            blocked=[_candidate_dict(x) for x in blocking]
        else:
            subject_id=row[1]
            history_id=_archive_embedding(c,subject_id,"enrollment_session:"+session_id)
            c.execute("""insert into subjects(subject_id,display_name,embedding,consent_obtained,consent_reference,retention_days,enrollment_source)
                         values(%s,%s,%s::jsonb,true,%s,%s,'enrollment-session')
                         on conflict(subject_id) do update set display_name=excluded.display_name,embedding=excluded.embedding,consent_obtained=true,
                         consent_reference=excluded.consent_reference,retention_days=excluded.retention_days,enrollment_source='enrollment-session',updated_at=now()""",
                      (subject_id,row[2],json.dumps(aggregate),row[3],row[4]))
            _stamp_subject(c,subject_id,_model_from_registry(c,model_key),len(aggregate),_AGGREGATION_METHOD,count)
            _close_session(c,session_id,"finalized")
    if new: _audit("duplicate_candidate.detected","enrollment_session",session_id,{"subject_ref":row[1],"candidates":new,"threshold":DUPLICATE_THRESHOLD})
    if blocked:
        for b in blocked:
            for k in ("created_at","updated_at","resolved_at"): b[k]=_iso(b[k])
        raise HTTPException(409,{"message":"duplicate candidates must be resolved as not_duplicate or dismissed before finalize",
                                 "candidates":blocked})
    _audit("enrollment_session.finalized","enrollment_session",session_id,{"subject_id":row[1],"re_enrollment":row[7],"image_count":count,
           "aggregation_method":_AGGREGATION_METHOD,"model_key":model_key,"embedding_version":version,"archived_history_id":history_id})
    return {"session_id":session_id,"status":"finalized","subject_id":row[1],"enrolled":True,"image_count":count,
            "aggregation_method":_AGGREGATION_METHOD,"model_key":model_key,"embedding_version":version,"archived_history_id":history_id,
            "skipped_incompatible_subjects":skipped,"liveness_checked":False}

@app.post("/v1/enrollment-sessions/{session_id}/cancel",tags=["enrollment-sessions"])
def cancel_enrollment_session(session_id:str):
    with conn() as c:
        row=_open_session(c,session_id,lock=True)
        _close_session(c,session_id,"cancelled")
    _audit("enrollment_session.cancelled","enrollment_session",session_id,{"subject_id":row[1]})
    return {"session_id":session_id,"status":"cancelled"}

@app.get("/v1/duplicate-candidates",tags=["duplicate-candidates"])
def list_duplicate_candidates(status:str="open", session_id:Optional[str]=None, limit:int=200):
    if status not in {"all","open","resolved"}: raise HTTPException(400,"status must be all, open, or resolved")
    limit=max(1,min(limit,1000))
    with conn() as c:
        rows=c.execute(f"""select {_CANDIDATE_COLS} from duplicate_candidates where (%s='all' or status=%s)
                           and (%s::text is null or session_id=%s) order by created_at desc,score desc limit %s""",
                       (status,status,session_id,session_id,limit)).fetchall()
    return [_candidate_dict(r) for r in rows]

@app.post("/v1/duplicate-candidates/{candidate_id}/resolve",tags=["duplicate-candidates"])
def resolve_duplicate_candidate(candidate_id:str, req:DuplicateResolveIn):
    if req.resolution not in _DUPLICATE_RESOLUTIONS: raise HTTPException(400,"resolution must be not_duplicate, duplicate_confirmed, or dismissed")
    resolver=_ref(req.resolver_ref,"resolver_ref")
    with conn() as c:
        cur=c.execute("select status from duplicate_candidates where candidate_id=%s for update",(candidate_id,)).fetchone()
        if not cur: raise HTTPException(404,"duplicate candidate not found")
        if cur[0]!="open": raise HTTPException(409,"duplicate candidate is already resolved")
        row=c.execute(f"""update duplicate_candidates set status='resolved',resolution=%s,note=%s,resolver_ref=%s,resolved_at=now(),updated_at=now()
                          where candidate_id=%s returning {_CANDIDATE_COLS}""",(req.resolution,req.note,resolver,candidate_id)).fetchone()
    _audit("duplicate_candidate.resolved","duplicate_candidate",candidate_id,{"session_id":row[1],"subject_ref":row[2],
           "candidate_subject_ref":row[3],"score":row[4],"resolution":req.resolution,"resolver_ref":resolver,"note":req.note})
    return _candidate_dict(row)

# Mission 29 - read-only model registry, migration status, and non-destructive re-embedding queue

_JOB_COLS="job_id,subject_id,status,reason,requested_by_ref,source_embedding_version,target_embedding_version,target_model_key,history_id,error,consent_reference,created_at,updated_at,completed_at"

def _job_dict(r):
    return dict(zip(_JOB_COLS.split(","),r))

@app.get("/v1/models",tags=["model-registry"])
def list_models():
    with conn() as c:
        rows=c.execute(f"select {_MODEL_COLS} from recognition_models order by first_seen_at").fetchall()
        counts=dict(c.execute("select model_key,count(*) from subjects where model_key is not null group by model_key").fetchall())
    return [{**_model_dict(r),"subject_count":counts.get(r[0],0)} for r in rows]

@app.get("/v1/models/current",tags=["model-registry"])
def current_model():
    meta=_model_meta(_engine_status())
    with conn() as c:
        registered=_model_from_registry(c,meta["model_key"])
    return {**meta,"registered":registered is not None,"dimension":registered and registered["dimension"]}

@app.get("/v1/models/migration-status",tags=["model-registry"])
def model_migration_status():
    current=None; engine_error=None
    try: current=_model_meta(_engine_status())
    except HTTPException as e: engine_error=e.detail
    with conn() as c:
        versions=c.execute("select embedding_version,count(*) from subjects group by embedding_version order by embedding_version nulls first").fetchall()
        jobs=dict(c.execute("select status,count(*) from reembedding_jobs group by status").fetchall())
        archived=c.execute("select count(*) from subject_embedding_history").fetchone()[0]
    target=current and current["embedding_version"]
    total=sum(v[1] for v in versions)
    on_target=sum(v[1] for v in versions if target and v[0]==target)
    return {"current_model":current,"engine_error":engine_error,"subjects_total":total,
            "subjects_by_embedding_version":[{"embedding_version":v[0],"count":v[1],"current":bool(target) and v[0]==target} for v in versions],
            "subjects_on_current_version":on_target if target else None,"subjects_needing_migration":total-on_target if target else None,
            "unversioned_subjects":sum(v[1] for v in versions if v[0] is None),
            "reembedding_jobs":{s:jobs.get(s,0) for s in sorted(_JOB_STATUSES)},"archived_embeddings":archived,
            "embedding_history_retention_days":EMBEDDING_HISTORY_DAYS,"automatic_migration":False}

@app.get("/v1/reembedding-jobs",tags=["model-registry"])
def list_reembedding_jobs(status:str="all", subject_id:Optional[str]=None, limit:int=200):
    limit=max(1,min(limit,1000))
    with conn() as c:
        rows=c.execute(f"""select {_JOB_COLS} from reembedding_jobs where (%s='all' or status=%s) and (%s::text is null or subject_id=%s)
                           order by created_at desc limit %s""",(status,status,subject_id,subject_id,limit)).fetchall()
    return [_job_dict(r) for r in rows]

@app.post("/v1/reembedding-jobs",tags=["model-registry"])
def queue_reembedding_jobs(req:ReembeddingJobsIn):
    """Queue records only. Nothing is re-embedded until an operator completes a job with new consented images."""
    subject_ids=list(dict.fromkeys(_ref(x,"subject_id",required=True) for x in req.subject_ids))
    requested_by=_ref(req.requested_by_ref,"requested_by_ref")
    meta=_model_meta(_engine_status())
    created=[]; existing=[]
    with conn() as c:
        found=dict(c.execute("select subject_id,embedding_version from subjects where subject_id = any(%s)",(subject_ids,)).fetchall())
        missing=[x for x in subject_ids if x not in found]
        if missing: raise HTTPException(400,"one or more subject_ids do not exist")
        for sid in subject_ids:
            row=c.execute(f"""insert into reembedding_jobs(job_id,subject_id,reason,requested_by_ref,source_embedding_version,target_embedding_version,target_model_key)
                              values(%s,%s,%s,%s,%s,%s,%s) on conflict(subject_id) where status='queued' do nothing returning {_JOB_COLS}""",
                          ("rej-"+uuid.uuid4().hex[:16],sid,req.reason.strip(),requested_by,found[sid],meta["embedding_version"],meta["model_key"])).fetchone()
            if row: created.append(_job_dict(row))
            else: existing.append(_job_dict(c.execute(f"select {_JOB_COLS} from reembedding_jobs where subject_id=%s and status='queued'",(sid,)).fetchone()))
    for j in created:
        _audit("reembedding_job.queued","reembedding_job",j["job_id"],{"subject_id":j["subject_id"],"source_embedding_version":j["source_embedding_version"],
               "target_embedding_version":j["target_embedding_version"],"requested_by_ref":requested_by,"reason":j["reason"]})
    return {"created":created,"existing":existing,"target_embedding_version":meta["embedding_version"],"destructive":False}

@app.post("/v1/reembedding-jobs/{job_id}/complete",tags=["model-registry"])
def complete_reembedding_job(job_id:str, req:ReembeddingCompleteIn):
    if not req.consent_obtained: raise HTTPException(400,"explicit consent is required for re-embedding images")
    with conn() as c:
        job=c.execute(f"select {_JOB_COLS} from reembedding_jobs where job_id=%s",(job_id,)).fetchone()
    if not job: raise HTTPException(404,"re-embedding job not found")
    if job[2]!="queued": raise HTTPException(409,f"re-embedding job is {job[2]}")
    results=[_analyze_image(b) for b in req.images_base64]
    shas=[r[3] for r in results]
    rejected=[{"index":i,"reasons":r[1]+(["duplicate_image"] if shas.index(r[3])!=i else []),"quality":r[0]} for i,r in enumerate(results)
              if r[1] or shas.index(r[3])!=i]
    if rejected: raise HTTPException(422,{"message":"one or more images rejected by enrollment quality checks; job remains queued","rejected":rejected})
    meta=_model_meta(_engine_status())
    aggregate=_aggregate([r[2] for r in results])
    error=None; history_id=None
    with conn() as c:
        cur=c.execute("select status,subject_id,target_embedding_version from reembedding_jobs where job_id=%s for update",(job_id,)).fetchone()
        if cur[0]!="queued": raise HTTPException(409,f"re-embedding job is {cur[0]}")
        if meta["embedding_version"]!=cur[2]: error="target_embedding_version_mismatch"
        elif not _exists(c,"subjects","subject_id",cur[1]): error="subject_not_found"
        if error:
            c.execute("update reembedding_jobs set status='failed',error=%s,updated_at=now(),completed_at=now() where job_id=%s",(error,job_id))
        else:
            _register_model(c,meta,len(aggregate))
            history_id=_archive_embedding(c,cur[1],"reembedding_job:"+job_id)
            c.execute("update subjects set embedding=%s::jsonb,updated_at=now() where subject_id=%s",(json.dumps(aggregate),cur[1]))
            _stamp_subject(c,cur[1],meta,len(aggregate),_AGGREGATION_METHOD,len(results))
            c.execute("""update reembedding_jobs set status='succeeded',history_id=%s,consent_reference=%s,updated_at=now(),completed_at=now()
                         where job_id=%s""",(history_id,req.consent_reference,job_id))
        row=c.execute(f"select {_JOB_COLS} from reembedding_jobs where job_id=%s",(job_id,)).fetchone()
    if error:
        _audit("reembedding_job.failed","reembedding_job",job_id,{"subject_id":cur[1],"error":error,"engine_embedding_version":meta["embedding_version"]})
        raise HTTPException(409,{"message":"re-embedding failed; the existing embedding was not changed","error":error})
    _audit("reembedding_job.succeeded","reembedding_job",job_id,{"subject_id":cur[1],"embedding_version":meta["embedding_version"],
           "model_key":meta["model_key"],"image_count":len(results),"archived_history_id":history_id})
    return {**_job_dict(row),"image_count":len(results),"aggregation_method":_AGGREGATION_METHOD}

@app.post("/v1/reembedding-jobs/{job_id}/cancel",tags=["model-registry"])
def cancel_reembedding_job(job_id:str):
    with conn() as c:
        row=c.execute("""update reembedding_jobs set status='cancelled',updated_at=now(),completed_at=now()
                         where job_id=%s and status='queued' returning subject_id""",(job_id,)).fetchone()
        if not row:
            if not _exists(c,"reembedding_jobs","job_id",job_id): raise HTTPException(404,"re-embedding job not found")
            raise HTTPException(409,"only queued re-embedding jobs can be cancelled")
    _audit("reembedding_job.cancelled","reembedding_job",job_id,{"subject_id":row[0]})
    return {"job_id":job_id,"status":"cancelled"}

# Mission 30 - bounded, redacted, integrity-checked audit export and audit retention readback

_BIOMETRIC_KEY_RE=re.compile(r"^(embeddings?|templates?|face_template|images?|image_base64|images_base64|image_[ab]_base64|snapshots?|snapshot_bytes|"
                             r"features?|vectors?|photos?|face_crop|biometric\w*)$",re.I)
_SECRET_KEY_RE=re.compile(r"(^|_)(password|passwd|passphrase|secret|token|api_?key|authorization|credentials?|cookie|private_?key|signature|hmac_key)($|_)",re.I)
_IDENTIFIER_KEYS={"id_hash"}
_B64ISH_RE=re.compile(r"^[A-Za-z0-9+/=_\-\s]+$")
_BEARER_RE=re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")

def _redact(value, counts, key=None):
    if key is not None:
        if _BIOMETRIC_KEY_RE.match(key): counts["biometric"]+=1; return "[REDACTED:biometric]"
        if not key.lower().endswith("_env") and _SECRET_KEY_RE.search(key): counts["secret"]+=1; return "[REDACTED:secret]"
        if key.lower() in _IDENTIFIER_KEYS: counts["identifier"]+=1; return "[REDACTED:identifier]"
    if isinstance(value,dict): return {k:_redact(v,counts,str(k)) for k,v in value.items()}
    if isinstance(value,list):
        if len(value)>=32 and all(isinstance(x,(int,float)) and not isinstance(x,bool) for x in value):
            counts["biometric"]+=1; return "[REDACTED:biometric]"
        return [_redact(v,counts) for v in value]
    if isinstance(value,str):
        if value.startswith("data:image") or (len(value)>=512 and _B64ISH_RE.match(value)):
            counts["biometric"]+=1; return "[REDACTED:biometric]"
        if _BEARER_RE.search(value):
            counts["secret"]+=1; return _BEARER_RE.sub(r"\1 [REDACTED:secret]",value)
    return value

def _audit_retention(c):
    pol=c.execute("select policy_id,days,enabled,updated_at from retention_policies where resource_type='audit'").fetchone()
    stats=c.execute("select count(*),min(occurred_at),max(occurred_at) from audit_log").fetchone()
    older=None
    if pol and pol[2]:
        older=c.execute("select count(*) from audit_log where occurred_at < now() - (%s * interval '1 day')",(pol[1],)).fetchone()[0]
    return {"resource_type":"audit","policy":{"policy_id":pol[0],"days":pol[1],"enabled":pol[2],"updated_at":_iso(pol[3])} if pol else None,
            "enforced":False,"enforcement":"advisory: FACE-ID never deletes audit records automatically; export before any operator-run purge",
            "record_count":stats[0],"oldest_occurred_at":_iso(stats[1]),"newest_occurred_at":_iso(stats[2]),
            "records_older_than_policy":older,"export_max_range_days":AUDIT_EXPORT_MAX_DAYS}

@app.get("/v1/audit/retention",tags=["audit-compliance"])
def audit_retention():
    with conn() as c:
        return _audit_retention(c)

def _b64url(obj):
    return base64.urlsafe_b64encode(_canonical(obj)).decode().rstrip("=")

@app.get("/v1/audit/export",tags=["audit-compliance"])
def audit_export(since:str, until:str, actor:Optional[str]=None, action:Optional[str]=None, target_type:Optional[str]=None,
                 limit:int=500, cursor:Optional[str]=None):
    since_ts=_parse_ts(since,"since"); until_ts=_parse_ts(until,"until")
    if until_ts<=since_ts: raise HTTPException(400,"until must be after since")
    if until_ts-since_ts>datetime.timedelta(days=AUDIT_EXPORT_MAX_DAYS):
        raise HTTPException(400,f"export range must not exceed {AUDIT_EXPORT_MAX_DAYS} days")
    limit=max(1,min(limit,1000))
    prefix=None
    if action and action.endswith("*"):
        prefix=action[:-1].replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
    filters={"since":_iso(since_ts),"until":_iso(until_ts),"actor":actor,"action":action,"target_type":target_type,"limit":limit}
    filters_digest=hashlib.sha256(_canonical(filters)).hexdigest()
    after_t=after_id=None; seed="0"*64; page=1
    if cursor:
        try:
            cur=json.loads(base64.urlsafe_b64decode(cursor+"="*(-len(cursor)%4)))
            after_t=datetime.datetime.fromisoformat(cur["t"]); after_id=str(cur["id"]); seed=str(cur["c"]); page=int(cur["p"])+1
            if cur["f"]!=filters_digest: raise HTTPException(400,"cursor does not match the export filters")
            if not re.fullmatch(r"[0-9a-f]{64}",seed) or after_t.tzinfo is None: raise ValueError
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400,"invalid cursor")
    with conn() as c:
        rows=c.execute("""select audit_id,actor,action,target_type,target_id,details,occurred_at from audit_log
                          where occurred_at>=%s and occurred_at<%s
                          and (%s::text is null or actor=%s)
                          and (%s::text is null or %s::text is not null or action=%s)
                          and (%s::text is null or action like %s)
                          and (%s::text is null or target_type=%s)
                          and (%s::timestamptz is null or (occurred_at,audit_id)>(%s::timestamptz,%s::text))
                          order by occurred_at,audit_id limit %s""",
                       (since_ts,until_ts,actor,actor,action,prefix,action,prefix,prefix,target_type,target_type,after_t,after_t,after_id,limit+1)).fetchall()
        retention=_audit_retention(c)
    counts={"secret":0,"biometric":0,"identifier":0}
    records=[]; chain=seed; digests=[]
    for r in rows[:limit]:
        rec={"audit_id":r[0],"occurred_at":_iso(r[6]),"actor":r[1],"action":r[2],"target_type":r[3],"target_id":r[4],
             "details":_redact(r[5] or {},counts)}
        d=hashlib.sha256(_canonical(rec)).hexdigest()
        chain=hashlib.sha256((chain+d).encode()).hexdigest()
        records.append({**rec,"record_sha256":d}); digests.append(d)
    has_more=len(rows)>limit
    next_cursor=_b64url({"t":records[-1]["occurred_at"],"id":records[-1]["audit_id"],"c":chain,"p":page,"f":filters_digest}) if has_more else None
    export_id="aex-"+uuid.uuid4().hex[:20]
    manifest={"export_id":export_id,"format":"faceid-audit-export/v1","generated_at":_iso(datetime.datetime.now(datetime.timezone.utc)),
              "service":{"name":app.title,"version":app.version},"filters":filters,"filters_sha256":filters_digest,"page":page,
              "record_count":len(records),"has_more":has_more,"next_cursor":next_cursor,
              "first_occurred_at":records[0]["occurred_at"] if records else None,"last_occurred_at":records[-1]["occurred_at"] if records else None,
              "integrity":{"record_digest":"sha256 over canonical JSON (sorted keys, compact separators, UTF-8) of each record without record_sha256",
                           "chain_algorithm":"chain_i = sha256(hex(chain_{i-1}) + hex(record_sha256_i)); page 1 seed is 64 zeros",
                           "chain_seed":seed,"chain_head":chain,"page_sha256":hashlib.sha256("".join(digests).encode()).hexdigest()},
              "redaction":{"policy":_REDACTION_POLICY,"secret_values":counts["secret"],"biometric_values":counts["biometric"],
                           "identifier_values":counts["identifier"],"biometric_templates_included":False,"secrets_included":False},
              "retention":retention}
    if AUDIT_EXPORT_HMAC_KEY:
        manifest["signature"]={"algorithm":"hmac-sha256","key_id":AUDIT_EXPORT_KEY_ID,"signed_content":"canonical manifest without signature",
                               "value":hmac.new(AUDIT_EXPORT_HMAC_KEY.encode(),_canonical(manifest),hashlib.sha256).hexdigest()}
    else:
        manifest["signature"]=None
    _audit("audit.exported","audit_export",export_id,{"filters":filters,"page":page,"record_count":len(records),"chain_head":chain,
           "signed":bool(AUDIT_EXPORT_HMAC_KEY)})
    return {"manifest":manifest,"records":records}
