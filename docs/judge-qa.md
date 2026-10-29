# Judge Q&A

## What problem does BhashaChain address?

Teams selecting multilingual training corpora need to evaluate whether each record permits the requested purpose, region, derivatives, and redistribution, while retaining an auditable decision trail. BhashaChain demonstrates those checks and applies eligibility before dataset optimization.

## What is actually on-chain?

The Solidity ledger stores a dataset identifier hash, content hash, issuer address, numeric licence version, permission terms, expiry, revocation state, and registration timestamp. The full corpus and API credentials remain off-chain. A registration or mutation is reported as confirmed only after a successful receipt, expected event, and state readback.

## What happens if the chain is unavailable?

In `required` mode, an unavailable chain, missing record, state mismatch, or denied on-chain permission rejects the request. In explicit `disabled` mode, local signature and policy checks still run, but chain evidence is labeled disabled and is never presented as verified.

## Who signs the local rights record?

The API signs records with a local Ed25519 key derived from `ISSUER_SIGNING_SECRET`. That demonstrates record integrity and which configured service key signed it. It does not establish that a real-world data provider authorized that key. A deployment should register provider public keys in `TRUSTED_ISSUER_PUBLIC_KEYS_JSON` and define a provider onboarding process.

## How does dataset selection work?

The backend first evaluates actual registered records against the signed rights policy and, when configured, the chain. Ineligible records are excluded. Then the QpiAI Opt adapter and an independent exact classical baseline receive the eligible set. The interface reports each solver's mode and result separately. When QpiAI is not configured, it says so instead of labeling a fallback result as QpiAI.

## What does the demo's optimizer result show?

The regression fixture for languages `bn,ta`, budget `1000`, purpose `commercial_training`, and geography `IN` selects `bn-open-01` at 120 and `ta-commercial-03` at 160, for a total of 280. Both the authenticated QpiAI Opt 0.0.9 local MILP solve and the independent classical baseline returned this result. The QpiAI SDK verified the key online and solved with its local runtime; platform mode and fallback were disabled.

## Does revocation delete data already downloaded by a licensee?

No. Revocation updates the registry and rejects later checks. This prototype cannot retrieve or erase copies already downloaded elsewhere.

## Has it been deployed publicly?

No. The local UI and local API have been exercised, including a disposable local Hardhat chain. Netlify and Render configuration is prepared, but public deployment requires connected hosting accounts, a selected durable database, CORS settings, and repository publication.
