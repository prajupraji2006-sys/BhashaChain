# BhashaChain

BhashaChain is a Web3-04 hackathon prototype for regional-language dataset licensing. It combines an Ed25519-signed local registry and rights policy engine with an optional Solidity rights ledger. It supports real local-chain registration, licence updates, revocation, transaction receipt/event checks, current-state readback, eligibility filtering, and a QpiAI Opt local optimization adapter alongside an independent classical baseline.

This prototype records licensing evidence. It does not establish legal ownership, prevent reuse of downloaded data, or guarantee a licence is enforceable.

## Start the app on Windows

Requirements: Python 3.10+, Node.js 20+, and npm. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Keep an existing `.env` file. Never paste credentials into source files or the frontend. In another PowerShell terminal:

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

Open <http://localhost:5173>. The API docs are at <http://127.0.0.1:8000/docs>. SQLite seeds five demo records on first launch.

## Optional local Hardhat chain

Use three terminals. In terminal 1:

```powershell
Set-Location contracts
npm.cmd install
npm.cmd run node
```

In terminal 2, compile (this also syncs the contract ABI used by FastAPI) and deploy:

```powershell
Set-Location contracts
npm.cmd run compile
npm.cmd run deploy:local
```

Copy the displayed deployed address. In the existing root `.env`, set `BLOCKCHAIN_RPC_URL=http://127.0.0.1:8545`, `BLOCKCHAIN_CHAIN_ID=31337`, `RIGHTS_LEDGER_ADDRESS`, and `BLOCKCHAIN_SENDER_ADDRESS` to the chosen local provider account. The deployment account is the contract owner but has no provider access by default. Explicitly authorize the backend signer before restarting the API:

```powershell
$env:RIGHTS_LEDGER_ADDRESS = "0xYOUR_DEPLOYED_LEDGER_ADDRESS"
$env:DATASET_PROVIDER_ADDRESS = "0xYOUR_BLOCKCHAIN_SENDER_ADDRESS"
$env:PROVIDER_ACTION = "authorize"
npm.cmd run provider:access
```

The command confirms the authorization by contract readback. Set `PROVIDER_ACTION` to `revoke` and rerun it to block that provider from creating new records. It only runs against `localhost`. The backend will not persist a chain-enabled registration unless its transaction, event, content hash, version, and on-chain issuer match verify. `BLOCKCHAIN_PRIVATE_KEY` is an optional server-side signer for other explicitly configured environments. Never use a real wallet key here. Restart the API after changing `.env`.

Licence updates and revocations require the configured signer to be the contract issuer. If chain mode is explicitly disabled, records remain local and are reported as not chain-verified. Do not expose the development API beyond loopback. The V2 ledger is not upgradeable: redeploying it does not migrate existing chain records. Back up SQLite before a ledger reset; previously anchored rows will need a deliberate data migration before required-chain checks can accept them on the new address.

## Run checks

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
Set-Location frontend
npm.cmd run build
Set-Location ..\contracts
npm.cmd test
```

The three QpiAI Quantum cloud tests are skipped by default because they authenticate or submit an external job. Run those only when intended with `RUN_QPIAI_QUANTUM_INTEGRATION=1` and appropriate QpiAI access. The ordinary Python suite never invokes QpiAI Opt because it would need credentials; the app retains the authenticated local QpiAI Opt path for the live demo.

## Optimization

The Optimizer accepts required languages, budget, mandatory dataset IDs, geography, and intended purpose. It filters actual SQLite records through the local signature and rights policy before either solver runs. The QpiAI result is labelled with its SDK execution mode and diagnostics; the classical baseline remains separately reported. The baseline regression fixture selects `bn-open-01` and `ta-commercial-03` for a total cost of 280 under budget 1000.

Install the pinned optional adapter with `python -m pip install -r backend/requirements-qpiai-opt.txt`, then set `QPIAI_OPT_API_KEY` only in `.env` to enable QpiAI Opt. The app requests the documented local SDK mode; the SDK verifies the key online but computes locally, with platform execution and fallback disabled. The app does not switch to another solver and call it QpiAI Opt when the SDK or authentication fails. See [docs/qpiai-opt-integration.md](docs/qpiai-opt-integration.md).

## Architecture and demo

- `backend/app`: FastAPI, SQLite, Ed25519 signatures, rights checks, chain adapter, and audit.
- `optimizer`: QpiAI Opt local adapter and independent classical baseline.
- `contracts`: Solidity `RightsLedger`, Hardhat deployment and tests.
- `frontend`: React workflows for registry, rights checks, optimizer, Quantum lab, and audit evidence.
- `docs/`: setup, API, security, architecture, integration notes, and a judge demo sequence.

See [docs/demo-script.md](docs/demo-script.md), [docs/api-contract.md](docs/api-contract.md), and [contracts/README.md](contracts/README.md). Raw corpora, private information, and API credentials stay off-chain. On-chain records contain only hashes, permissions, issuer address, version, expiry, status, and timestamps.

## Hosting

`netlify.toml` prepares the React website for Netlify; `render.yaml` prepares the FastAPI service for Render. No account is connected and nothing has been deployed publicly yet. Set Netlify's `VITE_API_BASE_URL` to the deployed API URL, and set the API's `CORS_ORIGINS` to the Netlify website origin. Never expose API tokens or wallet keys as `VITE_` variables. The included Render free service has ephemeral storage; choose a durable database before storing production records. See [docs/evidence-matrix.md](docs/evidence-matrix.md) and [docs/judge-qa.md](docs/judge-qa.md) for verified status and judge answers.

### Backend environment variables

Use `.env.example` as the local template. For a separately hosted backend, configure values through the host's environment settings; do not commit `.env` or put backend secrets in Netlify variables.

| Variable | Required use | Notes |
| --- | --- | --- |
| `APP_ENV` | Always | Set `production` on the host; production write routes require authentication. |
| `API_ACCESS_TOKEN` | Production | Strong random server-side token; send only to the backend over HTTPS. |
| `ISSUER_SIGNING_SECRET` | Always | Strong persistent server-side signing secret. Changing it invalidates verification of existing locally signed records. |
| `ISSUER_KEY_ID` | Optional | Stable identifier for the local signing key. |
| `TRUSTED_ISSUER_PUBLIC_KEYS_JSON` | Optional | JSON mapping of trusted issuer key IDs to public keys. |
| `CORS_ORIGINS` | Production | Comma-separated exact website origins, including scheme; configure the deployed Netlify origin. |
| `DATABASE_URL` / `DATABASE_PATH` | Always | Current app uses SQLite. The database must be on durable storage and included in backups for production. |
| `BLOCKCHAIN_MODE` | Always | `disabled` is off-chain mode; use `required` only after a deployed ledger and provider authorization are configured. |
| `BLOCKCHAIN_RPC_URL`, `BLOCKCHAIN_CHAIN_ID`, `RIGHTS_LEDGER_ADDRESS` | Chain mode | Backend connection details for the configured EVM ledger. |
| `BLOCKCHAIN_SENDER_ADDRESS` or `BLOCKCHAIN_PRIVATE_KEY` | Chain writes | Configure the authorized provider signer server-side; never expose a private key to the browser. |
| `QPIAI_OPT_API_KEY` | Optional | Enables authenticated local QpiAI Opt; hosted platform solving is not enabled by this configuration. |
| `QCLOUD_API_KEY` | Optional | Quantum integration credential; configure only when those features are intentionally used. |

The current `render.yaml` does not provision durable SQLite storage or a managed database. Render's free service filesystem is ephemeral, so restarts or redeploys can lose registry, audit, and decision data. Select and validate durable storage before production use. `CORS_ORIGINS` and `QPIAI_OPT_API_KEY` are manual Render settings: enter the exact Netlify origin and, only if enabling the QpiAI local optimizer, configure its server-side credential. The blueprint installs the pinned QpiAI Opt adapter but does not enable hosted platform solving. Netlify must separately set `VITE_API_BASE_URL` to the backend HTTPS URL. `frontend/.env.production.example` is a placeholder, not a deployable URL.
