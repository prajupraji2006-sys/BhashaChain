# Public demo deployment: Render + Netlify

This guide describes the currently prepared **off-chain demo**. It does not claim public blockchain verification. The Render blueprint uses the free web-service plan and SQLite on the service filesystem; registry, decision, and audit data can be lost when the service restarts or redeploys. Do not store important records until durable storage and backups are configured.

## What is configured

- Render builds from the repository root with `pip install -r backend/requirements.txt -r backend/requirements-qpiai-opt.txt`, starts `backend.app.main:app` on Render's `$PORT`, and checks `/health`.
- Production starts with `APP_ENV=production`, generated `API_ACCESS_TOKEN` and `ISSUER_SIGNING_SECRET`, and `BLOCKCHAIN_MODE=disabled`.
- Netlify builds from `frontend/` and publishes `dist/`. Its `/api/*` and `/health` proxy rules forward to the Render service before the SPA fallback routes other paths to `index.html`.
- Production frontend API calls use relative paths on the Netlify origin, so the browser does not call Render cross-origin. Local development continues to use `http://localhost:8000` by default; `VITE_API_BASE_URL` can override that development URL.

## 1. Deploy the backend on Render

1. Make the reviewed deployment changes available on the GitHub branch you will deploy. The Render and Netlify dashboards build the GitHub version, not uncommitted local files.
2. In Render, choose **New → Blueprint** and connect `prajupraji2006-sys/BhashaChain`. Select the intended branch and apply `render.yaml`. If using **New → Web Service** instead, use the repository root as the root directory and copy the build, start, and health-check settings from `render.yaml`.
3. Keep the service on the free plan only if you accept ephemeral SQLite storage and possible free-instance spin-down. No persistent disk is configured.
4. In the service's **Environment** settings, enter `CORS_ORIGINS` as a temporary exact origin such as `https://placeholder.netlify.app`; replace it after the Netlify site has a URL. An origin includes `https://` and has no path or trailing slash.
5. Keep Render's generated `API_ACCESS_TOKEN` and `ISSUER_SIGNING_SECRET` values. Do not copy them into the frontend build settings or GitHub.
6. `QPIAI_OPT_API_KEY` is optional and is only set in Render's protected environment settings when enabling QpiAI. Without it, optimization remains usable through a separately labeled classical fallback. Local QpiAI execution verifies the Opt key online but does not submit a hosted job.
7. Leave blockchain RPC, chain ID, contract address, and signer variables unset in this off-chain launch. The app will report `blockchain: disabled`. Registration and rights decisions are local signed-record operations; updates and revocations requiring an on-chain ledger will be unavailable.
8. Wait for the deployment to become healthy. Record the Render service's HTTPS URL; this is the backend URL. Check `https://<render-service>.onrender.com/health`. `/health` verifies SQLite availability and reports the chain state separately.

## 2. Deploy the frontend on Netlify

1. In Netlify, choose **Add new site → Import an existing project** and connect the same GitHub repository and branch.
2. Use the existing `netlify.toml` settings: base directory `frontend`, build command `npm run build`, publish directory `dist`.
3. Keep the production `VITE_API_BASE_URL` unset; production requests use the same-origin proxy in `netlify.toml`. The proxy targets the actual backend URL `https://bhashachain-api.onrender.com`.
4. Deploy the site and record its HTTPS origin, for example `https://<site-name>.netlify.app`.
5. In Render, set `CORS_ORIGINS` to the exact Netlify origin (including `https://`, without a trailing slash) and wait for any configuration-triggered restart. CORS is not a substitute for API authentication; the same-origin proxy does not remove bearer-token checks.
6. If you add another Netlify domain, update `CORS_ORIGINS` to include that exact origin, comma-separated with any other authorized origins.

## 3. Verify the connected public app

1. Open the Netlify site and confirm the overview reports API availability and `Chain disabled`. The blockchain panel explicitly marks decisions as off-chain and not public blockchain verification.
2. For protected writes, enter the Render-generated `API_ACCESS_TOKEN` in the website's password field and select **Connect**. It is held in browser memory only. Verify `/api/auth/check` through the UI.
3. Confirm seeded datasets load. Check an allowed sample such as `bn-open-01` for `commercial_training` in `IN`; verify the returned blockchain status says `disabled`.
4. Register a synthetic dataset, refresh the page, make a rights decision, and check the audit trail and `/api/audit/integrity`. These records are persisted only for the lifetime of the ephemeral Render filesystem.
5. Test facility dispatch with the supplied synthetic request. With no QpiAI key the response must identify `classical_exact_qubo_fallback`; with a configured Opt key it may identify `qpiai_opt` only when the SDK returns a usable local solution. Platform execution stays disabled.
6. Dataset registration, decisions, API connectivity, and audit checks are not proof of on-chain verification. Contract-backed updates/revocations are disabled until a real compatible ledger is deployed and configured.

## Environment variables

| Variable | Where | Purpose |
| --- | --- | --- |
| `APP_ENV=production` | Render | Enforces production write authentication and rejects local Hardhat RPC. |
| `PYTHON_VERSION=3.11.9` | Render | Selects the Python runtime used by the blueprint. |
| `PORT` | Render, provided by platform | Uvicorn binds to the service-provided port. Do not set a fixed port. |
| `API_ACCESS_TOKEN` | Render, generated | Shared bearer token required by write routes. Never use a `VITE_` name. |
| `ISSUER_SIGNING_SECRET` | Render, generated and stable | Signs local registry records; keep the value stable across restarts. |
| `ISSUER_KEY_ID` | Render, optional | Stable identifier for the local signing key; defaults safely if unset. |
| `TRUSTED_ISSUER_PUBLIC_KEYS_JSON` | Render, optional | JSON mapping of explicitly trusted signing key IDs to public keys. |
| `CORS_ORIGINS` | Render | Exact HTTPS Netlify origin(s), comma-separated. |
| `BLOCKCHAIN_MODE=disabled` | Render | Explicit off-chain launch; does not claim public chain verification. |
| `DATABASE_PATH` or `DATABASE_URL` | Render, optional | `DATABASE_PATH` selects the SQLite file; `DATABASE_URL` also accepts SQLite paths only, not PostgreSQL URLs. The default file is ephemeral on this free deployment. |
| `QPIAI_OPT_API_KEY` | Render, optional | Enables authenticated QpiAI Opt local solves. If absent or failing, fallback stays separately labeled. |
| `QCLOUD_API_KEY` | Render, optional | Only for intentionally enabled QpiAI Quantum features; keep server-side. |
| `VITE_API_BASE_URL` | Local development, optional | Development API URL override. Production ignores this setting and uses same-origin Netlify proxy paths. Never put API tokens or private keys in Vite variables. |
| `BLOCKCHAIN_RPC_URL`, `BLOCKCHAIN_CHAIN_ID`, `RIGHTS_LEDGER_ADDRESS` | Render, only after approved testnet setup | Identify the reachable non-local RPC and already deployed compatible ledger. Not needed in off-chain mode. |
| `BLOCKCHAIN_PRIVATE_KEY` or `BLOCKCHAIN_SENDER_ADDRESS` | Render, only after approved testnet setup | Backend transaction signer. Keep private keys in Render secrets; a public sender address is not a signing credential. |

## Persistent SQLite and blockchain follow-up

To keep SQLite data across redeployments, approve a Render plan that supports a persistent disk, mount it at `/var/data`, set `DATABASE_PATH=/var/data/bhashachain.db`, and add tested backups. The current backend is SQLite-specific; a PostgreSQL URL is not supported.

The Hardhat scripts in this repository currently deploy/manage providers on the local network only. A testnet launch needs an explicitly selected EVM testnet, RPC endpoint, chain ID, funded test wallet, a reviewed testnet deployment/authorization path, contract address, and authorized backend signer. Do not configure production with `localhost:8545` or chain ID `31337`. No contract has been deployed by this guide; mainnet deployment and real-fund transactions require separate explicit approval.
