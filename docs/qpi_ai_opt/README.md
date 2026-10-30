# Facility dispatch QUBO integration

## Architecture and execution modes

`POST /api/qubo/dispatch` is a separate FastAPI route. It accepts batches and candidate facilities, builds a binary quadratic objective, and reports the solver identity and execution mode in every response. It does not change dataset registration, licence evaluation, blockchain verification, the existing dataset optimizer, or the audit trail.

When `QPIAI_OPT_API_KEY` is configured, the adapter uses the installed `qpiai-opt==0.0.9` interfaces `Binary`, `Model`, `Client`, and `solve(model, mode="local", client=..., allow_platform=False)`. The installed SDK describes local calls as credential-verified before local compute. Platform execution is explicitly disabled. The key remains server-side and is never logged or returned. If the SDK is missing, authentication fails, the local runtime errors, or its solution fails independent validation, dispatch uses an exact enumerator only when the QUBO has at most 20 binary variables. The response labels that mode `classical_exact_qubo_fallback`; it is never reported as a QpiAI result.

The fallback enumerates all QUBO bit strings and independently checks assignment, chemistry, and capacity feasibility. `OPTIMAL` therefore means an exhaustive optimum for the named solver. A QpiAI response is called `OPTIMAL` only when the SDK reports an optimal termination; other feasible SDK results remain `FEASIBLE`. If no feasible assignment is found, the API returns `INFEASIBLE`; if the bounded fallback cannot run, it returns `UNAVAILABLE` without inventing an assignment. Valid dispatch calls return HTTP 200 with the solver status in the response.

## QUBO formulation

For job `j` and facility `f`, binary `x[j,f]` indicates assignment. The objective is the sum of `cost_per_unit[f] * units[j] * x[j,f]` plus penalties:

- Exactly one facility per job: `P * (sum_f x[j,f] - 1)^2`.
- Capacity: `P * (sum_j units[j] * x[j,f] + slack[f] - capacity[f])^2`. Integer slack is encoded with binary powers of two.
- Chemistry compatibility: `P * x[j,f]` for each incompatible job/facility pair.

`P` is one greater than the upper bound on feasible assignment cost. Binary expansion makes the squared terms quadratic. Request sizes are limited to six jobs and six facilities; each has bounded capacity/units. The exact fallback has a separate 20-bit limit.

## Request and response

Synthetic smoke-test request:

```json
{
  "jobs": [{"job_id":"batch-001","chemistry":"alkaline","units":2}],
  "facilities": [
    {"facility_id":"facility-alpha","name":"Facility Alpha","capacity":2,"chemistries":["alkaline"],"cost_per_unit":5},
    {"facility_id":"facility-beta","name":"Facility Beta","capacity":2,"chemistries":["alkaline"],"cost_per_unit":3}
  ]
}
```

Send it to `POST http://127.0.0.1:8000/api/qubo/dispatch` with `Content-Type: application/json`. Production calls must include the backend API bearer token when `API_ACCESS_TOKEN` is configured. The API validates identifiers, input counts, positive units/capacities, unique IDs, chemistry lists, and finite nonnegative costs. Invalid JSON or fields return HTTP 422.

The first recorded local smoke-test attempt returned `AuthenticationError`; its evidence contains no upstream HTTP status or error code, so it cannot distinguish an invalid key from a revoked key. The configured key was later verified successfully using the SDK's credential-verification endpoint. The actual `qpiai-opt==0.0.9` local smoke-test response then returned HTTP 200:

```json
{
  "trace_id": "real-qpi-local-296b4a3c0c0b",
  "status": "OPTIMAL",
  "solver": "qpiai_opt",
  "execution_mode": "local",
  "assigned_facility": {"facility_id": "facility-beta", "name": "Facility Beta"},
  "objective_value": 6.0,
  "qpiai_opt": {"status": "optimal", "execution_mode": "local", "termination": "optimal", "method": "exhaustive-enumeration", "sdk_version": "0.0.9"}
}
```

The SDK returned a usable QUBO result with `execution_mode="local"` and `termination="optimal"`. Its positional `solution` vector and named `variable_assignment` were captured in the JSONL evidence. The returned assignment was independently checked against the original chemistry and capacity constraints; its independently calculated cost was 6.0. The run used synthetic inputs, disabled platform execution, and submitted no hosted job. The deterministic fixture at `backend/tests/fixtures/qpi_ai_opt_dispatch_synthetic.json` remains synthetic and is marked as such.

## Logs and reproduction

The endpoint writes `[QPI AI OPT]` timestamped console and file logs to `logs/qpi_ai_opt.log`. Entries include a safe trace ID, request counts and bounded parameters, solver status/identity, selected facility ID, and duration. Exception text, environment values, API keys, and headers are omitted. Synthetic test request/response and real synthetic-input execution evidence are stored as JSON Lines in `logs/qpi_ai_opt_test_data.jsonl`; SDK results and verification/error metadata are redacted before storage.

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qubo_dispatch.py -q
$env:BLOCKCHAIN_MODE = "disabled"
.\.venv\Scripts\python.exe -m pytest backend/tests -q
Remove-Item Env:BLOCKCHAIN_MODE
Set-Location frontend
npm.cmd run build
```

The tests use synthetic inputs and fake the SDK boundary; they make no hosted solve request. To enable real QpiAI local execution, install `backend/requirements-qpiai-opt.txt` and configure `QPIAI_OPT_API_KEY` in the backend environment. The SDK may verify the credential online before local solving. Do not place the key in Vite variables or frontend code. An authentication error must be resolved with the account/key owner; the classical result remains separately labeled meanwhile.
