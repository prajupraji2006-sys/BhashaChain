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

For a local Hardhat-backed API session, set `BLOCKCHAIN_MODE=required`, `BLOCKCHAIN_RPC_URL=http://127.0.0.1:8545`, `BLOCKCHAIN_CHAIN_ID=31337`, `RIGHTS_LEDGER_ADDRESS` to the address printed by the current deployment, and `BLOCKCHAIN_SENDER_ADDRESS` to the provider account authorized above. The backend health endpoint performs live RPC, chain ID, bytecode, RightsLedger ABI, and provider-authorization reads. The Overview page shows these diagnostics; an unset or failed check is shown as unknown/false rather than inferred from non-empty settings. The example environment file contains only the local RPC and chain ID defaults; its contract address and signer remain blank until deployment.

Hardhat's local chain and its accounts are development-only. Contract state is lost when that node is restarted; redeploy and re-authorize the provider, then update the local contract address. Do not use the local address or development accounts on a public network.

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

The separate Facility Dispatch page calls `POST /api/qubo/dispatch`. It models one-facility assignments, capacity slack, and chemistry mismatch penalties as a QUBO. QpiAI Opt runs only with the documented local mode and `allow_platform=False`; if that fails, small problems may use a clearly labeled exhaustive classical QUBO fallback. See [the dispatch integration guide](docs/qpi_ai_opt/README.md) for the request format, solver semantics, safe logs, and synthetic test evidence.

Install the pinned optional adapter with `python -m pip install -r backend/requirements-qpiai-opt.txt`, then set `QPIAI_OPT_API_KEY` only in `.env` to enable QpiAI Opt. The app requests the documented local SDK mode; the SDK verifies the key online but computes locally, with platform execution and fallback disabled. The app does not switch to another solver and call it QpiAI Opt when the SDK or authentication fails. See [docs/qpiai-opt-integration.md](docs/qpiai-opt-integration.md).

## Architecture and demo

- `backend/app`: FastAPI, SQLite, Ed25519 signatures, rights checks, chain adapter, and audit.
- `optimizer`: QpiAI Opt local adapter, facility dispatch QUBO, and independent classical baselines.
- `contracts`: Solidity `RightsLedger`, Hardhat deployment and tests.
- `frontend`: React workflows for registry, rights checks, optimizer, Quantum lab, and audit evidence.
- `docs/`: setup, API, security, architecture, integration notes, and a judge demo sequence.

See [docs/demo-script.md](docs/demo-script.md), [docs/api-contract.md](docs/api-contract.md), [docs/qpi_ai_opt/README.md](docs/qpi_ai_opt/README.md), and [contracts/README.md](contracts/README.md). Raw corpora, private information, and API credentials stay off-chain. On-chain records contain only hashes, permissions, issuer address, version, expiry, status, and timestamps.

## Dataset Rights Lab: Kannada news CSV demo

The Lab accepts the dataset card's CSV structure (`headline`, `label`) and imports a 20–50 row demonstration sample. It previews up to 10 rows, shows filename/row count/columns/source URL, and computes the source file's SHA-256 in the browser. The mirrored [Hugging Face dataset card](https://huggingface.co/datasets/gaurvar/kannada_news) reports Kannada headlines, around 6,300 records, train/validation CSV files, and `CC BY-SA 4.0`; it also marks source provenance information as incomplete. The [Kaggle source listing](https://www.kaggle.com/datasets/disisbig/kannada-news-dataset) and the mirror's claims are not independent proof of the dataset contributors' rights. Do not characterize the dataset as illegally used or as having fully verified provenance.

CC BY-SA 4.0 allows reuse for commercial purposes when its conditions are followed. Attribution is required, and ShareAlike terms apply when adapted material is shared; it is not a blanket prohibition on commercial use. See the [Creative Commons deed](https://creativecommons.org/licenses/by-sa/4.0/deed.en) and [legal code](https://creativecommons.org/licenses/by-sa/4.0/legalcode). The app does not determine which individual articles or contributions are covered by the reported dataset licence.

### Run the demonstration

1. Start FastAPI and the Vite development server using the local commands above.
2. Open **Dataset Rights Lab** and select the downloaded `train.csv` or `valid.csv`. The browser validates the `headline` and `label` columns, previews up to 10 records, and calculates SHA-256. No source CSV is part of this repository.
3. Import a 20–50 row sample. The local-development UI opts into copying the original file under `backend/private_data/`; uncheck the box to send only the sample metadata and rows. The directory is Git-ignored. A remotely configured backend does not upload the full CSV by default. Server-side original storage verifies the hash, CSV headers, row count, and sample rows.
4. Treat all values prefilled from the source card as `UNVERIFIED` / `NEEDS_REVIEW`. The sample is stored as evidence intake, separate from the signed provider registry. Evidence can be updated with notes/statuses, but those operator assertions are not independent rights verification.
5. A review-complete record can be prepared for provider registration. Verify the evidence and fill the actual licence, territory, expiry, provider, and intended-use terms before submitting. New records that attach rights evidence use signed schema v3; existing schema v1/v2 signatures remain readable. The usual authorized-provider and verified-chain registration requirements still apply. The Lab reports `ALLOWED` only after evidence checks, the matching signed rights record, and verified on-chain state all pass. Without those, the final outcome remains `NEEDS_REVIEW` or `REJECTED`.
6. The synthetic benchmark runs five clearly marked fixtures: permitted evidence, incomplete evidence, explicit commercial prohibition, expiry, and revocation. Its `ALLOWED` case demonstrates the evidence-policy layer only; it does not create a chain transaction or enable training. The `/api/rights-lab/accepted-corpus` endpoint supplies only rows whose decision is `ALLOWED` and whose signed record and chain are verified. Rejected and review-pending rows cannot enter it.

The additive SQLite migration creates `rights_lab_datasets` and `rights_lab_decisions` tables at startup; existing tables and records are left intact. Imported sample rows and optional full CSV copies are local data, not Git content. Decision manifests include the source file SHA-256, purpose, decision, reasons, policy version, and timestamp. Manifest content hashes are deterministic. The Lab is a rights-governance prototype, not legal advice or a legal authority.

## Hosting

`netlify.toml` prepares the React website for Netlify; `render.yaml` prepares the FastAPI service for Render. The current deployment configuration is an explicitly off-chain demo on Render's free service: SQLite storage is ephemeral and there is no public contract deployment. The frontend requires Netlify's `VITE_API_BASE_URL` to point to the deployed backend, and Render's `CORS_ORIGINS` must contain the exact deployed frontend origin. Never expose API tokens or wallet keys as `VITE_` variables. See [docs/deployment.md](docs/deployment.md) for exact dashboard instructions, persistence limitations, environment variables, and verification steps.

### Backend and frontend deployment

Use `.env.example` for local development; production secrets belong in the host's protected environment settings. The prepared public demo uses `BLOCKCHAIN_MODE=disabled` until an approved testnet contract and signer are configured. The Render free filesystem is ephemeral, so its SQLite records are not durable. See [docs/deployment.md](docs/deployment.md) for the full Render/Netlify setup, environment variable reference, health checks, and safe testnet requirements.
