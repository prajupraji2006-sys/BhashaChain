# Judge demo script

## Prepare

1. Start Hardhat, compile, deploy, configure `.env`, and restart FastAPI using the root README commands.
2. Open the frontend and show health. Point out the connected local chain ID and confirm the chain status is distinct from the local API status.
3. In the Datasets page, register a unique test dataset ID such as `gu-demo-2026`, language `gu`, a 64-character SHA-256 value, purpose `research,commercial_training`, region `IN`, and a future expiry.
4. Show the returned mined transaction hash, block number, gas used, event result, and content-hash state verification. Refresh the dataset list and show the chain status.

## Walk through rights and optimization

5. Check the new dataset for commercial training in India; show the persisted decision ID and blockchain verification. Change geography or purpose to a value outside its licence and show the rejection reason.
6. Try checking a seeded record while the chain is connected. Because seeded examples are local only, it should show a missing chain record; register test records explicitly before claiming on-chain verification.
7. Open Optimizer. Enter `bn,ta`, budget `1000`, no mandatory IDs, geography `IN`, and purpose `commercial_training`. The seeded regression fixture should give the classical baseline `bn-open-01` plus `ta-commercial-03`, cost `280`. QpiAI Opt runs only if its configured SDK/key are available and displays its actual mode and diagnostics.
8. Open Audit trail and inspect the check decisions plus registration/optimization events.

## Update, revoke, and verify access control

9. Use Update for the registered record. Enter a higher licence version and a new 64-character metadata hash. Show transaction and updated contract state.
10. Revoke the record. The backend changes its local signed status only after a successful receipt, event, and readback.
11. Check it again and show the rejection. The decision includes local policy reasons and the observed on-chain revocation state.
12. Run `npm.cmd test` in `contracts` to demonstrate that an unauthorized signer cannot update or revoke another issuer's record, duplicates are rejected, and repeat revocation is blocked.
13. Stop Hardhat and refresh `/health` or submit a check. Show the explicit unavailable chain state; the app does not invent a transaction or green verification.

The prototype does not claim legal ownership or prevent reuse of downloaded corpus data. Do not use real wallet keys or public-chain transactions for this demonstration.
