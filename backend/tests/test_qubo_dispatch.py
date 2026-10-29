import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.main import app

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "qpi_ai_opt_dispatch_synthetic.json"
EVIDENCE = ROOT / "logs" / "qpi_ai_opt_test_data.jsonl"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_dispatch_valid_synthetic_fixture_records_actual_api_response(monkeypatch):
    fixture = _fixture()
    monkeypatch.setenv("QPIAI_OPT_API_KEY", "")
    trace_id = "dispatch-test-" + uuid4().hex[:12]
    with TestClient(app) as client:
        response = client.post("/api/qubo/dispatch", json=fixture["request"], headers={"X-Request-ID": trace_id})
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == trace_id
    assert body["status"] == fixture["expected"]["status"]
    assert body["solver"] == "classical_exact_qubo_fallback"
    assert body["execution_mode"] == "local_classical_fallback"
    assert body["qpiai_opt"]["status"] == "not_configured"
    assert body["assigned_facility"]["facility_id"] == fixture["expected"]["facility_id"]
    assert body["objective_value"] == fixture["expected"]["objective_value"]
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evidence_type": "synthetic_test_fixture",
        "synthetic": True,
        "trace_id": trace_id,
        "solver_tool_identity": body["solver"],
        "qpiai_status": body["qpiai_opt"]["status"],
        "http_status": response.status_code,
        "request": fixture["request"],
        "response": body,
        "note": "Actual local FastAPI response to the labelled synthetic fixture; no QpiAI solve was claimed.",
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    with EVIDENCE.open("a", encoding="utf-8") as evidence_file:
        evidence_file.write(json.dumps(record, sort_keys=True) + "\n")


def test_dispatch_missing_and_invalid_input_is_422():
    with TestClient(app) as client:
        missing = client.post("/api/qubo/dispatch", json={})
        invalid = client.post("/api/qubo/dispatch", json={"jobs": [{"job_id": "bad value", "chemistry": "alkaline", "units": 0}], "facilities": []})
    assert missing.status_code == 422
    assert invalid.status_code == 422
    assert missing.json()["detail"]["code"] == "DISPATCH_INVALID_INPUT"


def test_dispatch_qpiai_sdk_local_interface_and_response_are_truthful(monkeypatch):
    import qpiai_opt.opt_solvers as opt_solvers

    monkeypatch.setenv("QPIAI_OPT_API_KEY", "synthetic-unit-test-key")
    call = {}
    info = SimpleNamespace(has_usable_solution=True, solution_feasible=True, termination="OPTIMAL", method="synthetic-test")
    result = SimpleNamespace(execution_mode="local", solution={"x_0_0": 0, "x_0_1": 1}, objective=6.0,
                             compute_time_s=0.001, info=lambda: info)

    def fake_solve(model, **kwargs):
        call.update(kwargs)
        return result

    monkeypatch.setattr(opt_solvers, "solve", fake_solve)
    with TestClient(app) as client:
        response = client.post("/api/qubo/dispatch", json=_fixture()["request"])
    assert response.status_code == 200
    body = response.json()
    assert body["solver"] == "qpiai_opt" and body["execution_mode"] == "local"
    assert body["status"] == "OPTIMAL" and body["assigned_facility"]["facility_id"] == "facility-beta"
    assert call["mode"] == "local" and call["allow_platform"] is False


def test_dispatch_qpiai_error_uses_clearly_labelled_fallback(monkeypatch):
    import qpiai_opt.opt_solvers as opt_solvers

    monkeypatch.setenv("QPIAI_OPT_API_KEY", "synthetic-unit-test-key")
    monkeypatch.setattr(opt_solvers, "solve", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret text must not be logged")))
    with TestClient(app) as client:
        response = client.post("/api/qubo/dispatch", json=_fixture()["request"])
    body = response.json()
    assert response.status_code == 200
    assert body["qpiai_opt"]["status"] == "failed"
    assert body["solver"] == "classical_exact_qubo_fallback"
    assert body["execution_mode"] == "local_classical_fallback"
    assert body["assigned_facility"]["facility_id"] == "facility-beta"
    logs = (ROOT / "logs" / "qpi_ai_opt.log").read_text(encoding="utf-8")
    assert "secret text must not be logged" not in logs
    assert "synthetic-unit-test-key" not in logs


def test_qubo_chemistry_penalty_prevents_incompatible_low_cost_assignment(monkeypatch):
    monkeypatch.setenv("QPIAI_OPT_API_KEY", "")
    request = {"jobs": [{"job_id": "batch-chem", "chemistry": "alkaline", "units": 1}],
               "facilities": [{"facility_id": "alpha", "name": "Facility Alpha", "capacity": 1,
                               "chemistries": ["alkaline"], "cost_per_unit": 8},
                              {"facility_id": "beta", "name": "Facility Beta", "capacity": 1,
                               "chemistries": ["acid"], "cost_per_unit": 1}]}
    with TestClient(app) as client:
        response = client.post("/api/qubo/dispatch", json=request)
    assert response.status_code == 200
    assert response.json()["assigned_facility"]["facility_id"] == "alpha"


def test_qubo_capacity_penalty_respects_facility_limit(monkeypatch):
    monkeypatch.setenv("QPIAI_OPT_API_KEY", "")
    request = {"jobs": [{"job_id": "batch-a", "chemistry": "alkaline", "units": 2},
                        {"job_id": "batch-b", "chemistry": "alkaline", "units": 2}],
               "facilities": [{"facility_id": "alpha", "name": "Facility Alpha", "capacity": 2,
                               "chemistries": ["alkaline"], "cost_per_unit": 1},
                              {"facility_id": "beta", "name": "Facility Beta", "capacity": 4,
                               "chemistries": ["alkaline"], "cost_per_unit": 3}]}
    with TestClient(app) as client:
        response = client.post("/api/qubo/dispatch", json=request)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OPTIMAL"
    assert len(body["assignments"]) == 2
    assert {item["facility_id"] for item in body["assignments"]} == {"alpha", "beta"}
