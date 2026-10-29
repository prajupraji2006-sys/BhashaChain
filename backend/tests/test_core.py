import hashlib
from backend.app.main import app
from backend.app.services.rights_engine import check
from backend.app.services.signature_service import sign_dataset
from fastapi.testclient import TestClient

def sample():
    d={"dataset_id":"x","content_hash":"a"*64,"language":"ta","licence_version":"1","issuer":"issuer","purposes":["research"],"regions":["IN"],"derivatives_allowed":False,"redistribution_allowed":False,"expires_at":"2030-01-01T00:00:00+00:00","licensing_cost":10,"active":True}
    d["signature"]=sign_dataset(d); return d

def test_valid_and_policy_rejections():
    d=sample(); assert check(d,{"purpose":"research","geography":"IN"})==[]
    assert d["record_schema_version"]==2 and d["signature_algorithm"]=="Ed25519" and d["record_id"]
    assert "GEOGRAPHY_NOT_PERMITTED" in check(d,{"purpose":"research","geography":"US"})
    assert "DERIVATIVES_NOT_PERMITTED" in check(d,{"purpose":"research","geography":"IN","derivatives":True})
    assert "COMMERCIAL_TRAINING_NOT_PERMITTED" in check(d,{"purpose":"commercial_training","geography":"IN"})

def test_expired_revoked_unknown_and_tampered():
    d=sample(); d["expires_at"]="2020-01-01T00:00:00+00:00"; d["signature"]=sign_dataset(d)
    assert check(d,{"purpose":"research","geography":"IN"})==["LICENCE_EXPIRED"]
    d=sample(); d["active"]=False; d["signature"]=sign_dataset(d)
    assert check(d,{"purpose":"research","geography":"IN"})==["LICENCE_REVOKED"]
    assert check(None,{})==["UNKNOWN_DATASET"]
    d=sample(); d["issuer"]="tampered"; assert check(d,{"purpose":"research","geography":"IN"})==["INVALID_SIGNATURE"]
    d=sample(); d["issuer_key_id"]="unknown-key"; d["signature"]=sign_dataset(d)
    assert check(d,{"purpose":"research","geography":"IN"})==["UNAUTHORIZED_ISSUER"]

def test_fail_closed_and_hash_version():
    d=sample(); assert check(d,{"purpose":"research","geography":"IN"},False)==["LICENCE_VERIFICATION_UNAVAILABLE"]
    assert "HASH_MISMATCH" in check(d,{"purpose":"research","geography":"IN","content_hash":"b"*64})
    assert "INVALID_LICENCE_VERSION" in check(d,{"purpose":"research","geography":"IN","licence_version":"0"})
    assert "REDISTRIBUTION_NOT_PERMITTED" in check(d,{"purpose":"research","geography":"IN","redistribution":True})
    incomplete={"dataset_id":"x"}; assert check(incomplete,{})==["MISSING_LICENCE_FIELDS"]

def test_api_persists_decision_and_manifests(tmp_path,monkeypatch):
    from backend.app import db, config
    monkeypatch.setattr(config,"DB_PATH",tmp_path/"api.db"); monkeypatch.setattr(db,"DB_PATH",tmp_path/"api.db")
    from backend.app.services import manifest_service
    monkeypatch.setattr(manifest_service,"MANIFEST_DIR",tmp_path/"manifests")
    with TestClient(app) as client:
        rows=client.get("/api/datasets").json(); assert rows
        d=rows[0]
        out=client.post("/api/decisions/check",json={"dataset_id":d["dataset_id"],"purpose":"commercial_training","geography":"IN","content_hash":d["content_hash"],"licence_version":d["licence_version"]}).json()
        assert out["decision"]=="ACCEPT"
        assert out["signature_verification"]["verified"] is True
        assert out["blockchain_verification"]["status"]=="disabled"
        assert out["manifest_references"]["accepted"]
        assert client.get("/api/audit/"+out["decision_id"]).status_code==200
        accepted=client.get("/api/manifests/accepted").json()
        assert len(accepted["entries"])==1 and accepted["manifest_hash"]==accepted["manifest_id"]
        ta=next(x for x in rows if x["dataset_id"]=="ta-research-02")
        rejected=client.post("/api/decisions/check",json={"dataset_id":"ta-research-02","purpose":"commercial_training","geography":"IN","content_hash":ta["content_hash"],"licence_version":ta["licence_version"]}).json()
        assert rejected["decision"]=="REJECT" and "COMMERCIAL_TRAINING_NOT_PERMITTED" in rejected["reasons"]
        assert len(client.get("/api/manifests/rejected").json()["entries"])==1
        assert client.get("/api/audit/integrity").json()["valid"] is True
        registered=client.post("/api/datasets",json={"dataset_id":"new-demo","content_hash":"a"*64,"language":"gu","licence_version":"1.0","issuer":"Demo","purposes":["research"],"regions":["IN"],"derivatives_allowed":False,"redistribution_allowed":False,"expires_at":"2030-12-31T23:59:59+00:00","licensing_cost":20})
        assert registered.status_code==200 and registered.json()["signature"]
        assert client.post("/api/datasets",json=registered.json()).status_code==409

def test_optimizer_endpoint_filters_rights_and_reports_baseline(tmp_path,monkeypatch):
    from backend.app import db, config
    monkeypatch.setattr(config,"DB_PATH",tmp_path/"opt.db"); monkeypatch.setattr(db,"DB_PATH",tmp_path/"opt.db")
    monkeypatch.delenv("QPIAI_OPT_API_KEY",raising=False)
    with TestClient(app) as client:
        response=client.post("/api/optimization/run",json={"languages":["bn","ta"],"budget":1000,"mandatory_dataset_ids":[],"geography":"IN","purpose":"commercial_training"})
        assert response.status_code==200
        out=response.json(); assert out["classical_baseline"]["feasible"] is True
        assert out["classical_baseline"]["selected_dataset_ids"]==["bn-open-01","ta-commercial-03"]
        assert out["classical_baseline"]["total_cost"]==280
        assert out["classical_baseline"]["cost_allocation"]=={"bn-open-01":120.0,"ta-commercial-03":160.0}
        assert "mr-expired-04" in [x["dataset_id"] for x in out["excluded_datasets"]]
        assert "kn-revoked-05" in [x["dataset_id"] for x in out["excluded_datasets"]]
        assert out["qpiai_opt"]["execution_mode"]=="not_configured"
        assert out["classical_baseline"]["budget_feasible"] is True

def test_unconfigured_qpiai_is_not_misreported(monkeypatch):
    from optimizer.opt_selector import select_with_qpiai
    monkeypatch.delenv("QPIAI_OPT_API_KEY",raising=False)
    result=select_with_qpiai([],[],0)
    assert result["solver"]=="qpiai_opt" and result["execution_mode"]=="not_configured" and result["feasible"] is None
    assert result["selected_dataset_ids"]==[] and result["budget_feasible"] is None

def test_qpiai_uses_explicit_nonplatform_local_mode(monkeypatch):
    from types import SimpleNamespace
    import qpiai_opt.opt_solvers as opt_solvers
    from optimizer.opt_selector import select_with_qpiai
    monkeypatch.setenv("QPIAI_OPT_API_KEY","unit-test-key")
    call={}
    info=SimpleNamespace(has_usable_solution=True,solution_feasible=True,termination="OPTIMAL",guarantee="exact",method="highs")
    sdk_result=SimpleNamespace(solution={"d0":1.0,"d1":1.0},execution_mode="local",problem_class="MILP",objective=280.0,compute_time_s=0.01,info=lambda:info,optimality_gap=None,best_bound=280.0)
    def fake_solve(model,**kwargs):
        call.update(kwargs)
        return sdk_result
    monkeypatch.setattr(opt_solvers,"solve",fake_solve)
    candidates=[{"dataset_id":"bn-open-01","language":"bn","licensing_cost":120,"eligible":True},{"dataset_id":"ta-commercial-03","language":"ta","licensing_cost":160,"eligible":True}]
    result=select_with_qpiai(candidates,["bn","ta"],1000)
    assert result["status"]=="solved" and result["execution_mode"]=="local"
    assert result["selected_dataset_ids"]==["bn-open-01","ta-commercial-03"] and result["total_cost"]==280
    assert call["mode"]=="local" and call["allow_platform"] is False
    assert result["platform_fallback_enabled"] is False

def test_qpiai_failure_diagnostics_do_not_leak_exception_text(monkeypatch,caplog):
    import qpiai_opt.opt_solvers as opt_solvers
    from optimizer.opt_selector import select_with_qpiai
    test_secret="unit-test-secret-do-not-log"
    monkeypatch.setenv("QPIAI_OPT_API_KEY",test_secret)
    class AuthenticationError(Exception): pass
    def fail_solve(*_args,**_kwargs):
        raise AuthenticationError(f"Authorization header contained {test_secret}")
    monkeypatch.setattr(opt_solvers,"solve",fail_solve)
    candidates=[{"dataset_id":"bn-open-01","language":"bn","licensing_cost":120,"eligible":True},{"dataset_id":"ta-commercial-03","language":"ta","licensing_cost":160,"eligible":True}]
    result=select_with_qpiai(candidates,["bn","ta"],1000)
    assert result["status"]=="failed" and result["execution_mode"]=="failed"
    assert result["requested_execution_mode"]=="local" and result["error_stage"]=="local_solve"
    assert result["error_code"]=="QPIAI_AUTHENTICATION_OR_SERVICE_ERROR"
    assert test_secret not in str(result) and test_secret not in caplog.text
    assert "Authorization header" not in caplog.text

def test_qpiai_never_reports_unexpected_platform_result_as_local(monkeypatch):
    from types import SimpleNamespace
    import qpiai_opt.opt_solvers as opt_solvers
    from optimizer.opt_selector import select_with_qpiai
    monkeypatch.setenv("QPIAI_OPT_API_KEY","unit-test-key")
    monkeypatch.setattr(opt_solvers,"solve",lambda *_args,**_kwargs:SimpleNamespace(execution_mode="platform"))
    candidates=[{"dataset_id":"bn-open-01","language":"bn","licensing_cost":120,"eligible":True},{"dataset_id":"ta-commercial-03","language":"ta","licensing_cost":160,"eligible":True}]
    result=select_with_qpiai(candidates,["bn","ta"],1000)
    assert result["status"]=="failed" and result["error_code"]=="QPIAI_UNEXPECTED_EXECUTION_MODE"
    assert result["execution_mode"]=="platform" and result["requested_execution_mode"]=="local"
    assert result["selected_dataset_ids"]==[] and result["feasible"] is None

def test_classical_optimizer_constraints():
    from optimizer.classical_baseline import select
    c=[{"dataset_id":"expensive","language":"ta","licensing_cost":9,"eligible":True},{"dataset_id":"cheap","language":"ta","licensing_cost":3,"eligible":True},{"dataset_id":"bad","language":"bn","licensing_cost":1,"eligible":False}]
    r=select(c,["ta"],5); assert r["selected_dataset_ids"]==["cheap"] and r["total_cost"]==3
    assert select(c,["bn"],5)["feasible"] is False
    assert select(c,["ta"],20,["absent"])["feasible"] is False

def test_chain_unconfigured_never_claims_verification(monkeypatch):
    from backend.app.services import blockchain_service
    monkeypatch.setattr(blockchain_service,"BLOCKCHAIN_RPC_URL","")
    monkeypatch.setattr(blockchain_service,"RIGHTS_LEDGER_ADDRESS","")
    status=blockchain_service.status()
    assert status["status"]=="not_configured" and status["verified"] is False
    assert status["rpc_connected"] is False
    assert status["contract_abi_compatible"] is False
    assert status["backend_issuer_authorized"] is None
    result=blockchain_service.register(sample())
    assert result["status"]=="not_submitted" and result["verified"] is False

def test_production_chain_rejects_local_hardhat_rpc(monkeypatch):
    from backend.app.services import blockchain_service
    monkeypatch.setattr(blockchain_service,"APP_ENV","production")
    monkeypatch.setattr(blockchain_service,"BLOCKCHAIN_RPC_URL","http://127.0.0.1:8545")
    monkeypatch.setattr(blockchain_service,"RIGHTS_LEDGER_ADDRESS","0x"+"1"*40)
    connection,error=blockchain_service._web3()
    assert connection is None and error=="Local RPC endpoints are not allowed in production"

def test_production_chain_rejects_hardhat_chain_id(monkeypatch):
    import web3
    from backend.app.services import blockchain_service
    class FakeEth:
        chain_id=31337
    class FakeWeb3:
        eth=FakeEth()
        def __init__(self,_provider): pass
        @staticmethod
        def HTTPProvider(*_args,**_kwargs): return object()
        def is_connected(self): return True
    monkeypatch.setattr(web3,"Web3",FakeWeb3)
    monkeypatch.setattr(blockchain_service,"APP_ENV","production")
    monkeypatch.setattr(blockchain_service,"BLOCKCHAIN_RPC_URL","https://rpc.example")
    monkeypatch.setattr(blockchain_service,"RIGHTS_LEDGER_ADDRESS","0x"+"1"*40)
    connection,error=blockchain_service._web3()
    assert connection is None and error=="Hardhat local chain ID 31337 is not allowed in production"

def test_api_only_persists_confirmed_chain_mutations(tmp_path,monkeypatch):
    from backend.app import db, config
    from backend.app import main
    from backend.app.services import blockchain_service
    monkeypatch.setattr(config,"DB_PATH",tmp_path/"mutation.db"); monkeypatch.setattr(db,"DB_PATH",tmp_path/"mutation.db")
    monkeypatch.setattr(main,"BLOCKCHAIN_MODE","optional")
    with TestClient(app) as client:
        before=client.get("/api/datasets/bn-open-01").json()
        body={"content_hash":"b"*64,"licence_version":"1.1","purposes":["research"],"regions":["IN"],"derivatives_allowed":False,"redistribution_allowed":False,"expires_at":"2030-12-31T23:59:59+00:00"}
        monkeypatch.setattr(blockchain_service,"update",lambda *_:{"status":"not_submitted","verified":False,"error":"missing local chain"})
        assert client.post("/api/datasets/bn-open-01/update",json=body).status_code==409
        assert client.get("/api/datasets/bn-open-01").json()["licence_version"]==before["licence_version"]
        monkeypatch.setattr(blockchain_service,"update",lambda *_:{"status":"confirmed","verified":True,"transaction_hash":"0xupdate"})
        updated=client.post("/api/datasets/bn-open-01/update",json=body)
        assert updated.status_code==200 and updated.json()["blockchain_update"]["verified"] is True
        monkeypatch.setattr(blockchain_service,"revoke",lambda *_:{"status":"not_submitted","verified":False})
        assert client.post("/api/datasets/bn-open-01/revoke").status_code==409
        monkeypatch.setattr(blockchain_service,"revoke",lambda *_:{"status":"confirmed","verified":True,"transaction_hash":"0xrevoke"})
        revoked=client.post("/api/datasets/bn-open-01/revoke")
        assert revoked.status_code==200 and revoked.json()["active"] is False

def test_unverified_chain_registration_is_not_persisted(tmp_path,monkeypatch):
    from backend.app import db, config, main
    from backend.app.services import blockchain_service
    monkeypatch.setattr(config,"DB_PATH",tmp_path/"unverified-registration.db"); monkeypatch.setattr(db,"DB_PATH",tmp_path/"unverified-registration.db")
    monkeypatch.setattr(main,"BLOCKCHAIN_MODE","required")
    monkeypatch.setattr(blockchain_service,"register",lambda *_:{"status":"confirmed","verified":False,"issuer_match":False})
    payload={"dataset_id":"unverified-register","content_hash":"c"*64,"language":"gu","licence_version":"1.0","issuer":"Untrusted Demo","purposes":["research"],"regions":["IN"],"derivatives_allowed":False,"redistribution_allowed":False,"expires_at":"2030-12-31T23:59:59+00:00","licensing_cost":5}
    with TestClient(app) as client:
        response=client.post("/api/datasets",json=payload)
        assert response.status_code==503
        assert response.json()["detail"]["code"]=="BLOCKCHAIN_REGISTRATION_REQUIRED"
        assert client.get("/api/datasets/unverified-register").status_code==404

def test_required_chain_fails_closed_and_ineligible_mandatory_is_rejected(tmp_path,monkeypatch):
    from backend.app import db, config, main
    from backend.app.services import blockchain_service
    monkeypatch.setattr(config,"DB_PATH",tmp_path/"required.db"); monkeypatch.setattr(db,"DB_PATH",tmp_path/"required.db")
    monkeypatch.setattr(main,"BLOCKCHAIN_MODE","required")
    monkeypatch.setattr(blockchain_service,"verify_dataset",lambda *args,**kwargs:{"status":"unavailable","verified":False,"error":"offline"})
    monkeypatch.delenv("QPIAI_OPT_API_KEY",raising=False)
    with TestClient(app) as client:
        d=client.get("/api/datasets/bn-open-01").json()
        checked=client.post("/api/decisions/check",json={"dataset_id":d["dataset_id"],"purpose":"commercial_training","geography":"IN","content_hash":d["content_hash"],"licence_version":d["licence_version"]})
        assert checked.json()["decision"]=="REJECT"
        assert "BLOCKCHAIN_UNAVAILABLE" in checked.json()["reason_codes"]
        response=client.post("/api/optimization/run",json={"languages":["ta"],"budget":1000,"mandatory_dataset_ids":["ta-research-02"],"purpose":"commercial_training","geography":"IN"})
        assert response.status_code==422
        assert response.json()["detail"]["code"]=="MANDATORY_DATASET_INELIGIBLE"

def test_audit_hash_chain_detects_tampering(tmp_path,monkeypatch):
    from backend.app import db, config
    from datetime import datetime,timezone
    monkeypatch.setattr(config,"DB_PATH",tmp_path/"audit.db"); monkeypatch.setattr(db,"DB_PATH",tmp_path/"audit.db")
    db.init_db()
    db.save_audit_event("TEST_EVENT",{"value":"original"},datetime.now(timezone.utc).isoformat())
    assert db.verify_audit_chain()["valid"] is True
    with db.connect() as connection:
        connection.execute("UPDATE audit_events SET data=? WHERE id=1",('{"value":"changed"}',))
    assert db.verify_audit_chain()["valid"] is False
