import hashlib
import json
import os
from datetime import datetime, timezone

from ..config import MANIFEST_DIR
from ..db import list_decisions, list_rights_lab_decisions, get_rights_lab_dataset, get_dataset
from .rights_engine import evaluate
from .blockchain_service import verify_dataset

SCHEMA_VERSION = 2


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _entry(row):
    signature = row.get("signature_verification", {})
    chain = row.get("blockchain_verification", {})
    return {
        "decision_id": row["decision_id"], "trace_id": row.get("trace_id"), "dataset_id": row["dataset_id"],
        "content_hash": row.get("content_hash"), "decision": row["decision"],
        "purpose": row.get("purpose"), "geography": row.get("geography"),
        "reason_codes": row.get("reason_codes", row.get("reasons", [])),
        "policy_version": row.get("policy_version"), "rights_record_version": row.get("rights_record_version"),
        "signature_verification": signature, "blockchain_verification": chain,
        "transaction_ref": row.get("transaction_ref"), "evaluated_at": row.get("evaluated_at", row.get("timestamp")),
        "optimization_run_id": row.get("optimization_run_id"),
        "file_sha256": row.get("file_sha256"), "intended_use": row.get("intended_use"),
        "decision": row.get("decision"), "training_eligible": row.get("training_eligible", False),
    }


def _build(name, decisions):
    if name == "accepted":
        selected = (row for row in decisions if row.get("decision") == "ACCEPT" or
                    (row.get("decision") == "ALLOWED" and row.get("training_eligible") is True and
                     row.get("signature_verification", {}).get("verified") is True and
                     row.get("blockchain_verification", {}).get("verified") is True))
    elif name == "rejected":
        selected = (row for row in decisions if row.get("decision") in {"REJECT", "REJECTED"})
    else:
        selected = (row for row in decisions if row.get("decision") == "NEEDS_REVIEW")
    entries = sorted((_entry(row) for row in selected), key=lambda x: (x.get("evaluated_at") or "", x["decision_id"]))
    content = {"manifest": name, "schema_version": SCHEMA_VERSION, "entries": entries}
    digest = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
    return {**content, "manifest_id": digest, "manifest_hash": digest,
            "created_at": datetime.now(timezone.utc).isoformat(), "count": len(entries)}


def verified_lab_decisions():
    """Return only still-current lab approvals with valid signature and live chain state."""
    verified=[]
    for decision in list_rights_lab_decisions():
        if decision.get("decision")!="ALLOWED" or decision.get("training_eligible") is not True:
            continue
        item=get_rights_lab_dataset(decision["dataset_id"])
        record=get_dataset(decision["dataset_id"])
        if not item or not record or record.get("active") is False or record.get("revocation_status")=="revoked":
            continue
        if (record.get("record_schema_version")!=3 or
                record.get("rights_evidence")!=item.get("rights_evidence") or
                record.get("content_hash","").lower()!=decision.get("file_sha256","").lower()):
            continue
        request={"purpose":decision.get("intended_use"),"geography":decision.get("geography"),
                 "content_hash":decision.get("file_sha256"),
                 "derivatives":decision.get("will_share_adapted_work") is True}
        reasons,evidence=evaluate(record,request)
        if reasons or evidence.get("signature_verification",{}).get("verified") is not True:
            continue
        chain=verify_dataset(record["dataset_id"],record["content_hash"],purpose=request["purpose"],
            geography=request["geography"],derivatives=request["derivatives"],
            expected_version=record.get("licence_version"),expected_expiry=record.get("expires_at"))
        if chain.get("verified") is not True or chain.get("revoked") or chain.get("policy_permitted") is False:
            continue
        verified.append({**decision,"signature_verification":evidence["signature_verification"],
                         "blockchain_verification":chain,"training_eligible":True})
    return verified


def generate_manifests():
    lab_decisions=list_rights_lab_decisions()
    eligible=verified_lab_decisions()
    decisions = list_decisions() + [row for row in lab_decisions if row.get("decision") in {"REJECTED","NEEDS_REVIEW"}] + eligible
    manifests = {name: _build(name, decisions) for name in ("accepted", "rejected", "needs_review")}
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    for name, result in manifests.items():
        target = MANIFEST_DIR / f"{name}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    return manifests


def manifests():
    result = generate_manifests()
    return result["accepted"]["entries"], result["rejected"]["entries"]


def manifest_details(name):
    if name not in ("accepted", "rejected", "needs_review"):
        raise ValueError("Unknown manifest")
    return generate_manifests()[name]
