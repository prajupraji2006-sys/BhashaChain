"""Optional Web3 adapter for the local RightsLedger contract.

No transaction is reported unless it has been signed, mined, and checked against
the contract state and expected event. All chain failures are returned explicitly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from ..config import BLOCKCHAIN_CHAIN_ID, BLOCKCHAIN_MODE, BLOCKCHAIN_PRIVATE_KEY, BLOCKCHAIN_RPC_URL, BLOCKCHAIN_SENDER_ADDRESS, DATA_DIR, RIGHTS_LEDGER_ADDRESS


def _web3():
    if not BLOCKCHAIN_RPC_URL or not RIGHTS_LEDGER_ADDRESS:
        return None, "BLOCKCHAIN_RPC_URL and RIGHTS_LEDGER_ADDRESS are required"
    try:
        from web3 import Web3
    except ImportError:
        return None, "web3.py is not installed"
    w3 = Web3(Web3.HTTPProvider(BLOCKCHAIN_RPC_URL, request_kwargs={"timeout": 5}))
    try:
        if not w3.is_connected():
            return None, "Configured RPC endpoint is unavailable"
        if not w3.is_address(RIGHTS_LEDGER_ADDRESS):
            return None, "RIGHTS_LEDGER_ADDRESS is invalid"
        if not w3.eth.get_code(Web3.to_checksum_address(RIGHTS_LEDGER_ADDRESS)):
            return None, "No contract code found at RIGHTS_LEDGER_ADDRESS"
        if BLOCKCHAIN_CHAIN_ID and w3.eth.chain_id != int(BLOCKCHAIN_CHAIN_ID):
            return None, f"Connected chain ID {w3.eth.chain_id} does not match configured chain ID"
        abi_path = DATA_DIR / "rights_ledger_abi.json"
        abi = json.loads(abi_path.read_text(encoding="utf-8"))
        contract = w3.eth.contract(address=Web3.to_checksum_address(RIGHTS_LEDGER_ADDRESS), abi=abi)
        return (w3, contract), None
    except Exception as exc:
        return None, f"RPC or contract check failed: {type(exc).__name__}"


def status():
    connection, error = _web3()
    if error:
        return {"status": "unavailable" if BLOCKCHAIN_RPC_URL else "not_configured", "verified": False, "mode": BLOCKCHAIN_MODE, "error": error}
    w3, _ = connection
    return {"status": "connected", "verified": True, "mode": BLOCKCHAIN_MODE, "chain_id": w3.eth.chain_id,
            "contract_address": RIGHTS_LEDGER_ADDRESS,
            "transaction_signer": "configured" if BLOCKCHAIN_PRIVATE_KEY or BLOCKCHAIN_SENDER_ADDRESS else "not_configured"}


def _sign_and_send(w3, function):
    if not BLOCKCHAIN_PRIVATE_KEY and not BLOCKCHAIN_SENDER_ADDRESS:
        return None, "Configure BLOCKCHAIN_SENDER_ADDRESS for an unlocked local account or BLOCKCHAIN_PRIVATE_KEY; no transaction was submitted"
    try:
        if BLOCKCHAIN_PRIVATE_KEY:
            account = w3.eth.account.from_key(BLOCKCHAIN_PRIVATE_KEY)
            tx = function.build_transaction({"from": account.address,"nonce": w3.eth.get_transaction_count(account.address),"chainId": w3.eth.chain_id,"gas": 1_000_000,"gasPrice": w3.eth.gas_price})
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        else:
            from web3 import Web3
            sender = Web3.to_checksum_address(BLOCKCHAIN_SENDER_ADDRESS)
            tx = function.build_transaction({"from": sender,"chainId": w3.eth.chain_id,"gas": 1_000_000,"gasPrice": w3.eth.gas_price})
            # Local Hardhat nodes expose unlocked development accounts. No key is
            # copied into Python or sent from the browser in this workflow.
            tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        if receipt.status != 1:
            return {"transaction_hash": tx_hash.hex(), "status": "reverted", "receipt_status": receipt.status, "chain_id": w3.eth.chain_id, "block_number": receipt.blockNumber, "gas_used": receipt.gasUsed}, "Transaction reverted"
        return {"transaction_hash": tx_hash.hex(), "status": "confirmed", "receipt_status": receipt.status, "chain_id": w3.eth.chain_id, "block_number": receipt.blockNumber, "gas_used": receipt.gasUsed, "receipt": receipt}, None
    except Exception as exc:
        # Do not include exception text: providers may echo request configuration.
        return None, f"Transaction failed: {type(exc).__name__}"


def _bytes32(hex_string):
    value = bytes.fromhex(hex_string.removeprefix("0x"))
    return value.rjust(32, b"\0")


def _version_number(value):
    # Preserve common semantic versions as an ordered uint32 (e.g. 2.1 -> 201).
    parts = str(value).split(".")
    if not all(p.isdigit() for p in parts) or len(parts) > 3:
        raise ValueError("Licence version must contain one to three numeric components")
    number = 0
    for part in parts:
        number = number * 1000 + int(part)
    if number <= 0 or number >= 2**32:
        raise ValueError("Licence version is outside the supported range")
    return number


version_number = _version_number


def _expiry(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _list_hashes(values):
    from web3 import Web3
    return [Web3.keccak(text=value) for value in values]


def register(dataset):
    connection, error = _web3()
    if error:
        return {"status": "not_submitted", "verified": False, "error": error}
    w3, contract = connection
    try:
        dataset_id = w3.keccak(text=dataset["dataset_id"])
        content_hash = _bytes32(dataset["content_hash"])
        version = _version_number(dataset["licence_version"])
        call = contract.functions.register(
            dataset_id, content_hash, version, _expiry(dataset["expires_at"]),
            bool(dataset["derivatives_allowed"]), bool(dataset["redistribution_allowed"]),
            _list_hashes(dataset["purposes"]), _list_hashes(dataset["regions"]),
        )
        result, error = _sign_and_send(w3, call)
        if error:
            return {"status": "failed" if result else "not_submitted", "verified": False, "error": error, **(result or {})}
        receipt = result.pop("receipt")
        events = contract.events.LicenceRegistered().process_receipt(receipt)
        state = contract.functions.getLicence(dataset_id).call()
        hash_matches = bytes(state[0]) == content_hash
        from web3 import Web3
        expected_issuer = (w3.eth.account.from_key(BLOCKCHAIN_PRIVATE_KEY).address
                           if BLOCKCHAIN_PRIVATE_KEY else Web3.to_checksum_address(BLOCKCHAIN_SENDER_ADDRESS))
        issuer_matches = Web3.to_checksum_address(state[2]) == Web3.to_checksum_address(expected_issuer)
        event_matches = any(bytes(event["args"]["datasetId"]) == dataset_id and bytes(event["args"]["contentHash"]) == content_hash for event in events)
        verified = bool(state[7] and not state[6] and state[1] == version and hash_matches and issuer_matches and event_matches)
        return {**result, "status": "confirmed" if verified else "unverified", "verified": verified,
                "dataset_id_hash": "0x" + dataset_id.hex(), "content_hash_match": hash_matches,
                "issuer_match": issuer_matches, "event_verified": event_matches, "version": state[1], "registered_at": state[8]}
    except Exception as exc:
        return {"status": "failed", "verified": False, "error": f"Registration verification failed: {type(exc).__name__}"}


def revoke(dataset_id_value):
    connection, error = _web3()
    if error:
        return {"status": "not_submitted", "verified": False, "error": error}
    w3, contract = connection
    try:
        dataset_id = w3.keccak(text=dataset_id_value)
        result, error = _sign_and_send(w3, contract.functions.revoke(dataset_id))
        if error:
            return {"status": "failed" if result else "not_submitted", "verified": False, "error": error, **(result or {})}
        receipt = result.pop("receipt")
        events = contract.events.LicenceRevoked().process_receipt(receipt)
        state = contract.functions.getLicence(dataset_id).call()
        event_matches = any(bytes(event["args"]["datasetId"]) == dataset_id for event in events)
        verified = bool(state[6] and event_matches)
        return {**result, "status": "confirmed" if verified else "unverified", "verified": verified, "event_verified": event_matches}
    except Exception as exc:
        return {"status": "failed", "verified": False, "error": f"Revocation failed: {type(exc).__name__}"}


def update(dataset_id_value, dataset):
    connection, error = _web3()
    if error:
        return {"status": "not_submitted", "verified": False, "error": error}
    w3, contract = connection
    try:
        dataset_id = w3.keccak(text=dataset_id_value)
        content_hash = _bytes32(dataset["content_hash"])
        version = _version_number(dataset["licence_version"])
        call = contract.functions.update(
            dataset_id, content_hash, version, _expiry(dataset["expires_at"]),
            bool(dataset["derivatives_allowed"]), bool(dataset["redistribution_allowed"]),
            _list_hashes(dataset["purposes"]), _list_hashes(dataset["regions"]),
        )
        result, error = _sign_and_send(w3, call)
        if error:
            return {"status": "failed" if result else "not_submitted", "verified": False, "error": error, **(result or {})}
        receipt = result.pop("receipt")
        events = contract.events.LicenceUpdated().process_receipt(receipt)
        state = contract.functions.getLicence(dataset_id).call()
        hash_matches = bytes(state[0]) == content_hash
        event_matches = any(bytes(event["args"]["datasetId"]) == dataset_id and event["args"]["version"] == version for event in events)
        verified = bool(state[7] and not state[6] and state[1] == version and hash_matches and event_matches)
        return {**result, "status": "confirmed" if verified else "unverified", "verified": verified,
                "content_hash_match": hash_matches, "event_verified": event_matches, "version": state[1]}
    except Exception as exc:
        return {"status": "failed", "verified": False, "error": f"Licence update failed: {type(exc).__name__}"}


def verify_dataset(dataset_id_value, metadata_hash, purpose=None, geography=None, derivatives=False,
                   redistribution=False, expected_version=None, expected_expiry=None):
    connection, error = _web3()
    if error:
        return {"status": "unavailable", "verified": False, "error": error}
    w3, contract = connection
    try:
        record = contract.functions.getLicence(w3.keccak(text=dataset_id_value)).call()
        expected_hash = _bytes32(metadata_hash)
        exists = bool(record[7])
        hash_matches = exists and bytes(record[0]) == expected_hash
        version_matches = expected_version is None or (exists and record[1] == _version_number(expected_version))
        expiry_matches = expected_expiry is None or (exists and record[3] == _expiry(expected_expiry))
        policy_permitted = None
        if exists and purpose is not None and geography is not None:
            policy_permitted = contract.functions.permits(w3.keccak(text=dataset_id_value), w3.keccak(text=purpose), w3.keccak(text=geography), derivatives, redistribution).call()
        verified = bool(exists and hash_matches and version_matches and expiry_matches)
        return {"status": "missing" if not exists else "verified" if verified else "mismatch", "verified": verified,
                "exists": exists, "content_hash_match": hash_matches, "version": record[1],
                "version_match": version_matches, "expiry_match": expiry_matches,
                "policy_permitted": policy_permitted, "issuer_address": record[2],
                "expires_at": record[3], "revoked": record[6], "registered_at": record[8],
                "chain_id": w3.eth.chain_id, "contract_address": RIGHTS_LEDGER_ADDRESS}
    except Exception as exc:
        return {"status": "unavailable", "verified": False, "error": f"Read verification failed: {type(exc).__name__}"}


def registry_lookup(dataset_id_value):
    connection, error = _web3()
    if error:
        return {"status": "unavailable", "verified": False, "error": error}
    w3, contract = connection
    try:
        record = contract.functions.getLicence(w3.keccak(text=dataset_id_value)).call()
        if not record[7]:
            return {"status": "missing", "verified": False, "exists": False, "chain_id": w3.eth.chain_id, "contract_address": RIGHTS_LEDGER_ADDRESS}
        return {"status": "found", "verified": True, "exists": True,
                "content_hash": "0x" + bytes(record[0]).hex(), "version": record[1],
                "issuer_address": record[2], "expires_at": record[3],
                "derivatives_allowed": record[4], "redistribution_allowed": record[5],
                "revoked": record[6], "registered_at": record[8],
                "chain_id": w3.eth.chain_id, "contract_address": RIGHTS_LEDGER_ADDRESS}
    except Exception as exc:
        return {"status": "unavailable", "verified": False, "error": f"Registry read failed: {type(exc).__name__}"}


def transaction_status(transaction_hash):
    connection, error = _web3()
    if error:
        return {"status": "unavailable", "error": error}
    w3, _ = connection
    try:
        receipt = w3.eth.get_transaction_receipt(transaction_hash)
        return {"status": "confirmed" if receipt.status == 1 else "reverted",
                "transaction_hash": receipt.transactionHash.hex(), "receipt_status": receipt.status,
                "block_number": receipt.blockNumber, "gas_used": receipt.gasUsed,
                "chain_id": w3.eth.chain_id, "contract_address": receipt.to}
    except Exception as exc:
        if type(exc).__name__ == "TransactionNotFound":
            return {"status": "pending_or_unknown", "transaction_hash": transaction_hash, "chain_id": w3.eth.chain_id}
        return {"status": "unavailable", "error": f"Receipt lookup failed: {type(exc).__name__}"}


def registry_events(dataset_id_value, from_block=0):
    connection, error = _web3()
    if error:
        return {"status": "unavailable", "events": [], "error": error}
    w3, contract = connection
    try:
        dataset_id = w3.keccak(text=dataset_id_value)
        found = []
        for name in ("LicenceRegistered", "LicenceUpdated", "LicenceRevoked"):
            event_type = getattr(contract.events, name)
            for event in event_type().get_logs(from_block=from_block, argument_filters={"datasetId": dataset_id}):
                args = {key: (value.hex() if isinstance(value, (bytes, bytearray)) else value) for key, value in event["args"].items()}
                found.append({"event": name, "args": args, "transaction_hash": event["transactionHash"].hex(),
                              "block_number": event["blockNumber"], "log_index": event["logIndex"]})
        found.sort(key=lambda item: (item["block_number"], item["log_index"]))
        return {"status": "available", "dataset_id": dataset_id_value, "chain_id": w3.eth.chain_id,
                "contract_address": RIGHTS_LEDGER_ADDRESS, "events": found}
    except Exception as exc:
        return {"status": "unavailable", "events": [], "error": f"Event lookup failed: {type(exc).__name__}"}
