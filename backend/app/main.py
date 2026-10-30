from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
import csv, hashlib, hmac, io, json, logging, os, re, uuid
import sqlite3
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, field_validator
from .config import API_ACCESS_TOKEN, APP_ENV, BLOCKCHAIN_MODE, CORS_ORIGINS, DATA_DIR
from .db import connect as connect_database
from .db import init_db, list_datasets, get_dataset, save_dataset, update_dataset, save_decision, update_decision, list_decisions, get_decision, save_audit_event, list_audit_events, verify_audit_chain, save_rights_lab_dataset, update_rights_lab_dataset, get_rights_lab_dataset, list_rights_lab_datasets, save_rights_lab_decision, list_rights_lab_decisions
from .services.signature_service import sign_dataset
from .services.rights_engine import evaluate, POLICY_VERSION
from .services.manifest_service import manifests, manifest_details, verified_lab_decisions
from .services.rights_lab import evaluate_evidence, benchmark_cases, validate_csv_import
from .services.cost_service import allocate_cost
from .services import blockchain_service
from optimizer.facility_dispatch import log_dispatch, solve_dispatch
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
    rights_evidence:dict|None=None
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
    @field_validator("rights_evidence")
    @classmethod
    def validate_attached_rights_evidence(cls,value):
        return RightsEvidenceIn.model_validate(value).model_dump() if value is not None else None
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
class DispatchJobIn(BaseModel):
    job_id:str=Field(min_length=1,max_length=64,pattern=r"^[A-Za-z0-9._-]+$")
    chemistry:str=Field(min_length=1,max_length=32,pattern=r"^[A-Za-z0-9._-]+$")
    units:int=Field(gt=0,le=1000)
class DispatchFacilityIn(BaseModel):
    facility_id:str=Field(min_length=1,max_length=64,pattern=r"^[A-Za-z0-9._-]+$")
    name:str=Field(min_length=1,max_length=64)
    capacity:int=Field(gt=0,le=1000)
    chemistries:list[str]=Field(min_length=1,max_length=16)
    cost_per_unit:float=Field(ge=0,allow_inf_nan=False)
    @field_validator("chemistries")
    @classmethod
    def valid_chemistries(cls,values):
        cleaned=[value.strip() for value in values]
        if any(not value or len(value)>32 for value in cleaned) or len(cleaned)!=len(set(x.casefold() for x in cleaned)):
            raise ValueError("chemistries must be unique, nonempty values of at most 32 characters")
        return cleaned
class FacilityDispatchIn(BaseModel):
    jobs:list[DispatchJobIn]=Field(min_length=1,max_length=6)
    facilities:list[DispatchFacilityIn]=Field(min_length=1,max_length=6)
    @field_validator("jobs")
    @classmethod
    def unique_job_ids(cls,values):
        if len({x.job_id for x in values})!=len(values): raise ValueError("job_id values must be unique")
        return values
    @field_validator("facilities")
    @classmethod
    def unique_facility_ids(cls,values):
        if len({x.facility_id for x in values})!=len(values): raise ValueError("facility_id values must be unique")
        return values

class RightsEvidenceIn(BaseModel):
    dataset_name:str=Field(min_length=1,max_length=256); language:str=Field(min_length=2,max_length=16)
    modality:str=Field(min_length=1,max_length=64); source_url:str=Field(min_length=8,max_length=2048)
    file_sha256:str|None=Field(default=None,pattern=r"^[a-fA-F0-9]{64}$")
    source_publisher:str=Field(min_length=1,max_length=256); licence_name:str=Field(min_length=1,max_length=256)
    licence_url:str=Field(min_length=8,max_length=2048)
    licence_evidence_status:str; provenance_status:str; intended_purpose:str=Field(min_length=1,max_length=128)
    commercial_training:bool|None=None; attribution_required:bool|None=None
    redistribution_conditions:str=""; share_alike_conditions:str=""
    expiry_date:str|None=None; expiry_evidence_status:str="UNKNOWN"; revocation_status:str="UNKNOWN"
    evidence_notes:str=Field(min_length=1,max_length=4000)
    evidence_timestamp:str=Field(min_length=10,max_length=64)
    @field_validator("source_url","licence_url")
    @classmethod
    def require_https_evidence_links(cls,value):
        if not value.startswith("https://"):
            raise ValueError("evidence links must use HTTPS")
        return value
    @field_validator("licence_evidence_status","provenance_status","expiry_evidence_status")
    @classmethod
    def valid_evidence_status(cls,value):
        normalized=value.upper()
        if normalized not in {"VERIFIED","UNVERIFIED","UNKNOWN","NEEDS_REVIEW"}:
            raise ValueError("evidence status must be VERIFIED, UNVERIFIED, UNKNOWN, or NEEDS_REVIEW")
        return normalized
    @field_validator("revocation_status")
    @classmethod
    def valid_revocation_status(cls,value):
        normalized=value.upper()
        if normalized not in {"ACTIVE","REVOKED","UNKNOWN"}:
            raise ValueError("revocation status must be ACTIVE, REVOKED, or UNKNOWN")
        return normalized

class RightsLabImportIn(BaseModel):
    dataset_id:str=Field(min_length=1,max_length=128,pattern=r"^[A-Za-z0-9._-]+$")
    filename:str=Field(min_length=5,max_length=255); row_count:int=Field(ge=20)
    columns:list[str]=Field(min_length=2,max_length=128); source_url:str=Field(min_length=8,max_length=2048)
    file_sha256:str=Field(pattern=r"^[a-fA-F0-9]{64}$")
    sample_rows:list[dict[str,str]]=Field(min_length=20,max_length=50)
    rights_evidence:RightsEvidenceIn

class RightsLabCheckIn(BaseModel):
    dataset_id:str; purpose:str=Field(min_length=1,max_length=128); geography:str=Field(min_length=1,max_length=16)
    attribution_provided:bool|None=None; will_share_adapted_work:bool|None=None; share_alike_acknowledged:bool|None=None

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
    connection = None
    try:
        connection = connect_database()
        connection.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        logging.getLogger(__name__).error("Database health check failed error_type=%s", type(exc).__name__)
        raise HTTPException(503, "DATABASE_UNAVAILABLE") from exc
    finally:
        if connection is not None:
            connection.close()
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
    if payload.rights_evidence is not None:
        evidence_hash=payload.rights_evidence.get("file_sha256")
        if not isinstance(evidence_hash,str) or evidence_hash.lower()!=payload.content_hash.lower():
            raise HTTPException(422,"SIGNED_RIGHTS_EVIDENCE_FILE_HASH_MISMATCH")
        evidence_check=evaluate_evidence(payload.rights_evidence,{"purpose":payload.rights_evidence["intended_purpose"],"attribution_provided":True,"will_share_adapted_work":False})
        if evidence_check["decision"]!="ALLOWED":
            raise HTTPException(422,{"code":"RIGHTS_EVIDENCE_NOT_READY_FOR_REGISTRATION","decision":evidence_check["decision"],"reason_codes":evidence_check["reason_codes"]})
    d=payload.model_dump(exclude_none=True); d["active"]=True; d["created_at"]=datetime.now(timezone.utc).isoformat(); d["signature"]=sign_dataset(d)
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

@app.post("/api/qubo/dispatch")
async def qubo_dispatch(request:Request,_authorized=Depends(require_api_access)):
    supplied=request.headers.get("X-Request-ID","")
    trace_id=supplied if re.fullmatch(r"[A-Za-z0-9._-]{1,64}",supplied) else uuid.uuid4().hex
    log_dispatch(logging.INFO,"Dispatch request received",trace_id)
    try:
        raw=await request.json()
    except Exception as exc:
        log_dispatch(logging.WARNING,"Dispatch input validation failed",trace_id,error_type=type(exc).__name__)
        raise HTTPException(422,{"code":"DISPATCH_INVALID_JSON","trace_id":trace_id})
    try:
        payload=FacilityDispatchIn.model_validate(raw)
    except ValidationError as exc:
        fields=[".".join(str(part) for part in item.get("loc",())) for item in exc.errors()]
        log_dispatch(logging.WARNING,"Dispatch input validation failed",trace_id,error_count=len(fields),fields=fields)
        raise HTTPException(422,{"code":"DISPATCH_INVALID_INPUT","trace_id":trace_id,"invalid_fields":fields})
    log_dispatch(logging.INFO,"Dispatch input validation completed",trace_id,
                 job_count=len(payload.jobs),facility_count=len(payload.facilities))
    started=__import__("time").perf_counter()
    try:
        return solve_dispatch(payload.model_dump(),trace_id)
    except Exception as exc:
        log_dispatch(logging.ERROR,"Dispatch execution failed",trace_id,error_type=type(exc).__name__,
                     duration_ms=round((__import__("time").perf_counter()-started)*1000,3))
        raise HTTPException(500,{"code":"DISPATCH_SOLVER_ERROR","trace_id":trace_id})

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

@app.get("/api/manifests/needs-review")
def needs_review_manifest(): return manifest_details("needs_review")

@app.post("/api/rights-lab/import")
def rights_lab_import(payload:RightsLabImportIn,_authorized=Depends(require_api_access)):
    filename=Path(payload.filename).name
    if filename!=payload.filename:
        raise HTTPException(422,"CSV_FILENAME_INVALID")
    try:
        validate_csv_import(filename,payload.columns,payload.row_count,payload.file_sha256,payload.sample_rows)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    if payload.source_url!=payload.rights_evidence.source_url:
        raise HTTPException(422,"SOURCE_URL_EVIDENCE_MISMATCH")
    if get_rights_lab_dataset(payload.dataset_id):
        raise HTTPException(409,"RIGHTS_LAB_DATASET_ALREADY_IMPORTED")
    created=datetime.now(timezone.utc).isoformat()
    evidence=payload.rights_evidence.model_dump()
    evidence["file_sha256"]=payload.file_sha256.lower()
    evidence["evidence_timestamp"]=created
    item={"dataset_id":payload.dataset_id,"filename":filename,"row_count":payload.row_count,
          "columns":payload.columns,"source_url":payload.source_url,"file_sha256":payload.file_sha256.lower(),
          "hash_status":"browser_computed_unverified","sample_rows":payload.sample_rows,
          "rights_evidence":evidence,"created_at":created,"original_file_stored":False}
    try:
        save_rights_lab_dataset(item)
    except sqlite3.IntegrityError:
        raise HTTPException(409,"RIGHTS_LAB_DATASET_ALREADY_IMPORTED")
    save_audit_event("RIGHTS_LAB_DATASET_IMPORTED",{"dataset_id":item["dataset_id"],"file_sha256":item["file_sha256"],"sample_row_count":len(item["sample_rows"]),"original_file_stored":False},created)
    return {key:value for key,value in item.items() if key!="sample_rows"}

@app.get("/api/rights-lab/datasets")
def rights_lab_datasets():
    return [{key:value for key,value in item.items() if key!="sample_rows"} for item in list_rights_lab_datasets()]

@app.post("/api/rights-lab/datasets/{dataset_id}/evidence")
def rights_lab_update_evidence(dataset_id:str,payload:RightsEvidenceIn,_authorized=Depends(require_api_access)):
    item=get_rights_lab_dataset(dataset_id)
    if not item: raise HTTPException(404,"RIGHTS_LAB_DATASET_NOT_FOUND")
    evidence=payload.model_dump()
    if evidence.get("file_sha256") and evidence["file_sha256"].lower()!=item["file_sha256"].lower():
        raise HTTPException(422,"SIGNED_RIGHTS_EVIDENCE_FILE_HASH_MISMATCH")
    evidence["file_sha256"]=item["file_sha256"]
    evidence["evidence_timestamp"]=datetime.now(timezone.utc).isoformat()
    item["rights_evidence"]=evidence
    item["source_url"]=evidence["source_url"]
    update_rights_lab_dataset(item)
    save_audit_event("RIGHTS_LAB_EVIDENCE_UPDATED",{"dataset_id":dataset_id,"file_sha256":item["file_sha256"],"licence_evidence_status":evidence["licence_evidence_status"],"provenance_status":evidence["provenance_status"]},evidence["evidence_timestamp"])
    return {key:value for key,value in item.items() if key!="sample_rows"}

@app.post("/api/rights-lab/datasets/{dataset_id}/store-original")
async def rights_lab_store_original(dataset_id:str,request:Request,_authorized=Depends(require_api_access)):
    item=get_rights_lab_dataset(dataset_id)
    if not item: raise HTTPException(404,"RIGHTS_LAB_DATASET_NOT_FOUND")
    size=0; parts=[]
    async for chunk in request.stream():
        size+=len(chunk)
        if size>25*1024*1024: raise HTTPException(413,"ORIGINAL_CSV_EXCEEDS_25_MB_LIMIT")
        parts.append(chunk)
    content=b"".join(parts)
    actual_hash=hashlib.sha256(content).hexdigest()
    if actual_hash!=item["file_sha256"]:
        raise HTTPException(422,"ORIGINAL_CSV_SHA256_MISMATCH")
    try:
        decoded=content.decode("utf-8-sig")
        reader=csv.DictReader(io.StringIO(decoded,newline=""))
        headers=list(reader.fieldnames or [])
        if headers and headers[0].startswith("\ufeff"): headers[0]=headers[0].lstrip("\ufeff")
        reader.fieldnames=headers
        rows=list(reader)
    except (UnicodeDecodeError,csv.Error):
        raise HTTPException(422,"ORIGINAL_CSV_INVALID_UTF8_OR_FORMAT")
    if headers!=item["columns"] or len(rows)!=item["row_count"] or rows[:len(item["sample_rows"])]!=item["sample_rows"]:
        raise HTTPException(422,"ORIGINAL_CSV_CONTENT_DOES_NOT_MATCH_IMPORTED_SAMPLE")
    private_dir=DATA_DIR.parent/"private_data"
    private_dir.mkdir(parents=True,exist_ok=True)
    target=private_dir/f"{dataset_id}-{actual_hash}.csv"
    temporary=target.with_suffix(".csv.tmp")
    temporary.write_bytes(content)
    os.replace(temporary,target)
    item["hash_status"]="server_verified"
    item["original_file_stored"]=True
    item["original_file_size_bytes"]=size
    update_rights_lab_dataset(item)
    now=datetime.now(timezone.utc).isoformat()
    save_audit_event("RIGHTS_LAB_ORIGINAL_STORED",{"dataset_id":dataset_id,"file_sha256":actual_hash,"size_bytes":size,"storage":"backend/private_data (gitignored)"},now)
    return {"stored":True,"file_sha256":actual_hash,"size_bytes":size,"storage":"backend/private_data (gitignored)"}

@app.get("/api/rights-lab/benchmarks")
def rights_lab_benchmarks():
    return {"synthetic":True,"scope":"evidence-policy layer only; does not authorize registry or training-corpus access","policy_version":"bhashachain-ingestion-evidence-v1","cases":benchmark_cases()}

@app.post("/api/rights-lab/check")
def rights_lab_check(payload:RightsLabCheckIn,_authorized=Depends(require_api_access)):
    item=get_rights_lab_dataset(payload.dataset_id)
    if not item: raise HTTPException(404,"RIGHTS_LAB_DATASET_NOT_FOUND")
    request_data=payload.model_dump(exclude={"dataset_id"})
    evidence_result=evaluate_evidence(item["rights_evidence"],request_data)
    decision=evidence_result["decision"]
    reasons=list(evidence_result["reason_codes"])
    signature={"status":"not_checked","verified":False}
    chain={"status":"not_checked","verified":False,"mode":BLOCKCHAIN_MODE}
    registered=get_dataset(payload.dataset_id)
    if decision=="ALLOWED":
        if not registered:
            decision="NEEDS_REVIEW"; reasons.append("SIGNED_REGISTRY_RECORD_REQUIRED")
        elif registered.get("content_hash","").lower()!=item["file_sha256"].lower():
            decision="NEEDS_REVIEW"; reasons.append("REGISTERED_CONTENT_HASH_MISMATCH")
        elif registered.get("record_schema_version")!=3 or registered.get("rights_evidence")!=item["rights_evidence"]:
            decision="NEEDS_REVIEW"; reasons.append("SIGNED_RIGHTS_EVIDENCE_MISMATCH")
        else:
            policy_reasons,policy_evidence,chain=evaluate_request(registered,{"purpose":payload.purpose,"geography":payload.geography,"content_hash":item["file_sha256"]})
            signature=policy_evidence.get("signature_verification",signature)
            if signature.get("verified") is not True:
                decision="REJECTED"; reasons.extend(policy_reasons or ["INVALID_SIGNED_RIGHTS_RECORD"])
            else:
                explicit_blocks={"LICENCE_EXPIRED","LICENCE_REVOKED","LICENCE_REVOKED_ON_CHAIN","COMMERCIAL_TRAINING_NOT_PERMITTED","PURPOSE_NOT_PERMITTED","GEOGRAPHY_NOT_PERMITTED","HASH_MISMATCH","INVALID_LICENCE_VERSION","DERIVATIVES_NOT_PERMITTED","REDISTRIBUTION_NOT_PERMITTED","ONCHAIN_POLICY_MISMATCH"}
                applicable=[reason for reason in policy_reasons if reason in explicit_blocks]
                if applicable:
                    decision="REJECTED"; reasons.extend(applicable)
                elif policy_reasons or chain.get("verified") is not True:
                    decision="NEEDS_REVIEW"; reasons.extend(policy_reasons or ["ONCHAIN_REGISTRY_VERIFICATION_REQUIRED"])
    trace_id=str(uuid.uuid4()); decision_id=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat()
    result={"decision_id":decision_id,"trace_id":trace_id,"dataset_id":payload.dataset_id,
            "file_sha256":item["file_sha256"],"intended_use":payload.purpose,"geography":payload.geography,
            "attribution_provided":payload.attribution_provided,"will_share_adapted_work":payload.will_share_adapted_work,
            "share_alike_acknowledged":payload.share_alike_acknowledged,
            "decision":decision,"reason_codes":sorted(set(reasons)),"policy_version":"bhashachain-ingestion-evidence-v1",
            "evaluated_at":now,"licence_evidence_status":item["rights_evidence"]["licence_evidence_status"],
            "provenance_status":item["rights_evidence"]["provenance_status"],"signature_verification":signature,
            "blockchain_verification":chain,"training_eligible":decision=="ALLOWED" and signature.get("verified") is True and chain.get("verified") is True,
            "evidence_layer_result":evidence_result["decision"]}
    save_rights_lab_decision(result)
    save_audit_event("RIGHTS_LAB_INGESTION_DECISION",result,now,decision_id,trace_id=trace_id)
    return result

@app.get("/api/rights-lab/history")
def rights_lab_history(): return list_rights_lab_decisions()

@app.get("/api/rights-lab/accepted-corpus")
def rights_lab_accepted_corpus(_authorized=Depends(require_api_access)):
    rows=[]
    for decision in verified_lab_decisions():
        item=get_rights_lab_dataset(decision["dataset_id"])
        if item:
            rows.append({"dataset_id":decision["dataset_id"],"file_sha256":decision["file_sha256"],
                         "decision_id":decision["decision_id"],"sample_rows":item["sample_rows"]})
    return {"count":len(rows),"entries":rows,"requires_verified_signature_and_chain":True}

@app.get("/api/audit")
def audit(): return list_decisions()

@app.get("/api/audit/{decision_id}")
def audit_detail(decision_id:str):
    d=get_decision(decision_id)
    if not d: raise HTTPException(404,"DECISION_NOT_FOUND")
    return d
