# Implementation and evidence matrix

This matrix distinguishes implemented behavior from work that needs a connected host or external credentials.

| Capability | Implementation | Verification/evidence | Status and limits |
|---|---|---|---|
| Signed rights records | Ed25519 v2 records, version metadata, tamper checks, legacy v1 reads | `backend/tests/test_core.py`; live API smoke check | Verified for the local service signing key. A service signature does not prove an external provider's real-world identity; configure trusted issuer keys for that. |
| Purpose, geography, expiry and revocation checks | Fail-closed Python policy engine; optional/required chain modes | Python suite and local-chain end-to-end run | Verified locally. `BLOCKCHAIN_MODE=disabled` is explicitly reported as disabled. |
| Rights ledger | Solidity registry stores content hash, issuer, version, terms, expiry and revocation | `contracts/test/RightsLedger.ts`; local Hardhat end-to-end run | Local chain only. No public testnet/mainnet transaction was submitted. |
| Transaction evidence | Receipt status, expected event and registry readback; registry, event and receipt API endpoints | Local Hardhat run: registration, update and revoke confirmed; 3 events; chain ID 31337 | Confirmed only against the temporary local chain. |
| Classical optimizer | Exact constrained search, real-record eligibility filtering and mandatory-record validation | Python regression test: `bn-open-01` + `ta-commercial-03`, total 280 under budget 1000 | Verified locally. |
| QpiAI Opt | Pinned SDK 0.0.9; explicit local MILP mode; platform fallback disabled | Authenticated local regression selected `bn-open-01` + `ta-commercial-03`, cost 280; API response and classical comparison verified | SDK performs online key verification, then runs the model in its local runtime; no platform job was submitted. |
| Quantum experiment | Optional QpiAI Quantum simulator route | Three external integration tests are opt-in and skipped by default | No remote QCloud job was run. |
| Decision manifests and audit | Deterministic content hash/manifest IDs; chained audit event hashes | Python suite verifies manifest hashes and detects audit tampering | Local SQLite/JSON persistence. A hash chain detects edits but is not an external immutable anchor. |
| Web interface | React/Vite rights dashboard, registry, checks, optimization, quantum and audit pages | Production build succeeds; localhost site and API returned HTTP 200; browser opened at `http://127.0.0.1:5173/` | Local demonstration is available. Hosting has not been connected or deployed. |
| Production deployment | Netlify and Render configuration files prepared | Config files included in repository | Not deployed. Requires connected accounts, deployed API origin, CORS configuration, and persistent database choice for durable records. |
| GitHub publication | — | Repository has no commits and no remote | Not published. Need repository name and public/private setting, plus GitHub connection. |

## Reproduction commands

From the repository root on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
Set-Location frontend; npm.cmd run build
Set-Location ..\contracts; npm.cmd test
```

For the real local-chain path, follow [installation.md](installation.md). Use only disposable local Hardhat accounts for this demo.
