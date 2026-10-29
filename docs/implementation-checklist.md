# Implementation checklist

- [x] Review the existing API, policy engine, database, optimizers, frontend, Solidity contract, and tests.
- [x] Add Ed25519 versioned records, trusted-key verification support, and fail-closed policy checks.
- [x] Add chained audit event hashes and deterministic accepted/rejected manifests.
- [x] Add explicit disabled/optional/required chain modes; required mode rejects missing or mismatched chain state.
- [x] Check transaction receipt, expected event, and current contract state for registry mutations.
- [x] Run a local Hardhat end-to-end check: registration confirmed, rights check accepted, update confirmed, revocation confirmed, later check rejected, receipt confirmed, three registry events found (chain ID 31337).
- [x] Filter optimizer candidates through rights checks and enforce mandatory selections before solver execution.
- [x] Keep the QpiAI adapter distinct from the exact classical baseline; do not run remote jobs during routine checks.
- [x] Provide a production API-token input in the website; retain the token only in page memory.
- [x] Prepare Netlify and Render configuration and document remaining host/storage requirements.
- [x] Python suite: 11 passed, 3 external QpiAI Quantum tests skipped.
- [x] Frontend production build passed after the latest UI/API-token change.
- [x] Solidity suite: 4 passing.
- [ ] Publish to GitHub and deploy publicly. No remote or commits exist yet; repository name/visibility and connected hosting accounts are needed.

The local Hardhat node used for the smoke check was stopped after verification. The existing localhost website and API were left running for the browser preview.
