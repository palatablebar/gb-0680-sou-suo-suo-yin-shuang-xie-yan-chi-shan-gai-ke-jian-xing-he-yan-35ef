import csv,io,json
import pytest
from app.pipeline import calculate,execute,load_sample
from app import store
from app.modules.m1_streams.rules import evaluate as intake
from app.modules.m2_schema.rules import evaluate as schema
from app.modules.m3_versions.rules import evaluate as versions
from app.modules.m4_visibility.rules import evaluate as visibility
from app.modules.m7_backfills.rules import evaluate as seal
from app.errors import DomainError

def contract_row(tenant,event="1",doc="01"):
    return {"event_id":event,"tenant_id":tenant,"doc_id":doc,"version":"1","op":"upsert","side":"source","source_time":"2026-11-20T09:00:00Z","visible_time":"-","payload":"{}","reported":"1"}
def final_row(tenant,doc,side,version="1",document=None,event="1"):
    return {"event_id":event,"tenant_id":tenant,"doc_id":doc,"side":side,"version":version,"op":"upsert","document":document if document is not None else {"a":1},"source_at":"2026-11-20T09:00:00Z","visible_at":"2026-11-20T09:01:00Z","_sources":[int(event)]}

def test_intake_accepts_tenant_column():
    r=intake(load_sample("tenant.csv"))
    assert r["metrics"]["tenant_column"] is True and r["metrics"]["accepted"]==18
def test_intake_legacy_header_keeps_rows_unattributed():
    r=intake(load_sample("legacy.csv"))
    assert r["metrics"]["tenant_column"] is False and all(row["tenant_id"]=="" for row in r["rows"])
def test_missing_tenant_quarantined_not_guessed():
    "TRAP-28 缺归属行隔离，不猜配到任何租户"
    rows=[contract_row(""),contract_row("未知",event="2"),contract_row("NULL",event="3"),contract_row("t-a",event="4")]
    r=schema(rows,{})
    assert [q["reason"] for q in r["quarantine"]]==["TENANT_MISSING"]*3
    assert [g["tenant_id"] for g in r["rows"]]==["t-a"] and r["metrics"]["tenants"]==["t-a"]
def test_out_of_scope_quarantined():
    "TRAP-29 声明范围外的租户不进本次切换结论"
    rows=[contract_row("t-a"),contract_row("t-b",event="2")]
    r=schema(rows,{"parameters":{"tenant_scope":["t-a"]}})
    assert [g["tenant_id"] for g in r["rows"]]==["t-a"]
    assert r["quarantine"][0]["reason"]=="TENANT_OUT_OF_SCOPE" and r["quarantine"][0]["tenant_id"]=="t-b"
def test_same_doc_id_distinct_tenants_no_conflict():
    "TRAP-27 同文档号同版本不同内容，跨租户不算冲突"
    rows=[final_row("t-a","01","source",document={"a":1}),final_row("t-b","01","source",document={"a":2},event="2")]
    r=versions(rows,{})
    assert len(r["rows"])==2 and r["quarantine"]==[]
def test_same_tenant_same_version_conflict_still_blocked():
    rows=[final_row("t-a","01","source",document={"a":1}),final_row("t-a","01","source",document={"a":2},event="2")]
    r=versions(rows,{})
    assert r["rows"]==[] and len(r["quarantine"])==2
def test_visibility_conclusion_unique_per_tenant_doc():
    rows=[final_row("t-a","01","source","2"),final_row("t-a","01","index","1"),final_row("t-b","01","source","3"),final_row("t-b","01","index","3")]
    r=visibility(rows,{})
    keys=[(x["tenant_id"],x["doc_id"]) for x in r["rows"]]
    assert keys==[("t-a","01"),("t-b","01")] and len(set(keys))==2
    assert r["rows"][0]["visibility_state"]=="STALE_INDEX" and r["rows"][1]["visibility_state"]=="CONSISTENT"
    assert r["metrics"]["tenant_scope"]==["t-a","t-b"]
def test_seal_duplicate_key_scoped_by_tenant():
    seal([{"tenant_id":"t-a","doc_id":"1"},{"tenant_id":"t-b","doc_id":"1"}],{})
    with pytest.raises(DomainError): seal([{"tenant_id":"t-a","doc_id":"1"},{"tenant_id":"t-a","doc_id":"1"}],{})

def test_tenant_sample_conclusions():
    r=calculate(load_sample("tenant.csv"))
    m=r["stages"][3]["metrics"]
    assert m["documents"]==8 and m["tenant_scope"]==["t-lab","t-main","t-new"]
    assert {(x["tenant_id"],x["doc_id"],x["visibility_state"]) for x in r["stages"][3]["rows"]}=={
        ("t-new","1001","CONSISTENT"),("t-main","1001","STALE_INDEX"),
        ("t-new","1002","CONSISTENT"),("t-new","1003","MISSING_INDEX"),
        ("t-main","1004","CONSISTENT"),("t-new","1007","CONSISTENT"),
        ("t-main","1007","CONSISTENT"),("t-lab","1005","CONSISTENT")}
def test_unattributed_never_enter_conclusions():
    r=calculate(load_sample("tenant.csv"))
    assert all(x["tenant_id"] for x in r["stages"][3]["rows"])
    missing=[q for q in r["stages"][3]["cumulative_quarantine"] if q["reason"]=="TENANT_MISSING"]
    assert len(missing)==3 and all(q["tenant_id"] in {"","未知"} for q in missing)
def test_legacy_sample_fully_isolated():
    r=calculate(load_sample("legacy.csv"))
    assert r["stages"][3]["rows"]==[] and r["stages"][5]["metrics"]["balanced"] is True
def test_declared_scope_excludes_other_tenants():
    r=calculate(load_sample("tenant.csv"),{"tenant_scope":["t-main","t-new"]})
    m=r["stages"][3]["metrics"]
    assert m["documents"]==7 and m["tenant_scope"]==["t-main","t-new"]
    out=[q for q in r["stages"][3]["cumulative_quarantine"] if q["reason"]=="TENANT_OUT_OF_SCOPE"]
    assert len(out)==2 and all(q["tenant_id"]=="t-lab" for q in out)
def test_rerun_same_input_stable_conclusions():
    raw=load_sample("tenant.csv")
    a=execute(raw);b=execute(raw)
    assert a["run_id"]==b["run_id"] and len(store.history())==1
    assert a["stages"][3]["rows"]==b["stages"][3]["rows"] and len(a["stages"][3]["rows"])==8
def test_scope_order_same_run():
    raw=load_sample("tenant.csv")
    a=execute(raw,{"tenant_scope":["t-main","t-new"]});b=execute(raw,{"tenant_scope":["t-new","t-main"]})
    assert a["run_id"]==b["run_id"] and len(store.history())==1
def test_bad_scope_rejected(client):
    r=client.post("/api/runs",json={"sample":"tenant.csv","parameters":{"tenant_scope":"t-new"}})
    assert r.status_code==422 and store.history()==[]
def test_page_and_archive_read_same_result(client):
    run=client.post("/api/runs",json={"sample":"tenant.csv","parameters":{"tenant_scope":["t-main","t-new"]}}).get_json()
    page=client.get("/visibility").get_data(as_text=True)
    for row in run["stages"][3]["rows"]:
        assert row["tenant_id"] in page and row["doc_id"] in page
    assert "t-main、t-new" in page
    evidence=client.get("/api/runs/"+run["run_id"]+"/archive").data.decode("utf-8-sig")
    rows=list(csv.reader(io.StringIO(evidence)))
    assert rows[0]==["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence","tenant_id"]
    scope_row=next(x for x in rows[1:] if x[3]=="tenant_scope")
    scope=json.loads(scope_row[6])
    assert scope=={"declared_scope":["t-main","t-new"],"concluded_scope":["t-main","t-new"]}
    accepted={(x[7],json.loads(x[6])["doc_id"]) for x in rows[1:] if x[3]=="accepted"}
    assert accepted=={(x["tenant_id"],x["doc_id"]) for x in run["stages"][3]["rows"]}
    assert any(x[3]=="quarantine" and x[5]=="TENANT_MISSING" for x in rows[1:])
    assert any(x[3]=="quarantine" and x[5]=="TENANT_OUT_OF_SCOPE" and x[7]=="t-lab" for x in rows[1:])
def test_archive_rerun_identical(client):
    p=client.post("/api/runs",json={"sample":"tenant.csv"}).get_json()
    a=client.get("/api/runs/"+p["run_id"]+"/archive").data
    client.post("/api/runs",json={"sample":"tenant.csv"})
    b=client.get("/api/runs/"+p["run_id"]+"/archive").data
    assert a==b
