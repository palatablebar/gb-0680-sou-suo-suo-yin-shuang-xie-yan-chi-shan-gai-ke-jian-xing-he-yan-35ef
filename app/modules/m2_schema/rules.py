import json
from app.values import number,instant,SENTINELS
from app.reasons import reject
from app.errors import DomainError
ALIASES={"新增":"upsert","修改":"upsert","upsert":"upsert","删除":"delete","delete":"delete"}
def declared_scope(context):
    params=context.get("parameters",{}) if isinstance(context,dict) else {}
    scope=params.get("tenant_scope") or []
    if isinstance(scope,str): scope=[scope]
    return {str(t).strip() for t in scope if str(t).strip()}
def evaluate(rows,context):
    good=[];bad=[];scope=declared_scope(context or {})
    for row in rows:
        try:
            tenant=str(row.get("tenant_id","") or "").strip()
            if tenant.upper() in SENTINELS:raise DomainError("TENANT_MISSING","缺少租户归属，不做猜配")
            if scope and tenant not in scope:raise DomainError("TENANT_OUT_OF_SCOPE","租户不在本次切换范围")
            version=number(row["version"]);op=ALIASES.get(row["op"])
            if version<1 or version!=version.to_integral_value():raise DomainError("BAD_VERSION","版本必须为正整数")
            if op is None or row["side"] not in {"source","index"}:raise DomainError("BAD_OPERATION","操作或数据端无效")
            source=instant(row["source_time"]);visible=instant(row["visible_time"]) if row["visible_time"] not in {"","-","NULL"} else None
            if visible and visible<source:raise DomainError("NEGATIVE_LATENCY","可见时间早于源事件")
            payload=json.loads(row["payload"]) if op=="upsert" else None
            if op=="upsert" and not isinstance(payload,dict):raise DomainError("BAD_PAYLOAD","文档需要JSON对象")
            good.append({**row,"tenant_id":tenant,"version":format(version.to_integral_value(),"f"),"op":op,"source_at":source.isoformat(),"visible_at":visible.isoformat() if visible else None,"document":payload,"reported":str(number(row["reported"]))})
        except (DomainError,KeyError,ValueError) as e:bad.append(reject(row,getattr(e,"code","BAD_PAYLOAD"),str(e)))
    return {"rows":good,"quarantine":bad,"metrics":{"accepted":len(good),"deletes":sum(r["op"]=="delete" for r in good),"tenants":sorted({r["tenant_id"] for r in good})}}
