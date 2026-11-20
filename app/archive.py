import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence","tenant_id"])
    meta=run["manifest"];last=run["stages"][-1]
    concluded=sorted({str(row.get("tenant_id","")) for row in last["rows"] if row.get("tenant_id")})
    scope={"declared_scope":run.get("parameters",{}).get("tenant_scope"),"concluded_scope":concluded}
    writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"tenant_scope","","",json.dumps(scope,ensure_ascii=False,sort_keys=True),""])
    for row in last["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False),row.get("tenant_id","")])
    for row in last.get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False),row.get("tenant_id","")])
    return "\ufeff"+stream.getvalue()
