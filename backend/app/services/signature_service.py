"""Canonical Ed25519 rights records with v1 read compatibility."""
import base64
import binascii
import hashlib
import json
import uuid
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..config import LOCAL_SIGNER_KEY_ID, SIGNING_SECRET, TRUSTED_ISSUER_PUBLIC_KEYS_JSON

V1_KEYS = ("dataset_id", "content_hash", "language", "licence_version", "issuer", "purposes", "regions", "derivatives_allowed", "redistribution_allowed", "expires_at", "licensing_cost", "active")
V2_KEYS = V1_KEYS + ("record_id", "record_schema_version", "record_version", "issued_at", "updated_at", "issuer_key_id", "signature_algorithm", "revocation_status", "revoked_at")
V3_KEYS = V2_KEYS + ("rights_evidence",)


def _private_key():
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(SIGNING_SECRET.encode()).digest())


def _b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value):
    return base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))


def local_public_key_b64():
    raw = _private_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64(raw)


def _trusted_keys():
    try:
        configured = json.loads(TRUSTED_ISSUER_PUBLIC_KEYS_JSON or "{}")
        if not isinstance(configured, dict):
            return {}
        return {str(key_id): Ed25519PublicKey.from_public_bytes(_decode(str(value))) for key_id, value in configured.items()}
    except (ValueError, TypeError, binascii.Error):
        return {}


def canonical_payload(d):
    schema = d.get("record_schema_version", 1)
    if schema == 1:
        keys = V1_KEYS
    elif schema == 2:
        keys = V2_KEYS
    elif schema == 3:
        keys = V3_KEYS
    else:
        raise ValueError("Unsupported rights-record schema version")
    return json.dumps({key: d.get(key) for key in keys}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sign_dataset(d):
    """Attach a v2 service-signed record while preserving caller metadata."""
    now = datetime.now(timezone.utc).isoformat()
    d.setdefault("record_id", str(uuid.uuid4()))
    d.setdefault("record_schema_version", 3 if "rights_evidence" in d else 2)
    d.setdefault("record_version", 1)
    d.setdefault("issued_at", d.get("created_at", now))
    d.setdefault("updated_at", now)
    d.setdefault("issuer_key_id", LOCAL_SIGNER_KEY_ID)
    d.setdefault("signature_algorithm", "Ed25519")
    d.setdefault("revocation_status", "revoked" if d.get("active") is False else "active")
    d.setdefault("revoked_at", None)
    d["signature"] = _b64(_private_key().sign(canonical_payload(d)))
    return d["signature"]


def verify_dataset_details(d):
    try:
        schema = d.get("record_schema_version", 1)
        key_id = d.get("issuer_key_id", LOCAL_SIGNER_KEY_ID)
        algorithm = d.get("signature_algorithm", "Ed25519")
        if algorithm != "Ed25519":
            return {"valid": False, "trusted_signer": False, "reason": "UNSUPPORTED_SIGNATURE_ALGORITHM", "key_id": key_id, "algorithm": algorithm}
        keys = _trusted_keys()
        if key_id == LOCAL_SIGNER_KEY_ID:
            public_key = _private_key().public_key()
            trusted = True
        else:
            public_key = keys.get(key_id)
            trusted = public_key is not None
        if public_key is None:
            return {"valid": False, "trusted_signer": False, "reason": "UNAUTHORIZED_ISSUER", "key_id": key_id, "algorithm": algorithm}
        public_key.verify(_decode(d["signature"]), canonical_payload(d))
        return {"valid": True, "trusted_signer": trusted, "key_id": key_id, "algorithm": algorithm,
                "record_id": d.get("record_id"), "record_schema_version": schema,
                "record_version": d.get("record_version", 1),
                "identity_scope": "local_service_signature" if key_id == LOCAL_SIGNER_KEY_ID else "trusted_issuer_key"}
    except (KeyError, TypeError, ValueError, binascii.Error, InvalidSignature):
        return {"valid": False, "trusted_signer": False, "reason": "INVALID_SIGNATURE",
                "key_id": d.get("issuer_key_id") if isinstance(d, dict) else None, "algorithm": "Ed25519"}


def verify_dataset(d):
    return bool(verify_dataset_details(d).get("valid"))
