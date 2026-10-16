import base64, datetime, hashlib, hmac, json
import cv2, numpy as np, pytest
from conftest import uid, sql, audit_for
from app import main

STATUS={"provider":"opencv-sface","detector":"yunet-2023mar","recognizer":"sface-2021dec","metric":"cosine","default_threshold":0.363}

def unit(seed, dim=128):
    v=np.random.default_rng(seed).normal(size=dim)
    return v/np.linalg.norm(v)

def image(seed=1, value=None, size=240):
    """Synthetic textured image (no real person). value=<int> gives a flat, blur-failing image."""
    rng=np.random.default_rng(seed)
    img=np.full((size,size,3),value,np.uint8) if value is not None else rng.integers(60,200,(size,size,3),dtype=np.uint8)
    ok,jpg=cv2.imencode(".png",img)
    return base64.b64encode(jpg.tobytes()).decode()

class FakeEngine:
    def __init__(self):
        self.status=dict(STATUS); self.vector=unit(1); self.bbox=[40,40,120,120]; self.extra_faces=0; self.face=True
    def embed(self, b64):
        return (list(map(float,self.vector)),list(self.bbox)) if self.face else (None,None)

@pytest.fixture
def engine(monkeypatch):
    e=FakeEngine()
    monkeypatch.setattr(main,"_engine_embed",e.embed)
    monkeypatch.setattr(main,"_engine_status",lambda: dict(e.status))
    monkeypatch.setattr(main,"_secondary_faces",lambda gray,bbox: e.extra_faces)
    return e

def session(client, subject_id=None, **kw):
    body={"subject_id":subject_id or uid("subj"),"display_name":"Session Person","consent_obtained":True,"consent_reference":"form-2026-09",**kw}
    r=client.post("/v1/enrollment-sessions",json=body)
    assert r.status_code==200,r.text
    return r.json()

def add(client, sid, img, consent=True):
    return client.post(f"/v1/enrollment-sessions/{sid}/images",json={"image_base64":img,"consent_obtained":consent})

def enrolled_subject(vector):
    sid=uid("subj")
    sql("insert into subjects(subject_id,display_name,embedding,consent_obtained,retention_days) values(%s,'Existing',%s::jsonb,true,30)",
        (sid,json.dumps([float(x) for x in vector])))
    return sid

# ---------------- Mission 26: watchlists ----------------

def watchlist(client, category="staff", **kw):
    wid=uid("wl")
    r=client.post("/v1/watchlists",json={"watchlist_id":wid,"name":"List "+wid,"category":category,**kw})
    assert r.status_code==200,r.text
    return wid

def test_watchlist_crud_and_audit(client):
    wid=watchlist(client,"vip",description="front desk")
    d=client.get(f"/v1/watchlists/{wid}").json()
    assert d["category"]=="vip" and d["member_count"]==0 and d["identity_proof"] is False and d["automatic_actions"] is False
    assert client.post("/v1/watchlists",json={"watchlist_id":wid,"name":"dup","category":"vip"}).status_code==409
    assert client.patch(f"/v1/watchlists/{wid}",json={"category":"contractor","name":" Renamed "}).json()["name"]=="Renamed"
    assert any(w["watchlist_id"]==wid for w in client.get("/v1/watchlists?category=contractor").json())
    assert client.delete(f"/v1/watchlists/{wid}").json()["deleted"] is True
    assert client.get(f"/v1/watchlists/{wid}").status_code==404
    assert [a[0] for a in audit_for(wid)]==["watchlist.created","watchlist.updated","watchlist.deleted"]

def test_watchlist_categories_validated(client):
    for cat in ("staff","visitor","contractor","vip","review-required","denied-access"):
        watchlist(client,cat)
    assert client.post("/v1/watchlists",json={"watchlist_id":uid("wl"),"name":"x","category":"criminal"}).status_code==400
    assert client.post("/v1/watchlists",json={"watchlist_id":uid("wl"),"name":"x","category":"vip","status":"deleted"}).status_code==400
    assert client.post("/v1/watchlists",json={"watchlist_id":"bad id!","name":"x","category":"vip"}).status_code==400
    assert client.post("/v1/watchlists",json={"watchlist_id":uid("wl"),"name":"x","category":"vip","auto_deny":True}).status_code==422

def test_watchlist_membership(client, subject):
    wid=watchlist(client,"denied-access")
    r=client.post(f"/v1/watchlists/{wid}/members",json={"subject_ref":subject,"note":"operator note","added_by_ref":"kc:op-1"})
    assert r.status_code==200 and r.json()["created"] is True and r.json()["identity_proof"] is False
    mid=r.json()["member_id"]
    again=client.post(f"/v1/watchlists/{wid}/members",json={"subject_id":subject})
    assert again.json()["created"] is False and again.json()["member_id"]==mid
    assert client.post(f"/v1/watchlists/{wid}/members",json={"subject_ref":"ghost"}).status_code==400
    assert client.post(f"/v1/watchlists/{wid}/members",json={}).status_code==400
    assert client.get(f"/v1/watchlists/{wid}").json()["member_count"]==1
    assert client.delete(f"/v1/watchlists/{wid}").status_code==409
    mine=client.get(f"/v1/subjects/{subject}/watchlists").json()
    assert [m["category"] for m in mine]==["denied-access"]
    assert client.delete(f"/v1/watchlists/{wid}/members/{mid}").json()["removed"] is True
    assert client.delete(f"/v1/watchlists/{wid}/members/{mid}").status_code==404
    assert [a[0] for a in audit_for(wid)][-2:]==["watchlist.member_added","watchlist.member_removed"]

def test_watchlist_visitor_pass_expiry_and_archive(client):
    pid=uid("vp")
    assert client.post("/v1/visitor-passes",json={"pass_id":pid,"display_name":"Guest","valid_from":"2026-09-24T00:00:00Z","valid_until":"2026-09-25T00:00:00Z"}).status_code==200
    wid=watchlist(client,"visitor")
    m=client.post(f"/v1/watchlists/{wid}/members",json={"visitor_pass_id":pid,"expires_at":"2020-01-01T00:00:00Z"}).json()
    assert m["subject_kind"]=="visitor_pass" and m["expired"] is True
    assert client.get(f"/v1/watchlists/{wid}/members?include_expired=false").json()==[]
    client.patch(f"/v1/watchlists/{wid}",json={"status":"archived"})
    assert client.post(f"/v1/watchlists/{wid}/members",json={"visitor_pass_id":pid}).status_code==409

def test_watchlist_not_used_by_access_decisions(client, subject, zone):
    wid=watchlist(client,"denied-access")
    client.post(f"/v1/watchlists/{wid}/members",json={"subject_ref":subject})
    client.post("/v1/access-policies",json={"policy_id":uid("pol"),"name":"p","subject_id":subject,"zone_id":zone})
    d=client.post("/v1/access/evaluate",json={"subject_ref":subject,"zone_id":zone,"occurred_at":"2026-09-24T12:00:00Z"}).json()
    assert d["decision"]=="allow"

def test_watchlist_privacy_export_and_delete(client, subject):
    wid=watchlist(client,"staff")
    client.post(f"/v1/watchlists/{wid}/members",json={"subject_ref":subject})
    exp=client.get(f"/v1/privacy/subjects/{subject}/export").json()
    assert [m["watchlist_id"] for m in exp["watchlist_memberships"]]==[wid]
    assert exp["embedding_metadata"]["template_included"] is False
    client.delete(f"/v1/privacy/subjects/{subject}")
    assert client.get(f"/v1/watchlists/{wid}/members").json()==[]

def test_watchlist_lan_denied(lan):
    assert lan.get("/v1/watchlists").status_code==403
    assert lan.post("/v1/watchlists",json={"watchlist_id":"x","name":"x","category":"vip"},headers={"X-Role":"admin"}).status_code==403

# ---------------- Mission 27: enrollment sessions + quality ----------------

def test_session_requires_consent(client):
    r=client.post("/v1/enrollment-sessions",json={"subject_id":uid("s"),"display_name":"x","consent_obtained":False,"consent_reference":"f"})
    assert r.status_code==400
    s=session(client)
    assert add(client,s["session_id"],image(),consent=False).status_code==400

def test_session_accepts_good_image_with_quality_metadata(client, engine):
    s=session(client)
    assert s["thresholds"]["liveness"] is False and s["thresholds"]["pose_supported"] is False
    r=add(client,s["session_id"],image(2))
    assert r.status_code==200,r.text
    q=r.json()["quality"]
    assert r.json()["accepted"] is True and q["face_count"]==1 and q["face_min_side_px"]==120
    assert q["sharpness"]>=main.ENROLL_MIN_SHARPNESS and main.ENROLL_MIN_BRIGHTNESS<=q["brightness"]<=main.ENROLL_MAX_BRIGHTNESS
    assert q["liveness_checked"] is False and q["pose"] is None
    body=json.dumps(client.get(f"/v1/enrollment-sessions/{s['session_id']}").json())
    assert '"embedding":' not in body and "image_base64" not in body and "image_sha256" not in body

@pytest.mark.parametrize("setup,reason",[
    (lambda e: setattr(e,"extra_faces",1),"multiple_faces"),
    (lambda e: setattr(e,"bbox",[10,10,30,30]),"face_too_small"),
    (lambda e: setattr(e,"face",False),"no_face_detected"),
])
def test_session_rejects_low_quality(client, engine, setup, reason):
    s=session(client); setup(engine)
    r=add(client,s["session_id"],image(3))
    assert r.status_code==422 and reason in r.json()["detail"]["reasons"]
    detail=client.get(f"/v1/enrollment-sessions/{s['session_id']}").json()
    assert detail["accepted_images"]==0 and detail["images"][0]["status"]=="rejected"
    assert audit_for(s["session_id"])[-1][0]=="enrollment_image.rejected"

def test_session_rejects_blur_dark_bright(client, engine):
    s=session(client)
    dark=add(client,s["session_id"],image(value=10)).json()["detail"]["reasons"]
    bright=add(client,s["session_id"],image(value=250)).json()["detail"]["reasons"]
    assert "too_blurry" in dark and "too_dark" in dark and "too_bright" in bright

def test_session_rejects_duplicate_and_invalid_images(client, engine):
    s=session(client); img=image(4)
    assert add(client,s["session_id"],img).status_code==200
    r=add(client,s["session_id"],img)
    assert r.status_code==422 and r.json()["detail"]["reasons"]==["duplicate_image"]
    assert add(client,s["session_id"],"not base64!!").status_code==400
    assert add(client,s["session_id"],base64.b64encode(b"not an image").decode()).status_code==400

def test_session_rejects_model_change(client, engine):
    s=session(client)
    assert add(client,s["session_id"],image(5)).status_code==200
    engine.status["recognizer"]="sface-2099"
    r=add(client,s["session_id"],image(6))
    assert r.status_code==422 and r.json()["detail"]["reasons"]==["model_version_changed"]

def test_finalize_aggregates_deterministically(client, engine):
    subject_id=uid("subj"); s=session(client,subject_id)
    a,b=unit(11),unit(12)
    engine.vector=a*3; assert add(client,s["session_id"],image(7)).status_code==200
    engine.vector=b; assert add(client,s["session_id"],image(8)).status_code==200
    r=client.post(f"/v1/enrollment-sessions/{s['session_id']}/finalize")
    assert r.status_code==200,r.text
    out=r.json()
    assert out["image_count"]==2 and out["aggregation_method"]=="l2-mean-l2/v1" and out["liveness_checked"] is False
    m=(a+b)/2; expected=[round(float(x),8) for x in m/np.linalg.norm(m)]
    row=sql("select embedding,embedding_method,embedding_image_count,embedding_version,model_key,model_digest,enrollment_source from subjects where subject_id=%s",(subject_id,))[0]
    assert row[0]==expected and row[1]=="l2-mean-l2/v1" and row[2]==2
    assert row[3]=="sface-2021dec:cosine:l2norm" and row[4].startswith("opencv-sface:sface-2021dec@") and row[5].startswith("sha256:")
    assert row[6]=="enrollment-session"
    # per-image templates purged after finalize; session closed
    assert sql("select count(*) from enrollment_session_images where session_id=%s and embedding is not null",(s["session_id"],))[0][0]==0
    assert client.get(f"/v1/enrollment-sessions/{s['session_id']}").json()["status"]=="finalized"
    assert add(client,s["session_id"],image(9)).status_code==409
    assert audit_for(s["session_id"])[-1][0]=="enrollment_session.finalized"

def test_finalize_requires_accepted_images_and_single_open_session(client, engine):
    subject_id=uid("subj"); s=session(client,subject_id)
    assert client.post(f"/v1/enrollment-sessions/{s['session_id']}/finalize").status_code==409
    assert client.post("/v1/enrollment-sessions",json={"subject_id":subject_id,"display_name":"x","consent_obtained":True,"consent_reference":"f"}).status_code==409
    assert client.post(f"/v1/enrollment-sessions/{s['session_id']}/cancel").json()["status"]=="cancelled"
    assert client.post(f"/v1/enrollment-sessions/{s['session_id']}/cancel").status_code==409
    session(client,subject_id)

def test_session_expiry_purges_templates(client, engine):
    s=session(client); add(client,s["session_id"],image(10))
    sql("update enrollment_sessions set expires_at=now()-interval '1 minute' where session_id=%s",(s["session_id"],))
    assert add(client,s["session_id"],image(11)).status_code==409
    main._cleanup_last=0; main._cleanup_expired()
    assert sql("select status from enrollment_sessions where session_id=%s",(s["session_id"],))[0][0]=="expired"
    assert sql("select count(*) from enrollment_session_images where session_id=%s and embedding is not null",(s["session_id"],))[0][0]==0

def test_enrollment_lan_denied(lan):
    assert lan.get("/v1/enrollment-sessions").status_code==403
    assert lan.post("/v1/enrollment-sessions",json={}).status_code==403

# ---------------- Mission 28: duplicate candidates ----------------

def test_duplicate_candidates_block_finalize_until_resolved(client, engine):
    existing=enrolled_subject(unit(21))
    engine.vector=unit(21)
    s=session(client); add(client,s["session_id"],image(12))
    chk=client.post(f"/v1/enrollment-sessions/{s['session_id']}/duplicate-check").json()
    assert chk["threshold"]==main.DUPLICATE_THRESHOLD!=chk["recognition_threshold"]
    assert chk["identity_asserted"] is False and chk["auto_merge"] is False
    cand=[x for x in chk["candidates"] if x["candidate_subject_ref"]==existing][0]
    assert cand["status"]=="open" and cand["score"]>0.99 and cand["version_unverified"] is True
    assert set(cand)>={"candidate_subject_ref","score","subject_ref"} and "display_name" not in cand and "embedding" not in cand
    r=client.post(f"/v1/enrollment-sessions/{s['session_id']}/finalize")
    assert r.status_code==409 and r.json()["detail"]["candidates"][0]["candidate_id"]==cand["candidate_id"]
    assert sql("select count(*) from subjects where subject_id=%s",(s["subject_id"],))[0][0]==0
    res=client.post(f"/v1/duplicate-candidates/{cand['candidate_id']}/resolve",json={"resolution":"not_duplicate","resolver_ref":"kc:op-2","note":"twins"})
    assert res.json()["status"]=="resolved" and res.json()["resolution"]=="not_duplicate"
    assert client.post(f"/v1/duplicate-candidates/{cand['candidate_id']}/resolve",json={"resolution":"dismissed"}).status_code==409
    assert client.post(f"/v1/enrollment-sessions/{s['session_id']}/finalize").status_code==200
    # never merged: the existing subject is untouched and still separate
    assert sql("select count(*) from subjects where subject_id in (%s,%s)",(existing,s["subject_id"]))[0][0]==2
    assert [a[0] for a in audit_for(cand["candidate_id"])]==["duplicate_candidate.resolved"]
    assert "duplicate_candidate.detected" in [a[0] for a in audit_for(s["session_id"])]

def test_duplicate_confirmed_blocks_finalize(client, engine):
    enrolled_subject(unit(31)); engine.vector=unit(31)
    s=session(client); add(client,s["session_id"],image(13))
    r=client.post(f"/v1/enrollment-sessions/{s['session_id']}/finalize")
    cid=r.json()["detail"]["candidates"][0]["candidate_id"]
    client.post(f"/v1/duplicate-candidates/{cid}/resolve",json={"resolution":"duplicate_confirmed"})
    assert client.post(f"/v1/enrollment-sessions/{s['session_id']}/finalize").status_code==409
    client.post(f"/v1/enrollment-sessions/{s['session_id']}/cancel")
    assert client.get(f"/v1/duplicate-candidates?status=all&session_id={s['session_id']}").json()[0]["resolution"]=="duplicate_confirmed"

def test_duplicate_threshold_distinct_and_incompatible_versions_skipped(client, engine):
    base=unit(41); other=unit(42)
    # cosine between 0.30 and 0.363: a duplicate candidate but NOT a recognition match
    v=0.33*base+np.sqrt(1-0.33**2)*(other-(other@base)*base)/np.linalg.norm(other-(other@base)*base)
    near=enrolled_subject(v)
    skipped=enrolled_subject(base)
    sql("update subjects set embedding_version='other-model:cosine:l2norm' where subject_id=%s",(skipped,))
    engine.vector=base
    s=session(client); add(client,s["session_id"],image(14))
    chk=client.post(f"/v1/enrollment-sessions/{s['session_id']}/duplicate-check").json()
    refs={c["candidate_subject_ref"]:c["score"] for c in chk["candidates"]}
    assert near in refs and main.DUPLICATE_THRESHOLD<=refs[near]<main.MATCH_THRESHOLD
    assert skipped not in refs and chk["skipped_incompatible_subjects"]>=1

def test_reenrollment_excludes_self_and_archives_old_embedding(client, engine):
    subject_id=enrolled_subject(unit(51))
    engine.vector=unit(51)
    s=session(client,subject_id)
    assert s["re_enrollment"] is True
    add(client,s["session_id"],image(15))
    out=client.post(f"/v1/enrollment-sessions/{s['session_id']}/finalize").json()
    assert out["archived_history_id"]
    assert sql("select count(*) from subject_embedding_history where subject_id=%s",(subject_id,))[0][0]==1

def test_duplicate_resolve_validation_and_lan(client, lan):
    assert client.post("/v1/duplicate-candidates/nope/resolve",json={"resolution":"merge"}).status_code==400
    assert client.post("/v1/duplicate-candidates/nope/resolve",json={"resolution":"dismissed"}).status_code==404
    assert client.post("/v1/duplicate-candidates/nope/resolve",json={"resolution":"dismissed","merge_into":"x"}).status_code==422
    assert lan.get("/v1/duplicate-candidates").status_code==403

# ---------------- Mission 29: model registry + re-embedding ----------------

def test_model_registry_read_only(client, engine):
    s=session(client); add(client,s["session_id"],image(16))
    cur=client.get("/v1/models/current").json()
    assert cur["registered"] is True and cur["digest_kind"]=="descriptor-sha256" and cur["embedding_version"]=="sface-2021dec:cosine:l2norm"
    assert any(m["model_key"]==cur["model_key"] and m["dimension"]==128 for m in client.get("/v1/models").json())
    assert client.post("/v1/models",json={}).status_code==405
    assert client.get("/v1/models/current").json()["model_digest"]==cur["model_digest"]

def test_migration_status_and_engine_unavailable(client, engine, monkeypatch):
    st=client.get("/v1/models/migration-status").json()
    assert st["automatic_migration"] is False and st["current_model"]["embedding_version"]=="sface-2021dec:cosine:l2norm"
    assert st["subjects_needing_migration"]==st["subjects_total"]-st["subjects_on_current_version"]
    def down(): raise main.HTTPException(503,"recognition engine model status unavailable")
    monkeypatch.setattr(main,"_engine_status",down)
    st=client.get("/v1/models/migration-status").json()
    assert st["current_model"] is None and st["engine_error"] and st["subjects_needing_migration"] is None

def test_reembedding_queue_is_non_destructive(client, engine):
    old=unit(61); subject_id=enrolled_subject(old)
    r=client.post("/v1/reembedding-jobs",json={"subject_ids":[subject_id,subject_id],"reason":"model upgrade"}).json()
    assert r["destructive"] is False and len(r["created"])==1 and r["created"][0]["status"]=="queued"
    job=r["created"][0]["job_id"]
    again=client.post("/v1/reembedding-jobs",json={"subject_ids":[subject_id],"reason":"again"}).json()
    assert again["created"]==[] and again["existing"][0]["job_id"]==job
    stored=sql("select embedding,embedding_version from subjects where subject_id=%s",(subject_id,))[0]
    assert np.allclose(stored[0],old) and stored[1] is None
    assert client.post("/v1/reembedding-jobs",json={"subject_ids":["ghost-subject"],"reason":"x"}).status_code==400

def test_reembedding_complete_preserves_old_embedding(client, engine):
    old=unit(71); subject_id=enrolled_subject(old)
    job=client.post("/v1/reembedding-jobs",json={"subject_ids":[subject_id],"reason":"upgrade"}).json()["created"][0]["job_id"]
    # quality failure: job stays queued, embedding untouched
    engine.extra_faces=1
    r=client.post(f"/v1/reembedding-jobs/{job}/complete",json={"images_base64":[image(17)],"consent_obtained":True})
    assert r.status_code==422
    assert sql("select status from reembedding_jobs where job_id=%s",(job,))[0][0]=="queued"
    assert np.allclose(sql("select embedding from subjects where subject_id=%s",(subject_id,))[0][0],old)
    engine.extra_faces=0; engine.vector=unit(72)
    r=client.post(f"/v1/reembedding-jobs/{job}/complete",json={"images_base64":[image(18)],"consent_obtained":True,"consent_reference":"form-2"})
    assert r.status_code==200 and r.json()["status"]=="succeeded" and r.json()["history_id"]
    hist=sql("select embedding,reason from subject_embedding_history where history_id=%s",(r.json()["history_id"],))[0]
    assert np.allclose(hist[0],old) and hist[1]=="reembedding_job:"+job
    row=sql("select embedding_version,embedding_method from subjects where subject_id=%s",(subject_id,))[0]
    assert row==("sface-2021dec:cosine:l2norm","l2-mean-l2/v1")
    assert client.post(f"/v1/reembedding-jobs/{job}/complete",json={"images_base64":[image(18)],"consent_obtained":True}).status_code==409
    assert [a[0] for a in audit_for(job)]==["reembedding_job.queued","reembedding_job.succeeded"]

def test_reembedding_version_mismatch_fails_without_change(client, engine):
    old=unit(81); subject_id=enrolled_subject(old)
    job=client.post("/v1/reembedding-jobs",json={"subject_ids":[subject_id],"reason":"upgrade"}).json()["created"][0]["job_id"]
    engine.status["recognizer"]="sface-2030"
    r=client.post(f"/v1/reembedding-jobs/{job}/complete",json={"images_base64":[image(19)],"consent_obtained":True})
    assert r.status_code==409 and r.json()["detail"]["error"]=="target_embedding_version_mismatch"
    assert sql("select status from reembedding_jobs where job_id=%s",(job,))[0][0]=="failed"
    assert np.allclose(sql("select embedding from subjects where subject_id=%s",(subject_id,))[0][0],old)

def test_reembedding_cancel_and_consent(client, engine):
    subject_id=enrolled_subject(unit(91))
    job=client.post("/v1/reembedding-jobs",json={"subject_ids":[subject_id],"reason":"x"}).json()["created"][0]["job_id"]
    assert client.post(f"/v1/reembedding-jobs/{job}/complete",json={"images_base64":[image(20)],"consent_obtained":False}).status_code==400
    assert client.post(f"/v1/reembedding-jobs/{job}/cancel").json()["status"]=="cancelled"
    assert client.post(f"/v1/reembedding-jobs/{job}/cancel").status_code==409
    assert client.post("/v1/reembedding-jobs/nope/cancel").status_code==404

def test_embedding_history_retention_and_privacy_delete(client, engine):
    subject_id=enrolled_subject(unit(95))
    s=session(client,subject_id); engine.vector=unit(95); add(client,s["session_id"],image(21))
    client.post(f"/v1/enrollment-sessions/{s['session_id']}/finalize")
    sql("update subject_embedding_history set archived_at=now()-interval '400 days' where subject_id=%s",(subject_id,))
    main._cleanup_last=0; main._cleanup_expired()
    assert sql("select count(*) from subject_embedding_history where subject_id=%s",(subject_id,))[0][0]==0
    exp=client.get(f"/v1/privacy/subjects/{subject_id}/export").json()
    assert exp["embedding_metadata"]["embedding_method"]=="l2-mean-l2/v1" and "embedding" not in exp["subject"]
    assert len(exp["enrollment_sessions"])==1
    client.delete(f"/v1/privacy/subjects/{subject_id}")
    assert sql("select count(*) from enrollment_sessions where subject_id=%s",(subject_id,))[0][0]==0

def test_model_registry_lan_denied(lan):
    for path in ("/v1/models","/v1/models/current","/v1/models/migration-status","/v1/reembedding-jobs"):
        assert lan.get(path).status_code==403

# ---------------- Mission 30: audit export ----------------

_NOW=datetime.datetime.now(datetime.timezone.utc)
RANGE="since={}&until={}".format(*((_NOW+datetime.timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ") for d in (-1,1)))

def seed_audit(action, details, target=None):
    target=target or uid("t")
    main._audit(action,"test_target",target,details)
    return target

def test_audit_export_redacts_secrets_and_biometrics(client):
    t=seed_audit("test.redaction",{"embedding":[0.1]*128,"image_base64":"x","password":"hunter2","api_key":"k","id_hash":"ab"*32,
                                    "nested":{"token":"t","vector":[1]*64,"password_env":"CAM_PW"},"auth":"Bearer abcdefghijklmnop",
                                    "raw":"A"*600,"safe":"ok"})
    out=client.get(f"/v1/audit/export?{RANGE}&action=test.redaction").json()
    rec=[r for r in out["records"] if r["target_id"]==t][0]
    body=json.dumps(rec)
    assert "hunter2" not in body and "0.1, 0.1" not in body and "abcdefghijklmnop" not in body and "A"*600 not in body
    d=rec["details"]
    assert d["embedding"]=="[REDACTED:biometric]" and d["password"]=="[REDACTED:secret]" and d["id_hash"]=="[REDACTED:identifier]"
    assert d["nested"]["token"]=="[REDACTED:secret]" and d["nested"]["vector"]=="[REDACTED:biometric]" and d["nested"]["password_env"]=="CAM_PW"
    assert d["safe"]=="ok"
    red=out["manifest"]["redaction"]
    assert red["biometric_templates_included"] is False and red["secret_values"]>=4 and red["biometric_values"]>=4

def test_audit_export_integrity_and_pagination(client):
    action="test.page."+uid("x")
    targets=[seed_audit(action,{"i":i}) for i in range(5)]
    first=client.get(f"/v1/audit/export?{RANGE}&action={action}&limit=2").json()
    m=first["manifest"]
    assert m["record_count"]==2 and m["has_more"] and m["page"]==1 and m["integrity"]["chain_seed"]=="0"*64
    chain="0"*64; seen=[]; cursor=None; page=0
    while True:
        url=f"/v1/audit/export?{RANGE}&action={action}&limit=2"+(f"&cursor={cursor}" if cursor else "")
        out=client.get(url).json(); page+=1
        assert out["manifest"]["page"]==page and out["manifest"]["integrity"]["chain_seed"]==chain
        for r in out["records"]:
            rec={k:v for k,v in r.items() if k!="record_sha256"}
            d=hashlib.sha256(json.dumps(rec,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
            assert d==r["record_sha256"]
            chain=hashlib.sha256((chain+d).encode()).hexdigest(); seen.append(r["target_id"])
        assert out["manifest"]["integrity"]["chain_head"]==chain
        cursor=out["manifest"]["next_cursor"]
        if not cursor: break
    assert seen==targets and page==3
    # a cursor cannot be reused with different filters
    assert client.get(f"/v1/audit/export?{RANGE}&action={action}&limit=3&cursor={m['next_cursor']}").status_code==400
    assert client.get(f"/v1/audit/export?{RANGE}&cursor=garbage").status_code==400

def test_audit_export_filters_and_bounds(client):
    prefix="test.pfx"+uid("x").replace("-","")
    t1=seed_audit(prefix+".a",{}); t2=seed_audit(prefix+".b",{})
    main._audit(prefix+".c","test_target",uid("t"),{},actor="system")
    got=[r["target_id"] for r in client.get(f"/v1/audit/export?{RANGE}&action={prefix}.*&actor=local-admin").json()["records"]]
    assert got==[t1,t2]
    assert client.get(f"/v1/audit/export?{RANGE}&action={prefix}.*&target_type=nothing").json()["records"]==[]
    assert client.get("/v1/audit/export").status_code==422
    assert client.get("/v1/audit/export?since=2026-01-01T00:00:00Z&until=2025-01-01T00:00:00Z").status_code==400
    assert client.get("/v1/audit/export?since=2020-01-01T00:00:00Z&until=2026-01-01T00:00:00Z").status_code==400
    assert client.get("/v1/audit/export?since=2026-01-01T00:00:00&until=2026-02-01T00:00:00Z").status_code==400

def test_audit_export_is_audited_and_signed(client, monkeypatch):
    monkeypatch.setattr(main,"AUDIT_EXPORT_HMAC_KEY","test-signing-key")
    out=client.get(f"/v1/audit/export?{RANGE}&limit=1").json()
    m=out["manifest"]; sig=m.pop("signature")
    assert sig["algorithm"]=="hmac-sha256" and "test-signing-key" not in json.dumps(out)
    expected=hmac.new(b"test-signing-key",json.dumps(m,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(),hashlib.sha256).hexdigest()
    assert sig["value"]==expected
    assert audit_for(m["export_id"])[0][0]=="audit.exported"

def test_audit_retention_readback(client):
    r=client.get("/v1/audit/retention").json()
    assert r["enforced"] is False and r["record_count"]>0 and r["resource_type"]=="audit"
    client.post("/v1/retention-policies",json={"policy_id":"audit-retention-test","resource_type":"audit","days":400})
    r=client.get("/v1/audit/retention").json()
    assert r["policy"]["days"]==400 and r["records_older_than_policy"]==0
    assert client.get(f"/v1/audit/export?{RANGE}&limit=1").json()["manifest"]["retention"]["policy"]["days"]==400

def test_audit_export_lan_denied(lan):
    assert lan.get(f"/v1/audit/export?{RANGE}").status_code==403
    assert lan.get("/v1/audit/retention").status_code==403

# ---------------- cross-cutting ----------------

def test_capabilities_and_openapi_26_30(client):
    cap=client.get("/v1/capabilities").json()
    assert cap["watchlists"]["identity_proof"] is False and cap["watchlists"]["automatic_actions"] is False
    assert cap["enrollment_sessions"]["liveness"] is False and cap["liveness"] is False
    assert cap["duplicate_candidates"]["auto_merge"] is False and cap["duplicate_candidates"]["threshold"]!=cap["match_threshold"]
    assert cap["model_registry"]["automatic_migration"] is False
    assert cap["audit_export"]["redaction_policy"]=="faceid-audit-redaction/v1"
    spec=client.get("/openapi.json").json()
    tags={t for p in spec["paths"].values() for op in p.values() for t in op.get("tags",[])}
    assert {"watchlists","enrollment-sessions","duplicate-candidates","model-registry","audit-compliance"}<=tags

def test_manual_enroll_stamps_model_metadata(client, engine, monkeypatch):
    class R:
        status_code=200; is_success=True
        def json(self): return {"embedding":[float(x) for x in unit(99)],"bbox":[0,0,100,100]}
    monkeypatch.setattr(main.httpx,"post",lambda *a,**k: R())
    sid=uid("subj")
    assert client.post("/v1/faces/enroll",json={"subject_id":sid,"display_name":"M","image_base64":"eA==","consent_obtained":True}).status_code==200
    assert client.post("/v1/faces/enroll",json={"subject_id":sid,"display_name":"M","image_base64":"eA==","consent_obtained":True}).status_code==200
    row=sql("select embedding_version,embedding_method,embedding_dim from subjects where subject_id=%s",(sid,))[0]
    assert row==("sface-2021dec:cosine:l2norm","single-image",128)
    assert sql("select count(*) from subject_embedding_history where subject_id=%s",(sid,))[0][0]==1

def test_haar_secondary_face_counter_loads():
    gray=cv2.cvtColor(cv2.imdecode(np.frombuffer(base64.b64decode(image(22)),np.uint8),cv2.IMREAD_COLOR),cv2.COLOR_BGR2GRAY)
    assert main._secondary_faces(gray,(40,40,120,120))==0

def _engine_up():
    try: return main.httpx.get(main.ENGINE+"/readyz",timeout=2).is_success
    except Exception: return False

@pytest.mark.skipif(not _engine_up(),reason="recognition engine not reachable")
def test_real_engine_descriptor_and_no_face(client):
    cur=client.get("/v1/models/current").json()
    assert cur["model_id"]=="opencv-sface/sface-2021dec" and cur["model_digest"].startswith("sha256:")
    s=session(client)
    r=add(client,s["session_id"],image(23))
    assert r.status_code==422 and r.json()["detail"]["reasons"]==["no_face_detected"]
    client.post(f"/v1/enrollment-sessions/{s['session_id']}/cancel")
