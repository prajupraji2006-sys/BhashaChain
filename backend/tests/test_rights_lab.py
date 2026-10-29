import csv
import hashlib
import io

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.rights_lab import benchmark_cases, evaluate_evidence, validate_csv_import


SOURCE = "https://www.kaggle.com/datasets/disisbig/kannada-news-dataset"


def complete_evidence():
    return {
        "dataset_name": "Synthetic complete case", "language": "kn", "modality": "text",
        "source_url": SOURCE, "source_publisher": "Synthetic rights holder",
        "licence_name": "CC BY-SA 4.0", "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "licence_evidence_status": "VERIFIED", "provenance_status": "VERIFIED",
        "intended_purpose": "commercial_training", "commercial_training": True,
        "attribution_required": True, "redistribution_conditions": "Use attribution and follow licence terms.",
        "share_alike_conditions": "Shared adaptations use the same or compatible licence.",
        "expiry_date": "2030-12-31T23:59:59Z", "expiry_evidence_status": "VERIFIED",
        "revocation_status": "ACTIVE", "evidence_notes": "Synthetic test fixture only.",
        "evidence_timestamp": "2026-10-29T00:00:00Z",
    }


def csv_fixture():
    output=io.StringIO(newline="")
    writer=csv.DictWriter(output,fieldnames=["headline","label"])
    writer.writeheader()
    rows=[{"headline":f"synthetic headline {i}","label":"sports"} for i in range(20)]
    writer.writerows(rows)
    content=output.getvalue().encode("utf-8")
    return content,rows,hashlib.sha256(content).hexdigest()


def import_body(dataset_id="lab-kannada-test"):
    content,rows,digest=csv_fixture()
    return content,{
        "dataset_id":dataset_id,"filename":"train.csv","row_count":20,"columns":["headline","label"],
        "source_url":SOURCE,"file_sha256":digest,"sample_rows":rows,
        "rights_evidence":{**complete_evidence(),"dataset_name":"Kannada News Headlines Dataset",
            "licence_evidence_status":"UNVERIFIED","provenance_status":"NEEDS_REVIEW",
            "commercial_training":None,"expiry_date":None,"expiry_evidence_status":"UNKNOWN",
            "revocation_status":"UNKNOWN","evidence_notes":"Source-reported claims; not independently verified."},
    }


def configure_db(tmp_path,monkeypatch):
    from backend.app import config,db
    from backend.app import main
    from backend.app.services import manifest_service
    monkeypatch.setattr(config,"DB_PATH",tmp_path/"rights-lab.db")
    monkeypatch.setattr(db,"DB_PATH",tmp_path/"rights-lab.db")
    monkeypatch.setattr(manifest_service,"MANIFEST_DIR",tmp_path/"manifests")
    monkeypatch.setattr(main,"BLOCKCHAIN_MODE","disabled")


def test_synthetic_benchmark_expected_outcomes():
    cases=benchmark_cases()
    assert all(case["synthetic"] is True for case in cases)
    assert {case["case_id"]:case["result"]["decision"] for case in cases}=={
        "A":"ALLOWED","B":"NEEDS_REVIEW","C":"REJECTED","D":"REJECTED","E":"REJECTED"}
    assert cases[0]["result"]["evidence_layer_only"] is True
    assert cases[0]["result"]["legal_authority"] is False


def test_cc_by_sa_commercial_use_is_not_blanket_rejected():
    result=evaluate_evidence(complete_evidence(),{"purpose":"commercial_training","attribution_provided":True,"will_share_adapted_work":False})
    assert result["decision"]=="ALLOWED"
    no_attribution=evaluate_evidence(complete_evidence(),{"purpose":"commercial_training","attribution_provided":False,"will_share_adapted_work":False})
    assert no_attribution["decision"]=="REJECTED"
    no_sharealike=evaluate_evidence(complete_evidence(),{"purpose":"commercial_training","attribution_provided":True,"will_share_adapted_work":True,"share_alike_acknowledged":False})
    assert no_sharealike["decision"]=="REJECTED"


def test_csv_validation_requires_real_schema_and_20_to_50_sample():
    rows=[{"headline":str(i),"label":"sports"} for i in range(20)]
    assert validate_csv_import("train.csv",["headline","label"],20,"a"*64,rows)
    try:
        validate_csv_import("bad.csv",["text","category"],20,"a"*64,[{"text":"x","category":"sports"}]*20)
    except ValueError as exc:
        assert str(exc)=="CSV_SCHEMA_REQUIRES_HEADLINE_AND_LABEL"
    else:
        raise AssertionError("Unexpected CSV schema was accepted")
    try:
        validate_csv_import("train.csv",["headline","label"],20,"a"*64,rows[:19])
    except ValueError as exc:
        assert str(exc)=="SAMPLE_SIZE_MUST_BE_20_TO_50"
    else:
        raise AssertionError("Undersized sample was accepted")


def test_import_defaults_to_unverified_and_needs_review_manifest(tmp_path,monkeypatch):
    configure_db(tmp_path,monkeypatch)
    content,body=import_body()
    from backend.app.services import manifest_service
    with TestClient(app) as client:
        imported=client.post("/api/rights-lab/import",json=body)
        assert imported.status_code==200
        assert imported.json()["original_file_stored"] is False
        assert imported.json()["hash_status"]=="browser_computed_unverified"
        unverified_registry={"dataset_id":body["dataset_id"],"content_hash":body["file_sha256"],"language":"kn","licence_version":"1.0","issuer":"Unverified Provider","purposes":["commercial_training"],"regions":["IN"],"derivatives_allowed":False,"redistribution_allowed":False,"expires_at":"2030-12-31T23:59:59Z","licensing_cost":0,"rights_evidence":imported.json()["rights_evidence"]}
        assert client.post("/api/datasets",json=unverified_registry).status_code==422
        assert client.get(f"/api/datasets/{body['dataset_id']}").status_code==404
        checked=client.post("/api/rights-lab/check",json={"dataset_id":body["dataset_id"],"purpose":"commercial_training","geography":"IN"})
        assert checked.status_code==200
        assert checked.json()["decision"]=="NEEDS_REVIEW"
        assert checked.json()["training_eligible"] is False
        assert client.get("/api/manifests/accepted").json()["count"]==0
        pending=client.get("/api/manifests/needs-review").json()
        assert pending["count"]==1 and pending["entries"][0]["file_sha256"]==body["file_sha256"]
        assert client.get("/api/rights-lab/accepted-corpus").json()["count"]==0
        assert client.get("/api/rights-lab/datasets").json()[0].get("sample_rows") is None


def test_original_csv_storage_is_opt_in_hash_checked_and_gitignored(tmp_path,monkeypatch):
    configure_db(tmp_path,monkeypatch)
    from backend.app import main
    monkeypatch.setattr(main,"DATA_DIR",tmp_path/"backend"/"data")
    content,body=import_body("lab-original-test")
    with TestClient(app) as client:
        assert client.post("/api/rights-lab/import",json=body).status_code==200
        bad=client.post(f"/api/rights-lab/datasets/{body['dataset_id']}/store-original",content=b"wrong",headers={"Content-Type":"text/csv"})
        assert bad.status_code==422 and bad.json()["detail"]=="ORIGINAL_CSV_SHA256_MISMATCH"
        saved=client.post(f"/api/rights-lab/datasets/{body['dataset_id']}/store-original",content=content,headers={"Content-Type":"text/csv"})
        assert saved.status_code==200 and saved.json()["stored"] is True
        item=client.get("/api/rights-lab/datasets").json()[0]
        assert item["original_file_stored"] is True and item["hash_status"]=="server_verified"
        assert list((tmp_path/"backend"/"private_data").glob("*.csv"))


def test_v3_signed_rights_evidence_tampering_fails_and_needs_chain(tmp_path,monkeypatch):
    configure_db(tmp_path,monkeypatch)
    content,body=import_body("lab-signed-test")
    evidence={**body["rights_evidence"],**complete_evidence(),"dataset_name":"Kannada News Headlines Dataset"}
    body["rights_evidence"]=evidence
    from backend.app.services.signature_service import verify_dataset
    from backend.app import main
    from backend.app.services import blockchain_service,manifest_service
    with TestClient(app) as client:
        imported=client.post("/api/rights-lab/import",json=body)
        assert imported.status_code==200
        saved_evidence=imported.json()["rights_evidence"]
        payload={"dataset_id":body["dataset_id"],"content_hash":body["file_sha256"],"language":"kn","licence_version":"1.0","issuer":"Provider attestation","purposes":["commercial_training"],"regions":["IN"],"derivatives_allowed":False,"redistribution_allowed":False,"expires_at":"2030-12-31T23:59:59Z","licensing_cost":0,"rights_evidence":saved_evidence}
        registered=client.post("/api/datasets",json=payload)
        assert registered.status_code==200
        record=registered.json()
        assert record["record_schema_version"]==3 and verify_dataset(record) is True
        modified={**record,"rights_evidence":{**record["rights_evidence"],"source_publisher":"tampered"}}
        assert verify_dataset(modified) is False
        assert client.post("/api/rights-lab/check",json={"dataset_id":body["dataset_id"],"purpose":"commercial_training","geography":"IN","attribution_provided":True,"will_share_adapted_work":False}).json()["decision"]=="NEEDS_REVIEW"
        monkeypatch.setattr(main,"BLOCKCHAIN_MODE","required")
        verified_chain={"status":"verified","verified":True,"exists":True,"policy_permitted":True,"revoked":False,"version_match":True,"expiry_match":True}
        monkeypatch.setattr(blockchain_service,"verify_dataset",lambda *_args,**_kwargs:dict(verified_chain))
        monkeypatch.setattr(manifest_service,"verify_dataset",lambda *_args,**_kwargs:dict(verified_chain))
        allowed=client.post("/api/rights-lab/check",json={"dataset_id":body["dataset_id"],"purpose":"commercial_training","geography":"IN","attribution_provided":True,"will_share_adapted_work":False})
        assert allowed.json()["decision"]=="ALLOWED" and allowed.json()["training_eligible"] is True
        assert client.get("/api/rights-lab/accepted-corpus").json()["count"]==1
        assert client.get("/api/manifests/accepted").json()["count"]==1
        revoked_chain={**verified_chain,"status":"verified","verified":False,"revoked":True}
        monkeypatch.setattr(blockchain_service,"verify_dataset",lambda *_args,**_kwargs:dict(revoked_chain))
        monkeypatch.setattr(manifest_service,"verify_dataset",lambda *_args,**_kwargs:dict(revoked_chain))
        revoked=client.post("/api/rights-lab/check",json={"dataset_id":body["dataset_id"],"purpose":"commercial_training","geography":"IN","attribution_provided":True,"will_share_adapted_work":False})
        assert revoked.json()["decision"]=="REJECTED"
        assert client.get("/api/rights-lab/accepted-corpus").json()["count"]==0
        assert client.get("/api/manifests/accepted").json()["count"]==0


def test_review_and_rejected_rows_never_enter_demo_training_corpus(tmp_path,monkeypatch):
    configure_db(tmp_path,monkeypatch)
    from backend.app import db
    content,body=import_body("lab-gate-test")
    with TestClient(app) as client:
        assert client.post("/api/rights-lab/import",json=body).status_code==200
        base={"decision_id":"fixture-review","dataset_id":body["dataset_id"],"decision":"NEEDS_REVIEW","training_eligible":True,"signature_verification":{"verified":True},"blockchain_verification":{"verified":True},"file_sha256":body["file_sha256"],"evaluated_at":"2026-10-29T00:00:00Z"}
        rejected={**base,"decision_id":"fixture-rejected","decision":"REJECTED"}
        allowed={**base,"decision_id":"fixture-allowed","decision":"ALLOWED"}
        db.save_rights_lab_decision(base);db.save_rights_lab_decision(rejected);db.save_rights_lab_decision(allowed)
        corpus=client.get("/api/rights-lab/accepted-corpus").json()
        assert corpus["entries"]==[]
        assert client.get("/api/manifests/needs-review").json()["count"]==1
        assert client.get("/api/manifests/rejected").json()["count"]==1
