# API contract

- `GET /health`: API/database state, truthful blockchain connection status and chain ID when connected, and QpiAI configuration indicators.
- `GET /api/datasets`, `GET /api/datasets/{dataset_id}`: signed local records and optional on-chain transaction evidence.
- `POST /api/datasets`: register metadata. Required fields: `dataset_id`, 64-hex `content_hash`, `language`, `licence_version`, `issuer`, nonempty `purposes` and `regions`, `expires_at` (future ISO 8601), and nonnegative `licensing_cost`. Derivative and redistribution flags default false. If the chain signer is configured, this also submits a registry transaction.
- `POST /api/datasets/{dataset_id}/update`: update `content_hash`, higher `licence_version`, purpose/region lists, flags, and future `expires_at`. Contract issuer authorization applies.
- `POST /api/datasets/{dataset_id}/revoke`: revoke on-chain and synchronize the local signed record only after a successful receipt, expected event, and state readback.
- `POST /api/decisions/check`: `{dataset_id,purpose,geography,content_hash?,licence_version?,derivatives?,redistribution?}`. Persists an `ACCEPT|REJECT` decision, reasons, transaction reference when available, and separate blockchain verification details.
- `POST /api/optimization/run`: `{languages,budget,mandatory_dataset_ids?,geography?,purpose?}`. Returns eligible/excluded datasets, all constraints, QpiAI Opt diagnostics, and a separate classical result.
- `POST /api/qubo/dispatch`: `{jobs:[{job_id,chemistry,units}],facilities:[{facility_id,name,capacity,chemistries,cost_per_unit}]}`. Returns solver status, actual execution mode, assignments, QUBO diagnostics, and distinct QpiAI/fallback status. Valid infeasible or unavailable solves remain HTTP 200 with no fabricated facility; invalid input is HTTP 422. See `docs/qpi_ai_opt/README.md`.
- `POST /api/quantum/run`: optional local simulator status/result.
- `GET /api/manifests/accepted`, `/api/manifests/rejected`: persisted decision manifests.
- `GET /api/manifests/needs-review`: persisted rights-lab review manifest.
- `POST /api/rights-lab/import`: validate and persist CSV metadata plus a 20–50 row sample; requires `headline` and `label` columns and a SHA-256 value.
- `GET /api/rights-lab/datasets`, `POST /api/rights-lab/datasets/{dataset_id}/evidence`: view intake metadata and update its review evidence.
- `POST /api/rights-lab/datasets/{dataset_id}/store-original`: explicitly save a matching CSV (25 MB maximum) under Git-ignored `backend/private_data/`; ordinary imports do not send the complete source file.
- `POST /api/rights-lab/check`: returns `ALLOWED`, `REJECTED`, or `NEEDS_REVIEW`; ALLOWED requires the complete evidence policy plus a matching signed schema-v3 provider record and verified on-chain registry state.
- `GET /api/rights-lab/benchmarks`: synthetic evidence-policy fixtures only; these do not represent real data or chain transactions.
- `GET /api/rights-lab/history`, `/api/rights-lab/accepted-corpus`: decision history and sample rows eligible only after signature and chain verification.
- `GET /api/audit`, `GET /api/audit/{decision_id}`, `GET /api/audit/events`: rights decisions and registry/optimizer activity.

An unconfigured chain results in `not_submitted`, never a simulated transaction. A connected chain with no matching registered record reports a mismatch or missing chain record. HTTP 409 from update/revoke includes the chain failure state; a local record is not silently changed when a transaction fails.
