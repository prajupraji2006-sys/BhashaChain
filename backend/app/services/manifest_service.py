import hashlib
import json
import os
from datetime import datetime, timezone

from ..config import MANIFEST_DIR
from ..db import list_decisions

SCHEMA_VERSION = 1


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
    }


def _build(name, decisions):
    decision_state = "ACCEPT" if name == "accepted" else "REJECT"
    entries = sorted((_entry(row) for row in decisions if row["decision"] == decision_state), key=lambda x: (x.get("evaluated_at") or "", x["decision_id"]))
    content = {"manifest": name, "schema_version": SCHEMA_VERSION, "entries": entries}
    digest = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
    return {**content, "manifest_id": digest, "manifest_hash": digest,
            "created_at": datetime.now(timezone.utc).isoformat(), "count": len(entries)}


def generate_manifests():
    decisions = list_decisions()
    manifests = {name: _build(name, decisions) for name in ("accepted", "rejected")}
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
    if name not in ("accepted", "rejected"):
        raise ValueError("Unknown manifest")
    return generate_manifests()[name]
