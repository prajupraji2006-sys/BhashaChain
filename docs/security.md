# Security and prototype limits

Canonical dataset metadata is signed with Ed25519 using a key derived from `ISSUER_SIGNING_SECRET`. The default is for local development only; it is not an issuer identity system. Use a strong private secret, protect it, and do not change it after signing records unless records are re-signed.

The backend loads QpiAI keys and the optional chain signer only from server-side environment configuration. `.env` is ignored by Git and excluded from project ZIP archives. Never commit it or put a key in frontend code, logs, or screenshots. Hardhat development keys are public test keys and must never secure real assets.

The contract deployer is the owner and explicitly manages an allowlist of provider accounts. Only allowlisted accounts can register; ordinary accounts cannot grant themselves provider access. Revoking a provider role blocks new registrations but does not remove the issuer's ability to update or revoke records already issued. The contract also enforces issuer-only updates/revocation, duplicate protection, positive version/expiry/hash checks, and expiry/revocation in permission checks. It stores hashes and licence facts only, not corpora or full licence documents.

In chain-enabled modes, the backend persists a registration only after confirming its receipt, event, licence fields, and that the on-chain issuer matches the configured signer. Production API writes require `API_ACCESS_TOKEN`; the token is not an issuer identity system. Explicit `BLOCKCHAIN_MODE=disabled` remains an off-chain local demo mode and reports the chain as disabled.

CORS is not authentication. Production still needs provider identity/onboarding, secure admin key custody, rate limits, monitoring, chain reorg/finality handling, durable backups, independently anchored audit integrity, and a security review. The local provider-management script refuses non-local networks; production provider grants must be performed by the deployed contract owner through an appropriately secured owner wallet.

Blockchain traceability does not establish legal ownership, prove that licence text is enforceable, or prevent reuse of data already downloaded. This prototype is not legal advice.
