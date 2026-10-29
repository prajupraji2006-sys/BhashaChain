# Installation and local demo

Prerequisites: Python 3.10+, Node.js 20+, npm. See the root README for the complete PowerShell sequence. The key safeguards are to create `.env` only if it does not already exist, keep all keys in `.env`, bind FastAPI to `127.0.0.1`, and restart FastAPI after environment changes.

## Local chain

1. In terminal 1, run `Set-Location contracts; npm.cmd install; npm.cmd run node`.
2. In terminal 2, run `Set-Location contracts; npm.cmd run compile; npm.cmd run deploy:local`.
3. Copy the deployed V2 contract address into `RIGHTS_LEDGER_ADDRESS` in the root `.env`; set RPC to `http://127.0.0.1:8545` and chain ID to `31337`.
4. Choose the first provider address. For the local demo this is usually the backend's `BLOCKCHAIN_SENDER_ADDRESS`, set to an unlocked Hardhat development account. If `BLOCKCHAIN_PRIVATE_KEY` is configured, authorize the address derived from that key instead. The deployer is the contract owner, but it does not receive provider rights automatically.
5. From `contracts`, set `RIGHTS_LEDGER_ADDRESS`, `DATASET_PROVIDER_ADDRESS`, and `PROVIDER_ACTION=authorize`, then run `npm.cmd run provider:access`. The script uses the local deployer account, submits the grant, and confirms the on-chain readback. Use `PROVIDER_ACTION=revoke` to stop future registrations by that provider.
6. Set the backend signer to the exact authorized provider address, set `BLOCKCHAIN_MODE=required`, restart FastAPI, and confirm `/health` reports `blockchain: connected` with chain ID 31337.
7. Register a dataset in the UI. A real registration response must contain a confirmed receipt, expected event, matching content hash and version, and issuer address equal to the authorized backend signer. An unverified or unauthorized registration is not persisted.

`npm.cmd run compile` synchronizes the compiled ABI into `backend/data/rights_ledger_abi.json`. A fresh Hardhat node has empty state, so deploy V2 and authorize the provider again after every node restart. V2 is a new non-upgradeable contract; existing on-chain records do not migrate automatically. Back up SQLite before changing the ledger address; old local records will fail required-chain checks until deliberately re-registered or migrated.

## Tests

- Backend: `..\.venv\Scripts\python.exe -m pytest ..\backend\tests -q` from `contracts`, or the equivalent root command in README.
- Frontend: `npm.cmd run build` from `frontend`.
- Contract compile and tests: from `contracts`, run `npm.cmd run compile` and `npm.cmd test`.
- Live QpiAI Quantum tests require `RUN_QPIAI_QUANTUM_INTEGRATION=1`; they are skipped otherwise. A local EVM API smoke test requires the configured chain above.
