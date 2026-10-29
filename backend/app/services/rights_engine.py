from datetime import datetime, timezone

from .signature_service import verify_dataset_details

REQUIRED = ("dataset_id", "content_hash", "language", "licence_version", "issuer", "purposes", "regions", "derivatives_allowed", "redistribution_allowed", "expires_at", "licensing_cost", "active", "signature")
V2_REQUIRED = ("record_id", "record_schema_version", "record_version", "issued_at", "updated_at", "issuer_key_id", "signature_algorithm", "revocation_status")
POLICY_VERSION = "bhashachain-rights-v2"


def _utc(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def evaluate(dataset, request, service_available=True):
    evidence = {"policy_version": POLICY_VERSION, "signature_verification": {"status": "not_checked", "verified": False}, "rights_record_version": None}
    if dataset is None:
        return ["UNKNOWN_DATASET"], evidence
    if not service_available:
        return ["LICENCE_VERIFICATION_UNAVAILABLE"], evidence
    missing = [key for key in REQUIRED if key not in dataset or dataset[key] is None]
    schema = dataset.get("record_schema_version", 1)
    if schema == 2:
        missing.extend(key for key in V2_REQUIRED if key not in dataset or dataset[key] is None)
    if missing:
        return ["MISSING_LICENCE_FIELDS"], evidence
    evidence["rights_record_version"] = dataset.get("record_version", 1)
    signature = verify_dataset_details(dataset)
    evidence["signature_verification"] = {"status": "valid" if signature.get("valid") else "invalid", "verified": bool(signature.get("valid")), "trusted_signer": bool(signature.get("trusted_signer")), "key_id": signature.get("key_id"), "algorithm": signature.get("algorithm"), "identity_scope": signature.get("identity_scope")}
    if signature.get("reason") == "UNAUTHORIZED_ISSUER":
        return ["UNAUTHORIZED_ISSUER"], evidence
    if not signature.get("valid"):
        return ["INVALID_SIGNATURE"], evidence
    if schema not in (1, 2):
        return ["UNSUPPORTED_RIGHTS_RECORD_VERSION"], evidence
    if request.get("rights_record_version") is not None and request["rights_record_version"] != dataset.get("record_version", 1):
        return ["STALE_RIGHTS_RECORD"], evidence
    if dataset.get("active") is False or dataset.get("revocation_status") == "revoked":
        return ["LICENCE_REVOKED"], evidence
    try:
        expiry = _utc(dataset["expires_at"])
        if expiry <= datetime.now(timezone.utc):
            return ["LICENCE_EXPIRED"], evidence
        issued = _utc(dataset["issued_at"]) if schema == 2 else None
        if issued is not None and issued >= expiry:
            return ["MISSING_LICENCE_FIELDS"], evidence
        if schema == 2:
            updated = _utc(dataset["updated_at"])
            if updated < issued or int(dataset["record_version"]) < 1:
                return ["STALE_RIGHTS_RECORD"], evidence
    except (ValueError, TypeError, AttributeError):
        return ["MISSING_LICENCE_FIELDS"], evidence
    reasons = []
    purpose = request.get("purpose", "")
    if purpose not in dataset["purposes"]:
        reasons.append("COMMERCIAL_TRAINING_NOT_PERMITTED" if purpose == "commercial_training" else "PURPOSE_NOT_PERMITTED")
    if request.get("geography") not in dataset["regions"] and "GLOBAL" not in dataset["regions"]:
        reasons.append("GEOGRAPHY_NOT_PERMITTED")
    if request.get("derivatives", False) and not dataset.get("derivatives_allowed"):
        reasons.append("DERIVATIVES_NOT_PERMITTED")
    if request.get("redistribution", False) and not dataset.get("redistribution_allowed"):
        reasons.append("REDISTRIBUTION_NOT_PERMITTED")
    if request.get("content_hash") and request["content_hash"].lower() != dataset["content_hash"].lower():
        reasons.append("HASH_MISMATCH")
    if request.get("licence_version") and request["licence_version"] != dataset["licence_version"]:
        reasons.append("INVALID_LICENCE_VERSION")
    return reasons, evidence


def check(dataset, request, service_available=True):
    return evaluate(dataset, request, service_available)[0]
