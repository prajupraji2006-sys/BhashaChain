# RightsLedger

From PowerShell in this folder:

```powershell
npm.cmd install
npm.cmd run compile
npm.cmd test
npm.cmd run node
```

In another terminal, deploy to the local node:

```powershell
npm.cmd run deploy:local
```

The compile command also syncs the generated ABI to `backend/data/rights_ledger_abi.json`. Copy the deployed address and set it with the local RPC URL, chain ID `31337`, and `BLOCKCHAIN_SENDER_ADDRESS` set to one of the node's unlocked account addresses in the root `.env`. This avoids copying a development private key into the app. Keep the local node running while the API uses it; a restart clears chain state and requires redeployment.

## Authorize the first dataset provider

The deployer is the contract owner, but is **not** automatically a dataset provider. Registration is rejected until the owner explicitly authorizes the backend's transaction signer. For the unlocked local-account setup, that is `BLOCKCHAIN_SENDER_ADDRESS`; if `BLOCKCHAIN_PRIVATE_KEY` is configured, authorize the address derived from that server-side key instead. From PowerShell in this folder, set the deployed address and actual provider address:

```powershell
$env:RIGHTS_LEDGER_ADDRESS = "0xYOUR_DEPLOYED_LEDGER_ADDRESS"
$env:DATASET_PROVIDER_ADDRESS = "0xYOUR_BACKEND_SIGNER_ADDRESS"
$env:PROVIDER_ACTION = "authorize"
npm.cmd run provider:access
```

The script submits the owner-only authorization transaction and verifies `authorizedProviders(provider)` by readback. Run it again with `$env:PROVIDER_ACTION = "revoke"` to stop that provider from registering new records. The authorization script only permits the `localhost` Hardhat network. Clear the temporary variables with `Remove-Item Env:RIGHTS_LEDGER_ADDRESS,Env:DATASET_PROVIDER_ADDRESS,Env:PROVIDER_ACTION` when finished. Do not put private keys in these variables.

After authorization, configure the backend to use the same provider address and contract, set `BLOCKCHAIN_MODE=required`, and restart the API. In any chain-enabled mode, registration is not persisted unless the transaction receipt, registration event, content hash, version, and on-chain issuer address all verify. The provider must use its authorized account for later licence updates and revocations.

`RightsLedger` records a deterministic dataset ID hash, content hash, issuer, numeric licence version, expiry, purpose/region hashes, rights flags, revoked status, and registration timestamp. The deployer is the only account that can authorize or revoke provider registration access. Only authorized providers can register; only the issuer can update or revoke an existing record. Tests cover provider grants/revocation, unauthorized registration and role grants, duplicate and invalid inputs, expiry, unauthorized changes, licence revocation, and hash verification.

## Upgrading a previous local deployment

This contract is not a proxy and the previous deployed bytecode cannot gain the new allowlist. The V2 Ignition module creates a fresh ledger. Restarting a Hardhat node clears chain state; compile, deploy V2, authorize the backend signer, and update the root `.env` contract address. Existing SQLite rows remain on disk but are not registered in the new ledger, so `BLOCKCHAIN_MODE=required` will reject them until they are deliberately migrated/re-registered. Back up the SQLite database and audit/manifests before any reset; do not delete or overwrite `.env`. The API currently rejects duplicate local dataset IDs, so re-registration requires a planned data migration or a fresh database populated from reviewed records. Do not treat old-chain receipts as evidence for the new address.

This is a local prototype. Do not use a real wallet key or deploy it as a production rights system without a security review.
