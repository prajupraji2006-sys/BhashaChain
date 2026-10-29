"""Evidence-layer policy for the Dataset Rights Lab.

This is a conservative decision aid, not a legal determination. Passing this
layer alone never makes a dataset training-ready; signed registry and chain
verification are required separately.
"""
from datetime import datetime, timezone

POLICY_VERSION = "bhashachain-ingestion-evidence-v1"
EVIDENCE_STATUSES = {"VERIFIED", "UNVERIFIED", "UNKNOWN", "NEEDS_REVIEW"}
CSV_REQUIRED_COLUMNS = {"headline", "label"}


def validate_csv_import(filename, columns, row_count, file_sha256, sample_rows):
    if not filename.lower().endswith(".csv") or filename in (".", ".."):
        raise ValueError("CSV_FILENAME_REQUIRED")
    if row_count < 20 or not 20 <= len(sample_rows) <= 50 or len(sample_rows) > row_count:
        raise ValueError("SAMPLE_SIZE_MUST_BE_20_TO_50")
    normalized = {str(column).strip().lower() for column in columns}
    if not CSV_REQUIRED_COLUMNS.issubset(normalized):
        raise ValueError("CSV_SCHEMA_REQUIRES_HEADLINE_AND_LABEL")
    if len(columns) > 128 or any(not str(column).strip() for column in columns):
        raise ValueError("CSV_COLUMNS_INVALID")
    if len(set(columns)) != len(columns):
        raise ValueError("CSV_COLUMNS_DUPLICATE")
    if len(file_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in file_sha256):
        raise ValueError("FILE_SHA256_INVALID")
    expected = set(columns)
    if any(not isinstance(row, dict) or set(row) != expected for row in sample_rows):
        raise ValueError("CSV_SAMPLE_ROW_SCHEMA_MISMATCH")
    return True


def _parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def evaluate_evidence(evidence, request, now=None):
    """Evaluate supplied evidence without claiming it is signed or on-chain."""
    now = now or datetime.now(timezone.utc)
    reject, review = [], []

    revocation = (evidence.get("revocation_status") or "UNKNOWN").upper()
    if revocation == "REVOKED":
        reject.append("LICENCE_REVOKED")
    elif revocation != "ACTIVE":
        review.append("REVOCATION_STATUS_UNKNOWN")

    expiry = evidence.get("expiry_date")
    if expiry:
        try:
            if _parse_time(expiry) <= now:
                reject.append("LICENCE_EXPIRED")
        except (ValueError, TypeError, AttributeError):
            review.append("EXPIRY_DATE_INVALID")
        if evidence.get("expiry_evidence_status") != "VERIFIED":
            review.append("EXPIRY_EVIDENCE_NOT_VERIFIED")
    elif evidence.get("expiry_evidence_status") != "VERIFIED":
        review.append("EXPIRY_EVIDENCE_MISSING")

    licence_status = (evidence.get("licence_evidence_status") or "UNKNOWN").upper()
    provenance_status = (evidence.get("provenance_status") or "UNKNOWN").upper()
    if licence_status == "INVALID":
        reject.append("LICENCE_EVIDENCE_INVALID")
    elif licence_status != "VERIFIED":
        review.append("LICENCE_EVIDENCE_NOT_VERIFIED")
    if provenance_status != "VERIFIED":
        review.append("PROVENANCE_NOT_VERIFIED")

    required_text = ("dataset_name", "language", "modality", "source_url", "source_publisher",
                     "licence_name", "licence_url", "intended_purpose", "evidence_notes", "evidence_timestamp")
    if any(not str(evidence.get(key) or "").strip() for key in required_text):
        review.append("REQUIRED_EVIDENCE_FIELDS_MISSING")
    try:
        _parse_time(evidence.get("evidence_timestamp", ""))
    except (ValueError, TypeError, AttributeError):
        review.append("EVIDENCE_TIMESTAMP_INVALID")

    purpose = request.get("purpose") or evidence.get("intended_purpose")
    if purpose == "commercial_training":
        licence_code = str(evidence.get("licence_name") or "").lower().replace("_", "-")
        if "noncommercial" in licence_code or "by-nc" in licence_code or "-nc-" in licence_code:
            reject.append("LICENCE_NONCOMMERCIAL_RESTRICTION")
        permitted = evidence.get("commercial_training")
        if permitted is False:
            reject.append("COMMERCIAL_TRAINING_PROHIBITED")
        elif permitted is not True:
            review.append("COMMERCIAL_TRAINING_PERMISSION_UNKNOWN")
    elif purpose != evidence.get("intended_purpose"):
        review.append("PURPOSE_NOT_REVIEWED")

    if evidence.get("attribution_required") is None:
        review.append("ATTRIBUTION_REQUIREMENT_UNKNOWN")
    elif evidence.get("attribution_required") and request.get("attribution_provided") is not True:
        if request.get("attribution_provided") is False:
            reject.append("ATTRIBUTION_REQUIREMENT_NOT_MET")
        else:
            review.append("ATTRIBUTION_NOT_CONFIRMED")

    licence_name = str(evidence.get("licence_name") or "").lower()
    share_alike = "share alike" in licence_name or "by-sa" in licence_name
    conditions = str(evidence.get("share_alike_conditions") or "").strip()
    if share_alike and not conditions:
        review.append("SHARE_ALIKE_CONDITIONS_MISSING")
    if share_alike:
        sharing_plan = request.get("will_share_adapted_work")
        if sharing_plan is None:
            review.append("ADAPTATION_SHARING_PLAN_UNKNOWN")
        elif sharing_plan is True:
            acknowledged = request.get("share_alike_acknowledged")
            if acknowledged is False:
                reject.append("SHARE_ALIKE_REQUIREMENT_NOT_MET")
            elif acknowledged is not True:
                review.append("SHARE_ALIKE_NOT_CONFIRMED")

    if reject:
        status = "REJECTED"
        reasons = sorted(set(reject + review))
    elif review:
        status = "NEEDS_REVIEW"
        reasons = sorted(set(review))
    else:
        status = "ALLOWED"
        reasons = []
    return {"decision": status, "reason_codes": reasons, "policy_version": POLICY_VERSION,
            "evaluated_at": now.isoformat(), "evidence_layer_only": True,
            "legal_authority": False}


def benchmark_cases(now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    common = {"dataset_name": "Synthetic benchmark fixture", "language": "kn", "modality": "text",
              "source_url": "https://example.invalid/synthetic-fixture", "source_publisher": "Synthetic test publisher",
              "licence_name": "CC BY-SA 4.0", "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
              "licence_evidence_status": "VERIFIED", "provenance_status": "VERIFIED",
              "intended_purpose": "commercial_training", "commercial_training": True,
              "attribution_required": True, "redistribution_conditions": "Synthetic fixture terms.",
              "share_alike_conditions": "If sharing adapted material, use the same or a compatible licence.",
              "expiry_date": None, "expiry_evidence_status": "VERIFIED", "revocation_status": "ACTIVE",
              "evidence_notes": "Synthetic test fixture; not a real dataset or licence review.", "evidence_timestamp": stamp}
    cases = [
        ("A", "Synthetic complete permitted-use evidence", common.copy(),
         {"purpose": "commercial_training", "attribution_provided": True, "will_share_adapted_work": False}, "ALLOWED"),
        ("B", "Synthetic incomplete source rights", {**common, "licence_evidence_status": "UNVERIFIED", "provenance_status": "NEEDS_REVIEW"},
         {"purpose": "commercial_training", "attribution_provided": True, "will_share_adapted_work": False}, "NEEDS_REVIEW"),
        ("C", "Synthetic explicit commercial restriction", {**common, "commercial_training": False},
         {"purpose": "commercial_training", "attribution_provided": True, "will_share_adapted_work": False}, "REJECTED"),
        ("D", "Synthetic expired licence", {**common, "expiry_date": "2020-01-01T00:00:00Z"},
         {"purpose": "commercial_training", "attribution_provided": True, "will_share_adapted_work": False}, "REJECTED"),
        ("E", "Synthetic revoked licence", {**common, "revocation_status": "REVOKED"},
         {"purpose": "commercial_training", "attribution_provided": True, "will_share_adapted_work": False}, "REJECTED"),
    ]
    return [{"case_id": case_id, "name": name, "synthetic": True, "expected_decision": expected,
             "result": evaluate_evidence(evidence, request, now)}
            for case_id, name, evidence, request, expected in cases]
