# API contract

- `GET /health`: API/database state, truthful blockchain connection status and chain ID when connected, and QpiAI configuration indicators.
- `GET /api/datasets`, `GET /api/datasets/{dataset_id}`: signed local records and optional on-chain transaction evidence.
- `POST /api/datasets`: register metadata. Required fields: `dataset_id`, 64-hex `content_hash`, `language`, `licence_version`, `issuer`, nonempty `purposes` and `regions`, `expires_at` (future ISO 8601), and nonnegative `licensing_cost`. Derivative and redistribution flags default false. If the chain signer is configured, this also submits a registry transaction.
- `POST /api/datasets/{dataset_id}/update`: update `content_hash`, higher `licence_version`, purpose/region lists, flags, and future `expires_at`. Contract issuer authorization applies.
- `POST /api/datasets/{dataset_id}/revoke`: revoke on-chain and synchronize the local signed record only after a successful receipt, expected event, and state readback.
- `POST /api/decisions/check`: `{dataset_id,purpose,geography,content_hash?,licence_version?,derivatives?,redistribution?}`. Persists an `ACCEPT|REJECT` decision, reasons, transaction reference when available, and separate blockchain verification details.
- `POST /api/optimization/run`: `{languages,budget,mandatory_dataset_ids?,geography?,purpose?}`. Returns eligible/excluded datasets, all constraints, QpiAI Opt diagnostics, and a separate classical result.
- `POST /api/quantum/run`: optional local simulator status/result.
- `GET /api/manifests/accepted`, `/api/manifests/rejected`: persisted decision manifests.
- `GET /api/audit`, `GET /api/audit/{decision_id}`, `GET /api/audit/events`: rights decisions and registry/optimizer activity.

An unconfigured chain results in `not_submitted`, never a simulated transaction. A connected chain with no matching registered record reports a mismatch or missing chain record. HTTP 409 from update/revoke includes the chain failure state; a local record is not silently changed when a transaction fails.
