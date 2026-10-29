from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
import hmac, json, os, uuid
import sqlite3
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from .config import API_ACCESS_TOKEN, APP_ENV, BLOCKCHAIN_MODE, CORS_ORIGINS, DATA_DIR
from .db import init_db, list_datasets, get_dataset, save_dataset, update_dataset, save_decision, update_decision, list_decisions, get_decision, save_audit_event, list_audit_events, verify_audit_chain
from .services.signature_service import sign_dataset
from .services.rights_engine import evaluate, POLICY_VERSION
from .services.manifest_service import manifests, manifest_details
from .services.cost_service import allocate_cost
from .services import blockchain_service
from optimizer.classical_baseline import select as classical_select
from optimizer.opt_selector import select_with_qpiai
from optimizer.quantum_experiment import run_experiment

@asynccontextmanager
async def lifespan(_app):
    startup()
    yield

app=FastAPI(title="BhashaChain API",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=CORS_ORIGINS,allow_methods=["GET","POST"],allow_headers=["Content-Type","Authorization"])

class DatasetIn(BaseModel):
    dataset_id:str=Field(min_length=1,max_length=128,pattern=r"^[A-Za-z0-9._-]+$"); language:str=Field(min_length=2,max_length=16)
    content_hash:str=Field(pattern=r"^[a-fA-F0-9]{64}$"); licence_version:str=Field(min_length=1,max_length=32)
    issuer:str=Field(min_length=1,max_length=256); purposes:list[str]=Field(min_length=1); regions:list[str]=Field(min_length=1)
    derivatives_allowed:bool=False; redistribution_allowed:bool=False
    expires_at:str; licensing_cost:float=Field(ge=0,allow_inf_nan=False); active:bool=True
    @field_validator("expires_at")
    @classmethod
    def valid_future_expiry(cls,value):
        try: expiry=datetime.fromisoformat(value.replace("Z","+00:00"))
        except (ValueError,AttributeError): raise ValueError("expires_at must be an ISO 8601 timestamp")
        if expiry.tzinfo is None: expiry=expiry.replace(tzinfo=timezone.utc)
        if expiry<=datetime.now(timezone.utc): raise ValueError("expires_at must be in the future")
        return value
    @field_validator("purposes","regions")
    @classmethod
    def valid_terms(cls,values):
        cleaned=[value.strip() for value in values]
        if any(not value for value in cleaned) or len(cleaned)!=len(set(cleaned)):
            raise ValueError("purpose and region lists must contain unique, nonempty values")
        return cleaned
class CheckIn(BaseModel):
    dataset_id:str; purpose:str; geography:str; content_hash:str|None=None; licence_version:str|None=None; rights_record_version:int|None=None
    derivatives:bool=False; redistribution:bool=False
class LicenceUpdateIn(BaseModel):
    content_hash:str=Field(pattern=r"^[a-fA-F0-9]{64}$"); licence_version:str=Field(min_length=1,max_length=32)
    purposes:list[str]=Field(min_length=1); regions:list[str]=Field(min_length=1)
    derivatives_allowed:bool=False; redistribution_allowed:bool=False; expires_at:str
    @field_validator("expires_at")
    @classmethod
    def valid_future_expiry(cls,value):
        try: expiry=datetime.fromisoformat(value.replace("Z","+00:00"))
        except (ValueError,AttributeError): raise ValueError("expires_at must be an ISO 8601 timestamp")
        if expiry.tzinfo is None: expiry=expiry.replace(tzinfo=timezone.utc)
        if expiry<=datetime.now(timezone.utc): raise ValueError("expires_at must be in the future")
        return value
    @field_validator("purposes","regions")
    @classmethod
    def valid_terms(cls,values):
        cleaned=[value.strip() for value in values]
        if any(not value for value in cleaned) or len(cleaned)!=len(set(cleaned)):
            raise ValueError("purpose and region lists must contain unique, nonempty values")
        return cleaned
class OptimizeIn(BaseModel):
    languages:list[str]=Field(min_length=1); budget:float=Field(ge=0,allow_inf_nan=False); mandatory_dataset_ids:list[str]=Field(default_factory=list); geography:str=Field(default="IN",min_length=1,max_length=16); purpose:str=Field(default="commercial_training",min_length=1,max_length=64)
    @field_validator("languages","mandatory_dataset_ids")
    @classmethod
    def clean_list_values(cls,values):
        cleaned=[value.strip() for value in values]
        if any(not value for value in cleaned) or len(cleaned)!=len(set(cleaned)):
            raise ValueError("values must be unique and nonempty")
        return cleaned

def startup():
    init_db()
    seed=DATA_DIR/"sample_datasets.json"
    if seed.exists() and not list_datasets():
        for d in json.loads(seed.read_text(encoding="utf-8")):
            d["created_at"]=datetime.now(timezone.utc).isoformat()
            d["signature"]=sign_dataset(d); save_dataset(d)

def require_api_access(authorization:str|None=Header(default=None)):
    if API_ACCESS_TOKEN:
        supplied=authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not hmac.compare_digest(supplied,API_ACCESS_TOKEN): raise HTTPException(401,"API_ACCESS_TOKEN_REQUIRED")
    elif APP_ENV=="production":
        raise HTTPException(503,"WRITE_AUTH_NOT_CONFIGURED")
    return True

def evaluate_request(dataset,request):
    reasons,evidence=evaluate(dataset,request)
    chain={"status":"disabled","verified":False,"mode":"disabled"}
    if BLOCKCHAIN_MODE not in ("disabled","optional","required"):
        reasons.append("BLOCKCHAIN_CONFIGURATION_INVALID")
        chain={"status":"invalid_mode","verified":False,"mode":BLOCKCHAIN_MODE}
    elif BLOCKCHAIN_MODE!="disabled":
        if dataset is None:
            chain={"status":"not_checked","verified":False,"mode":BLOCKCHAIN_MODE}
        else:
            chain=blockchain_service.verify_dataset(dataset["dataset_id"],dataset["content_hash"],
                purpose=request.get("purpose"),geography=request.get("geography"),
                derivatives=request.get("derivatives",False),redistribution=request.get("redistribution",False),
                expected_version=dataset.get("licence_version"),expected_expiry=dataset.get("expires_at"))
            chain["mode"]=BLOCKCHAIN_MODE
            if chain.get("status")=="unavailable" and BLOCKCHAIN_MODE=="required": reasons.append("BLOCKCHAIN_UNAVAILABLE")
            elif chain.get("status")=="missing": reasons.append("ONCHAIN_RECORD_MISMATCH")
            elif chain.get("status")=="mismatch":
                reasons.append("STALE_RIGHTS_RECORD" if chain.get("version_match") is False or chain.get("expiry_match") is False else "ONCHAIN_RECORD_MISMATCH")
            if chain.get("revoked"): reasons.append("LICENCE_REVOKED_ON_CHAIN")
            if chain.get("policy_permitted") is False and not chain.get("revoked"): reasons.append("ONCHAIN_POLICY_MISMATCH")
    return reasons,evidence,chain

@app.get("/health")
def health():
    chain={"status":"disabled","verified":False,"mode":"disabled"} if BLOCKCHAIN_MODE=="disabled" else blockchain_service.status()
    chain["mode"]=BLOCKCHAIN_MODE
    return {"status":"ok","database":"connected","blockchain":chain["status"],"blockchain_details":chain,"blockchain_mode":BLOCKCHAIN_MODE,"write_auth":"required" if API_ACCESS_TOKEN or APP_ENV=="production" else "local_open","opt":"configured" if os.getenv("QPIAI_OPT_API_KEY") else "not_configured","qcloud":"configured" if os.getenv("QCLOUD_API_KEY") else "not_configured"}

@app.get("/api/auth/check")
def auth_check(_authorized=Depends(require_api_access)):
    return {"authenticated":True,"actor":"api-admin"}

@app.get("/api/datasets")
def datasets(): return list_datasets()

@app.post("/api/datasets")
def register_dataset(payload:DatasetIn,_authorized=Depends(require_api_access)):
    if get_dataset(payload.dataset_id): raise HTTPException(409,"DATASET_ALREADY_REGISTERED")
    d=payload.model_dump(); d["active"]=True; d["created_at"]=datetime.now(timezone.utc).isoformat(); d["signature"]=sign_dataset(d)
    if BLOCKCHAIN_MODE=="disabled":
        d["blockchain"]={"status":"disabled","verified":False}
    elif BLOCKCHAIN_MODE in ("optional","required"):
        d["blockchain"]=blockchain_service.register(d)
        if d["blockchain"].get("status")!="confirmed" or d["blockchain"].get("verified") is not True:
            raise HTTPException(503,{"code":"BLOCKCHAIN_REGISTRATION_REQUIRED","blockchain":d["blockchain"]})
    else:
        raise HTTPException(503,{"code":"BLOCKCHAIN_CONFIGURATION_INVALID"})
    try: save_dataset(d)
    except sqlite3.IntegrityError: raise HTTPException(409,"DATASET_ALREADY_REGISTERED")
    save_audit_event("DATASET_REGISTERED",{"dataset_id":d["dataset_id"],"rights_record_id":d.get("record_id"),"record_version":d.get("record_version"),"blockchain":d["blockchain"]},d["created_at"])
    return d

@app.get("/api/datasets/{dataset_id}")
def dataset_detail(dataset_id:str):
    d=get_dataset(dataset_id)
    if not d: raise HTTPException(404,"UNKNOWN_DATASET")
    return d

@app.post("/api/decisions/check")
def decision_check(payload:CheckIn,_authorized=Depends(require_api_access)):
    d=get_dataset(payload.dataset_id); req=payload.model_dump(exclude={"dataset_id"})
    reasons,evidence,chain=evaluate_request(d,req)
    decision_id=str(uuid.uuid4()); trace_id=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat()
    row={"decision_id":decision_id,"trace_id":trace_id,"dataset_id":payload.dataset_id,"content_hash":d.get("content_hash") if d else payload.content_hash,"decision":"ACCEPT" if not reasons else "REJECT","reasons":reasons,"reason_codes":reasons,"purpose":payload.purpose,"geography":payload.geography,"licence_version":d.get("licence_version") if d else payload.licence_version,"rights_record_version":(evidence.get("rights_record_version") if d else None),"policy_version":POLICY_VERSION,"signature_verification":evidence.get("signature_verification"),"blockchain_verification":chain,"evaluated_at":now,"timestamp":now,"transaction_ref":(d or {}).get("blockchain",{}).get("transaction_hash"),"optimization_run_id":None}
    save_decision(row)
    manifests()
    accepted=manifest_details("accepted"); rejected=manifest_details("rejected")
    row["manifest_references"]={"accepted":accepted["manifest_id"],"rejected":rejected["manifest_id"]}
    update_decision(row)
    save_audit_event("MANIFEST_GENERATED",{"decision_id":decision_id,"accepted_manifest_id":accepted["manifest_id"],"rejected_manifest_id":rejected["manifest_id"],"accepted_manifest_hash":accepted["manifest_hash"],"rejected_manifest_hash":rejected["manifest_hash"]},now,decision_id,trace_id=trace_id)
    return row

@app.post("/api/optimization/run")
def optimize(payload:OptimizeIn,_authorized=Depends(require_api_access)):
    run_id=str(uuid.uuid4()); all_data=list_datasets(); eligible=[]; excluded=[]
    for d in all_data:
        reasons,_,_=evaluate_request(d,{"purpose":payload.purpose,"geography":payload.geography})
        (eligible if not reasons else excluded).append({**d,"eligible":not reasons,"exclusion_reasons":reasons})
    eligible_ids={d["dataset_id"] for d in eligible}
    mandatory_failures=[{"dataset_id":dataset_id,"reasons":next((x["exclusion_reasons"] for x in excluded if x["dataset_id"]==dataset_id),["UNKNOWN_DATASET"])} for dataset_id in payload.mandatory_dataset_ids if dataset_id not in eligible_ids]
    if mandatory_failures:
        save_audit_event("OPTIMIZATION_REJECTED",{"optimization_run_id":run_id,"code":"MANDATORY_DATASET_INELIGIBLE","mandatory_failures":mandatory_failures,"inputs":payload.model_dump()},datetime.now(timezone.utc).isoformat(),trace_id=run_id)
        raise HTTPException(422,{"code":"MANDATORY_DATASET_INELIGIBLE","optimization_run_id":run_id,"mandatory_failures":mandatory_failures})
    classical=classical_select(eligible,payload.languages,payload.budget,payload.mandatory_dataset_ids)
    opt=select_with_qpiai(eligible,payload.languages,payload.budget,payload.mandatory_dataset_ids)
    selected=[d for d in eligible if d["dataset_id"] in opt.get("selected_dataset_ids",[])]
    if opt.get("feasible"):
        opt["cost_allocation"]=allocate_cost(selected)
    classical_selected=[d for d in eligible if d["dataset_id"] in classical.get("selected_dataset_ids",[])]
    if classical.get("feasible"): classical["cost_allocation"]=allocate_cost(classical_selected)
    response={"optimization_run_id":run_id,"eligible_datasets":[d["dataset_id"] for d in eligible],"excluded_datasets":[{"dataset_id":d["dataset_id"],"reasons":d["exclusion_reasons"]} for d in excluded],"required_languages":payload.languages,"budget":payload.budget,"mandatory_dataset_ids":payload.mandatory_dataset_ids,"geography":payload.geography,"purpose":payload.purpose,"qpiai_opt":opt,"classical_baseline":classical}
    save_audit_event("OPTIMIZATION_RUN",response,datetime.now(timezone.utc).isoformat(),trace_id=run_id)
    return response

@app.post("/api/datasets/{dataset_id}/revoke")
def revoke_dataset(dataset_id:str,_authorized=Depends(require_api_access)):
    d=get_dataset(dataset_id)
    if not d: raise HTTPException(404,"UNKNOWN_DATASET")
    if not d.get("active",True): raise HTTPException(409,"DATASET_ALREADY_REVOKED")
    if BLOCKCHAIN_MODE=="disabled": raise HTTPException(409,"BLOCKCHAIN_MODE_DISABLED")
    chain=blockchain_service.revoke(dataset_id)
    if chain.get("status")!="confirmed" or chain.get("verified") is not True:
        raise HTTPException(409,{"code":"BLOCKCHAIN_REVOCATION_NOT_CONFIRMED","blockchain":chain})
    now=datetime.now(timezone.utc).isoformat(); d["active"]=False; d["revocation_status"]="revoked"; d["revoked_at"]=now; d["updated_at"]=now; d["record_version"]=int(d.get("record_version",1))+1; d["signature"]=sign_dataset(d); d["blockchain_revocation"]=chain
    update_dataset(d)
    save_audit_event("DATASET_REVOKED",{"dataset_id":dataset_id,"blockchain":chain},datetime.now(timezone.utc).isoformat())
    return d

@app.post("/api/datasets/{dataset_id}/update")
def update_dataset_licence(dataset_id:str,payload:LicenceUpdateIn,_authorized=Depends(require_api_access)):
    d=get_dataset(dataset_id)
    if not d: raise HTTPException(404,"UNKNOWN_DATASET")
    if not d.get("active",True): raise HTTPException(409,"LICENCE_REVOKED")
    if BLOCKCHAIN_MODE=="disabled": raise HTTPException(409,"BLOCKCHAIN_MODE_DISABLED")
    changed=payload.model_dump()
    changed.update({"updated_at":datetime.now(timezone.utc).isoformat(),"record_version":int(d.get("record_version",1))+1,"revocation_status":"active","revoked_at":None})
    chain=blockchain_service.update(dataset_id,changed)
    if chain.get("status")!="confirmed" or chain.get("verified") is not True:
        raise HTTPException(409,{"code":"BLOCKCHAIN_UPDATE_NOT_CONFIRMED","blockchain":chain})
    d.update(changed); d["signature"]=sign_dataset(d); d["blockchain_update"]=chain
    update_dataset(d)
    save_audit_event("LICENCE_UPDATED",{"dataset_id":dataset_id,"blockchain":chain},datetime.now(timezone.utc).isoformat())
    return d

@app.get("/api/audit/events")
def audit_events(): return list_audit_events()

@app.get("/api/audit/integrity")
def audit_integrity(): return verify_audit_chain()

@app.get("/api/blockchain/registry/{dataset_id}")
def blockchain_registry_entry(dataset_id:str): return blockchain_service.registry_lookup(dataset_id)

@app.get("/api/blockchain/transactions/{transaction_hash}")
def blockchain_transaction(transaction_hash:str): return blockchain_service.transaction_status(transaction_hash)

@app.get("/api/blockchain/events/{dataset_id}")
def blockchain_events(dataset_id:str,from_block:int=0): return blockchain_service.registry_events(dataset_id,from_block)

@app.post("/api/quantum/run")
def quantum_run(_authorized=Depends(require_api_access)): return run_experiment()

@app.get("/api/manifests/accepted")
def accepted_manifest(): return manifest_details("accepted")

@app.get("/api/manifests/rejected")
def rejected_manifest(): return manifest_details("rejected")

@app.get("/api/audit")
def audit(): return list_decisions()

@app.get("/api/audit/{decision_id}")
def audit_detail(decision_id:str):
    d=get_decision(decision_id)
    if not d: raise HTTPException(404,"DECISION_NOT_FOUND")
    return d
