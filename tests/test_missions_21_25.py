import json
from conftest import uid, sql, make_event, audit_for

T_IN="2026-09-24T12:00:00+00:00"

# ---------------- Mission 21: access decisions ----------------

def policy(client, zone, subject=None, allowed=True, schedule=None):
    pid=uid("pol")
    r=client.post("/v1/access-policies",json={"policy_id":pid,"name":pid,"subject_id":subject,"zone_id":zone,"allowed":allowed,"schedule":schedule or {}})
    assert r.status_code==200,r.text
    return pid

def evaluate(client, **body):
    return client.post("/v1/access/evaluate",json=body)

def test_access_allow_is_decision_only_and_audited(client, subject, zone):
    pid=policy(client,zone,subject)
    r=evaluate(client,subject_ref=subject,zone_id=zone,occurred_at=T_IN)
    assert r.status_code==200
    d=r.json()
    assert d["decision"]=="allow" and d["allowed"] is True
    assert d["reason_codes"]==["policy_allowed"] and d["matched_policy_ids"]==[pid]
    assert d["decision_only"] is True and d["actuation"]=="none"
    rows=audit_for(d["decision_id"])
    assert rows and rows[0][0]=="access.evaluated"
    details=json.dumps(rows[0][1])
    assert "embedding" not in details and "image" not in details

def test_access_subject_id_alias_and_mismatch(client, subject, zone):
    policy(client,zone,subject)
    assert evaluate(client,subject_id=subject,zone_id=zone,occurred_at=T_IN).json()["allowed"] is True
    assert evaluate(client,subject_id=subject,subject_ref="other",zone_id=zone,occurred_at=T_IN).status_code==400

def test_access_deny_overrides_allow(client, subject, zone):
    policy(client,zone,None,allowed=True)
    deny=policy(client,zone,subject,allowed=False)
    d=evaluate(client,subject_ref=subject,zone_id=zone,occurred_at=T_IN).json()
    assert d["decision"]=="deny" and d["reason_codes"]==["policy_denied"] and d["matched_policy_ids"]==[deny]

def test_access_schedule_window_and_timezone(client, subject, zone):
    policy(client,zone,subject,schedule={"days":["thu"],"start":"08:00","end":"17:00","timezone":"America/Santo_Domingo"})
    # 2026-09-24 is a Thursday; 12:00Z = 08:00 AST (inside), 22:00Z = 18:00 AST (outside)
    assert evaluate(client,subject_ref=subject,zone_id=zone,occurred_at="2026-09-24T12:00:00Z").json()["allowed"] is True
    out=evaluate(client,subject_ref=subject,zone_id=zone,occurred_at="2026-09-24T22:00:00Z").json()
    assert out["allowed"] is False and out["reason_codes"]==["no_matching_policy"]
    assert evaluate(client,subject_ref=subject,zone_id=zone,occurred_at="2026-09-25T12:00:00Z").json()["allowed"] is False

def test_access_fail_closed_on_invalid_refs(client, subject, zone):
    policy(client,zone,subject)
    assert evaluate(client,subject_ref="ghost",zone_id=zone,occurred_at=T_IN).json()["reason_codes"]==["subject_not_found"]
    assert evaluate(client,subject_ref=subject,zone_id="nozone",occurred_at=T_IN).json()["reason_codes"]==["zone_not_found"]
    client.post("/v1/zones",json={"zone_id":zone,"name":"off","enabled":False})
    d=evaluate(client,subject_ref=subject,zone_id=zone,occurred_at=T_IN).json()
    assert d["allowed"] is False and d["reason_codes"]==["zone_disabled"]

def test_access_no_policy_denies(client, subject, zone):
    d=evaluate(client,subject_ref=subject,zone_id=zone,occurred_at=T_IN).json()
    assert d["decision"]=="deny" and d["reason_codes"]==["no_matching_policy"]

def test_access_invalid_stored_policy_fails_closed(client, subject, zone):
    policy(client,zone,subject)
    bad=uid("pol")
    sql("""insert into access_policies(policy_id,name,subject_id,zone_id,allowed,schedule) values(%s,'bad',%s,%s,true,'{"hours":"always"}'::jsonb)""",(bad,subject,zone))
    d=evaluate(client,subject_ref=subject,zone_id=zone,occurred_at=T_IN).json()
    assert d["allowed"] is False and d["reason_codes"]==["policy_invalid"] and d["matched_policy_ids"]==[bad]

def test_policy_save_rejects_invalid_schedule(client, zone):
    r=client.post("/v1/access-policies",json={"policy_id":uid("pol"),"name":"x","zone_id":zone,"schedule":{"start":"25:00","end":"26:00"}})
    assert r.status_code==400
    r=client.post("/v1/access-policies",json={"policy_id":uid("pol"),"name":"x","zone_id":zone,"schedule":{"unlock":True}})
    assert r.status_code==400

def test_access_visitor_pass_windows(client, zone):
    policy(client,zone,None)
    def vp(start,end,status="active"):
        pid=uid("vp")
        assert client.post("/v1/visitor-passes",json={"pass_id":pid,"display_name":"Guest","valid_from":start,"valid_until":end,"status":status}).status_code==200
        return pid
    ok=vp("2026-09-24T00:00:00Z","2026-09-25T00:00:00Z")
    d=evaluate(client,visitor_pass_id=ok,zone_id=zone,occurred_at=T_IN).json()
    assert d["allowed"] is True and d["reason_codes"]==["policy_allowed","visitor_pass_valid"] and d["matched_visitor_pass_id"]==ok
    exp=vp("2026-09-01T00:00:00Z","2026-09-02T00:00:00Z")
    assert evaluate(client,visitor_pass_id=exp,zone_id=zone,occurred_at=T_IN).json()["reason_codes"]==["visitor_pass_expired"]
    fut=vp("2026-10-01T00:00:00Z","2026-10-02T00:00:00Z")
    assert evaluate(client,visitor_pass_id=fut,zone_id=zone,occurred_at=T_IN).json()["reason_codes"]==["visitor_pass_not_yet_valid"]
    rev=vp("2026-09-24T00:00:00Z","2026-09-25T00:00:00Z","revoked")
    assert evaluate(client,visitor_pass_id=rev,zone_id=zone,occurred_at=T_IN).json()["reason_codes"]==["visitor_pass_inactive"]
    assert evaluate(client,visitor_pass_id="nope",zone_id=zone,occurred_at=T_IN).json()["reason_codes"]==["visitor_pass_not_found"]

def test_access_malformed_requests_rejected(client, subject, zone):
    assert evaluate(client,subject_ref=subject,zone_id=zone,occurred_at="2026-09-24T12:00:00").status_code==400
    assert evaluate(client,subject_ref=subject,zone_id=zone,occurred_at="yesterday").status_code==400
    assert evaluate(client,zone_id=zone,occurred_at=T_IN).status_code==400
    assert evaluate(client,subject_ref=subject,zone_id=zone,occurred_at=T_IN,unlock=True).status_code==422
    assert evaluate(client,subject_ref="bad ref!",zone_id=zone,occurred_at=T_IN).status_code==400

def test_access_lan_denied(lan):
    r=lan.post("/v1/access/evaluate",json={"subject_ref":"x","zone_id":"z","occurred_at":T_IN},headers={"X-Role":"admin"})
    assert r.status_code==403

# ---------------- Mission 24: camera-zone mapping ----------------

def test_camera_zone_crud_idempotent_and_audited(client, camera, zone):
    r=client.post("/v1/camera-zones",json={"camera_id":camera,"zone_id":zone,"priority":10})
    assert r.status_code==200 and r.json()["created"] is True
    mid=r.json()["mapping_id"]
    r2=client.post("/v1/camera-zones",json={"camera_id":camera,"zone_id":zone,"priority":20})
    assert r2.json()["created"] is False and r2.json()["mapping_id"]==mid and r2.json()["priority"]==20
    assert [m["mapping_id"] for m in client.get(f"/v1/camera-zones?camera_id={camera}").json()]==[mid]
    p=client.patch(f"/v1/camera-zones/{mid}",json={"enabled":False})
    assert p.status_code==200 and p.json()["enabled"] is False
    assert client.patch(f"/v1/camera-zones/{mid}",json={"priority":None}).status_code==400
    assert client.delete(f"/v1/camera-zones/{mid}").json()["deleted"] is True
    assert client.delete(f"/v1/camera-zones/{mid}").status_code==404
    actions=[a for a,_ in audit_for(mid)]
    assert actions==["camera_zone.created","camera_zone.updated","camera_zone.updated","camera_zone.deleted"]

def test_camera_zone_invalid_refs_and_no_credentials(client, camera, zone):
    assert client.post("/v1/camera-zones",json={"camera_id":"nocam","zone_id":zone}).status_code==400
    assert client.post("/v1/camera-zones",json={"camera_id":camera,"zone_id":"nozone"}).status_code==400
    assert client.post("/v1/camera-zones",json={"camera_id":camera,"zone_id":zone,"password":"x"}).status_code==422
    assert client.post("/v1/camera-zones",json={"camera_id":camera,"zone_id":zone,"priority":5000}).status_code==422
    assert client.patch("/v1/camera-zones/missing",json={"priority":1}).status_code==404

def test_camera_delete_removes_mappings(client, camera, zone):
    client.post("/v1/camera-zones",json={"camera_id":camera,"zone_id":zone})
    client.delete(f"/v1/cameras/{camera}")
    assert client.get(f"/v1/camera-zones?camera_id={camera}").json()==[]

def test_camera_zone_lan_denied(lan):
    assert lan.get("/v1/camera-zones").status_code==403
    assert lan.post("/v1/camera-zones",json={"camera_id":"a","zone_id":"b"}).status_code==403

# ---------------- Mission 22: presence ----------------

def pev(client, **body):
    return client.post("/v1/presence/events",json=body)

def test_presence_enter_exit_idempotent(client, subject, zone):
    ref=uid("obs")
    r=pev(client,event_ref=ref,direction="enter",subject_ref=subject,zone_id=zone,occurred_at=T_IN)
    assert r.status_code==200 and r.json()["outcome"]=="session_opened"
    sid=r.json()["session_id"]
    replay=pev(client,event_ref=ref,direction="enter",subject_ref=subject,zone_id=zone,occurred_at=T_IN).json()
    assert replay["idempotent_replay"] is True and replay["session_id"]==sid
    assert pev(client,event_ref=ref,direction="exit",subject_ref=subject,zone_id=zone,occurred_at=T_IN).status_code==409
    again=pev(client,event_ref=uid("obs"),direction="enter",subject_ref=subject,zone_id=zone,occurred_at="2026-09-24T12:05:00Z").json()
    assert again["outcome"]=="already_present" and again["session_id"]==sid
    cur=client.get(f"/v1/presence/current?zone_id={zone}").json()
    assert cur["total"]==1 and cur["occupancy"][0]["count"]==1
    assert sql("select count(*) from presence_sessions where subject_ref=%s and exited_at is null",(subject,))[0][0]==1
    early=pev(client,event_ref=uid("obs"),direction="exit",subject_ref=subject,zone_id=zone,occurred_at="2026-09-24T11:00:00Z").json()
    assert early["outcome"]=="exit_before_entry_ignored"
    out=pev(client,event_ref=uid("obs"),direction="exit",subject_ref=subject,zone_id=zone,occurred_at="2026-09-24T13:00:00Z").json()
    assert out["outcome"]=="session_closed" and out["session_id"]==sid
    assert client.get(f"/v1/presence/current?zone_id={zone}").json()["total"]==0
    none=pev(client,event_ref=uid("obs"),direction="exit",subject_ref=subject,zone_id=zone,occurred_at="2026-09-24T14:00:00Z").json()
    assert none["outcome"]=="no_open_session"
    hist=client.get(f"/v1/presence/history?subject_ref={subject}").json()
    assert len(hist)==1 and hist[0]["status"]=="closed" and hist[0]["exit_event_ref"]
    assert client.get(f"/v1/presence/history?subject_ref={subject}&status=open").json()==[]
    assert audit_for(ref)[0][0]=="presence.observed"

def test_presence_camera_mapping_resolution(client, subject, camera):
    z1=uid("zone"); z2=uid("zone")
    for z in (z1,z2): client.post("/v1/zones",json={"zone_id":z,"name":z})
    client.post("/v1/camera-zones",json={"camera_id":camera,"zone_id":z1,"priority":50})
    client.post("/v1/camera-zones",json={"camera_id":camera,"zone_id":z2,"priority":5})
    r=pev(client,event_ref=uid("obs"),direction="enter",subject_ref=subject,camera_id=camera)
    assert r.status_code==200 and r.json()["zone_id"]==z2
    other=uid("zone"); client.post("/v1/zones",json={"zone_id":other,"name":other})
    assert pev(client,event_ref=uid("obs"),direction="enter",subject_ref=subject,camera_id=camera,zone_id=other).status_code==400

def test_presence_event_attribution_and_visitor(client, subject, zone):
    eid=make_event("recognized_face",subject_id=subject)
    r=pev(client,event_ref=uid("obs"),direction="enter",event_id=eid,zone_id=zone)
    assert r.status_code==200 and r.json()["subject_ref"]==subject
    vp=uid("vp")
    client.post("/v1/visitor-passes",json={"pass_id":vp,"display_name":"Guest","valid_from":"2026-09-24T00:00:00Z","valid_until":"2026-09-25T00:00:00Z"})
    v=pev(client,event_ref=uid("obs"),direction="enter",visitor_pass_id=vp,zone_id=zone).json()
    assert v["subject_kind"]=="visitor_pass" and v["outcome"]=="session_opened"

def test_presence_invalid_refs(client, subject, zone, camera):
    base=dict(direction="enter",subject_ref=subject,zone_id=zone)
    assert pev(client,event_ref=uid("o"),**{**base,"subject_ref":"ghost"}).status_code==400
    assert pev(client,event_ref=uid("o"),**{**base,"zone_id":"nozone"}).status_code==400
    assert pev(client,event_ref=uid("o"),**{**base,"direction":"sideways"}).status_code==400
    assert pev(client,event_ref=uid("o"),**base,event_id="noevent").status_code==400
    assert pev(client,event_ref=uid("o"),**base,camera_id=camera).status_code==400  # camera not mapped to zone
    assert pev(client,event_ref=uid("o"),direction="enter",subject_ref=subject).status_code==400
    assert pev(client,event_ref=uid("o"),direction="enter",zone_id=zone).status_code==400
    assert pev(client,event_ref=uid("o"),**base,visitor_pass_id="vp-x").status_code==400
    assert pev(client,event_ref=uid("o"),**base,occurred_at="2026-09-24T12:00:00").status_code==400
    assert pev(client,event_ref="bad ref",**base).status_code==400
    assert pev(client,event_ref=uid("o"),**base,embedding=[0.1]).status_code==422

def test_presence_removed_on_privacy_delete(client, subject, zone):
    pev(client,event_ref=uid("obs"),direction="enter",subject_ref=subject,zone_id=zone)
    assert client.get(f"/v1/privacy/subjects/{subject}/export").json()["presence_sessions"]
    assert client.delete(f"/v1/privacy/subjects/{subject}").status_code==200
    assert sql("select count(*) from presence_sessions where subject_ref=%s",(subject,))[0][0]==0
    assert sql("select count(*) from presence_observations where subject_ref=%s",(subject,))[0][0]==0

def test_presence_lan_denied(lan):
    assert lan.post("/v1/presence/events",json={"event_ref":"a","direction":"enter"}).status_code==403
    assert lan.get("/v1/presence/current").status_code==403
    assert lan.get("/v1/presence/history").status_code==403

# ---------------- Mission 23: unknown clusters ----------------

def test_unknown_cluster_lifecycle(client):
    cid=uid("uc")
    r=client.post("/v1/unknown-clusters",json={"cluster_id":cid,"label":"Blue jacket, north door","owner_ref":"kc:operator-7"})
    assert r.status_code==200 and r.json()["identity_asserted"] is False
    assert client.post("/v1/unknown-clusters",json={"cluster_id":cid,"label":"dup"}).status_code==409
    auto=client.post("/v1/unknown-clusters",json={"label":"auto id"}).json()
    assert auto["cluster_id"].startswith("uc-")
    e1,e2=make_event(),make_event()
    a=client.post(f"/v1/unknown-clusters/{cid}/events",json={"event_ids":[e1,e2,e1]}).json()
    assert sorted(a["attached"])==sorted([e1,e2]) and a["already_attached"]==[]
    again=client.post(f"/v1/unknown-clusters/{cid}/events",json={"event_ids":[e1]}).json()
    assert again["attached"]==[] and again["already_attached"]==[e1]
    assert client.post(f"/v1/unknown-clusters/{auto['cluster_id']}/events",json={"event_ids":[e1]}).status_code==409
    detail=client.get(f"/v1/unknown-clusters/{cid}").json()
    assert detail["event_count"]==2 and "subject_id" not in detail
    listed={c["cluster_id"]:c for c in client.get("/v1/unknown-clusters").json()}
    assert listed[cid]["event_count"]==2
    assert client.delete(f"/v1/unknown-clusters/{cid}/events/{e2}").json()["detached"] is True
    assert client.delete(f"/v1/unknown-clusters/{cid}/events/{e2}").status_code==404
    p=client.patch(f"/v1/unknown-clusters/{cid}",json={"status":"monitoring","label":"Renamed"}).json()
    assert p["status"]=="monitoring" and p["label"]=="Renamed"
    actions=[x for x,_ in audit_for(cid)]
    assert actions[0]=="unknown_cluster.created" and "unknown_cluster.events_attached" in actions and "unknown_cluster.event_detached" in actions

def test_unknown_cluster_refuses_identity_and_bad_refs(client, subject):
    assert client.post("/v1/unknown-clusters",json={"label":"x","subject_id":subject}).status_code==422
    cid=client.post("/v1/unknown-clusters",json={"label":"x"}).json()["cluster_id"]
    assert client.patch(f"/v1/unknown-clusters/{cid}",json={"subject_id":subject}).status_code==422
    assert client.patch(f"/v1/unknown-clusters/{cid}",json={"status":"identified"}).status_code==400
    assert client.post("/v1/unknown-clusters",json={"label":"x","status":"bogus"}).status_code==400
    recognized=make_event("recognized_face",subject_id=subject)
    assert client.post(f"/v1/unknown-clusters/{cid}/events",json={"event_ids":[recognized]}).status_code==400
    assert client.post(f"/v1/unknown-clusters/{cid}/events",json={"event_ids":["missing"]}).status_code==400
    assert client.post("/v1/unknown-clusters/nope/events",json={"event_ids":[make_event()]}).status_code==404
    assert client.get("/v1/unknown-clusters/nope").status_code==404
    assert client.patch("/v1/unknown-clusters/nope",json={"label":"y"}).status_code==404

def test_unknown_cluster_lan_denied(lan):
    assert lan.get("/v1/unknown-clusters").status_code==403
    assert lan.post("/v1/unknown-clusters",json={"label":"x"}).status_code==403

# ---------------- Mission 25: review queues ----------------

def test_review_queue_crud(client):
    qid=uid("q")
    r=client.post("/v1/review-queues",json={"queue_id":qid,"name":"Unknown faces","default_priority":"high"})
    assert r.status_code==200 and r.json()["status"]=="active"
    assert client.post("/v1/review-queues",json={"queue_id":qid,"name":"dup"}).status_code==409
    assert client.post("/v1/review-queues",json={"queue_id":uid("q"),"name":"x","status":"weird"}).status_code==400
    assert client.post("/v1/review-queues",json={"queue_id":uid("q"),"name":"x","default_priority":"p0"}).status_code==400
    assert client.patch(f"/v1/review-queues/{qid}",json={"status":"paused"}).json()["status"]=="paused"
    assert client.get(f"/v1/review-queues/{qid}").json()["item_counts"]=={}
    assert qid in [q["queue_id"] for q in client.get("/v1/review-queues").json()]
    assert client.delete(f"/v1/review-queues/{qid}").json()["deleted"] is True
    assert client.get(f"/v1/review-queues/{qid}").status_code==404
    assert [a for a,_ in audit_for(qid)]==["review_queue.created","review_queue.updated","review_queue.deleted"]

def test_review_items_all_types_idempotent_and_ordered(client):
    qid=uid("q"); client.post("/v1/review-queues",json={"queue_id":qid,"name":"Ops"})
    ev=make_event()
    inc=uid("inc"); client.post("/v1/incidents",json={"incident_id":inc,"title":"t"})
    reg=uid("reg"); sql("insert into registration_requests(request_id,display_name,id_hash,id_last4,embedding,consent_reference) values(%s,'R',%s,'1234','[]'::jsonb,'c')",(reg,uid("h")))
    uc=client.post("/v1/unknown-clusters",json={"label":"c"}).json()["cluster_id"]
    made={}
    for t,ref,prio in (("event",ev,"low"),("registration",reg,None),("incident",inc,"urgent"),("unknown_cluster",uc,"high")):
        r=client.post(f"/v1/review-queues/{qid}/items",json={"item_type":t,"item_ref":ref,"priority":prio,"assignee_ref":"kc:user-42"})
        assert r.status_code==200 and r.json()["created"] is True,r.text
        made[t]=r.json()["item_id"]
    dup=client.post(f"/v1/review-queues/{qid}/items",json={"item_type":"event","item_ref":ev})
    assert dup.json()["created"] is False and dup.json()["item_id"]==made["event"]
    items=client.get(f"/v1/review-queues/{qid}/items").json()
    assert [i["priority"] for i in items]==["urgent","high","normal","low"]
    assert len(client.get(f"/v1/review-queues/{qid}/items?assignee_ref=kc:user-42").json())==4
    iid=made["incident"]
    p=client.patch(f"/v1/review-queues/{qid}/items/{iid}",json={"status":"resolved","assignee_ref":None}).json()
    assert p["status"]=="resolved" and p["resolved_at"] and p["assignee_ref"] is None
    reopened=client.patch(f"/v1/review-queues/{qid}/items/{iid}",json={"status":"open"}).json()
    assert reopened["resolved_at"] is None
    assert client.get(f"/v1/review-queues/{qid}/items/{iid}").json()["item_id"]==iid
    assert client.delete(f"/v1/review-queues/{qid}").status_code==409
    client.patch(f"/v1/review-queues/{qid}",json={"status":"archived"})
    assert client.post(f"/v1/review-queues/{qid}/items",json={"item_type":"event","item_ref":make_event()}).status_code==409
    assert "review_item.updated" in [a for a,_ in audit_for(iid)]

def test_review_items_invalid_refs(client):
    qid=uid("q"); client.post("/v1/review-queues",json={"queue_id":qid,"name":"Ops"})
    for t in ("event","registration","incident","unknown_cluster"):
        assert client.post(f"/v1/review-queues/{qid}/items",json={"item_type":t,"item_ref":"missing"}).status_code==400
    assert client.post(f"/v1/review-queues/{qid}/items",json={"item_type":"subject","item_ref":"x"}).status_code==400
    ev=make_event()
    assert client.post(f"/v1/review-queues/{qid}/items",json={"item_type":"event","item_ref":ev,"assignee_ref":"role=admin; drop"}).status_code==400
    assert client.post(f"/v1/review-queues/{qid}/items",json={"item_type":"event","item_ref":ev,"priority":"p0"}).status_code==400
    assert client.post(f"/v1/review-queues/{qid}/items",json={"item_type":"event","item_ref":ev,"role":"admin"}).status_code==422
    assert client.post("/v1/review-queues/nope/items",json={"item_type":"event","item_ref":ev}).status_code==404
    iid=client.post(f"/v1/review-queues/{qid}/items",json={"item_type":"event","item_ref":ev}).json()["item_id"]
    assert client.patch(f"/v1/review-queues/{qid}/items/{iid}",json={"status":"done"}).status_code==400
    assert client.patch(f"/v1/review-queues/{qid}/items/missing",json={"status":"open"}).status_code==404
    assert client.patch(f"/v1/review-queues/other/items/{iid}",json={"status":"open"}).status_code==404

def test_review_role_headers_not_trusted(client, lan):
    qid=uid("q")
    hdrs={"X-Role":"admin","X-User":"kc:root","X-Forwarded-For":"127.0.0.1","X-Real-IP":"127.0.0.1"}
    assert lan.post("/v1/review-queues",json={"queue_id":qid,"name":"x"},headers=hdrs).status_code==403
    assert lan.get("/v1/review-queues",headers=hdrs).status_code==403
    client.post("/v1/review-queues",json={"queue_id":qid,"name":"x"},headers=hdrs)
    iid=client.post(f"/v1/review-queues/{qid}/items",json={"item_type":"event","item_ref":make_event()},headers=hdrs).json()
    assert iid["assignee_ref"] is None
    assert all(r[0]!="kc:root" for r in sql("select actor from audit_log where target_id=%s",(qid,)))

# ---------------- cross-cutting ----------------

def test_capabilities_and_openapi(client):
    cap=client.get("/v1/capabilities").json()
    assert cap["access_decisions"]["actuation"] is False and cap["access_decisions"]["decision_only"] is True
    assert cap["unknown_clusters"]["identity_assertion"] is False
    assert cap["review_queues"]["trusts_role_headers"] is False
    assert cap["camera_zone_mapping"]["stores_camera_credentials"] is False
    assert cap["presence"]["idempotency_key"]=="event_ref"
    assert cap["admin_access"]=="local-only"
    paths=client.get("/openapi.json").json()["paths"]
    for p in ("/v1/access/evaluate","/v1/presence/events","/v1/presence/current","/v1/presence/history",
              "/v1/unknown-clusters","/v1/unknown-clusters/{cluster_id}/events","/v1/camera-zones",
              "/v1/review-queues","/v1/review-queues/{queue_id}/items","/v1/review-queues/{queue_id}/items/{item_id}"):
        assert p in paths

def test_schema_migration_idempotent(client):
    from app import main
    main.init_db(); main.init_db()

def test_existing_boundary_preserved(lan):
    assert lan.get("/").status_code==403
    assert lan.get("/v1/subjects").status_code==403
    assert lan.get("/healthz").status_code==200
    assert lan.get("/register").status_code in (403,503)
