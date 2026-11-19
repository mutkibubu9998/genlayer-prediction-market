# PredictionMarket — GenLayer Intelligent Contract

A YES/NO prediction market resolved by GenLayer consensus: validators use an
LLM plus live web evidence to settle real-world events, and winners are paid
out on-chain. Built for GenLayer Builder points (Season 2). Free to build,
test and deploy to StudioNet — no GEN, no faucet, no paid steps.

## What it does

- **Anyone can create a market** on a verifiable real-world event
  (`create_market(question, evidence_url, deadline_ts)`), with a deadline in
  the future and an `http(s)` evidence page the validators can fetch.
- **Anyone can stake** GEN on YES or NO before the deadline
  (`stake(market_id, side)`), one stake per bettor per market, 1–1000 GEN.
- **After the deadline, anyone can resolve** the market
  (`resolve_market(market_id)`). The leader fetches the evidence page and
  asks an LLM for a strict JSON verdict (`YES` / `NO` / `VOID`); every
  validator independently re-fetches the page and re-runs the LLM, and the
  outcome is accepted only if it matches exactly. A market with no winning
  stakes, or a `VOID` verdict, voids so everyone is refunded.
- **Winners claim pro-rata** from the pot (`claim(market_id)`); losers claim
  0 but the claim is recorded. Each stake can be claimed once.

## How resolution stays honest

- Leader and validator functions are separate: the validator re-runs the
  whole web + LLM pipeline and requires an exact `outcome` match.
- LLM output is parsed defensively: non-JSON, missing fields, bad outcome
  values and low-confidence verdicts fail closed (`[LLM_ERROR]`, which
  forces leader rotation instead of a wrong settlement).
- Error prefixes follow the GenLayer convention: `[EXPECTED]` (business
  logic, deterministic), `[EXTERNAL]` (evidence page 4xx),
  `[TRANSIENT]` (network/5xx), `[LLM_ERROR]` (bad model output).
- All storage writes and payouts happen outside the nondeterministic block,
  so state is only mutated after consensus.

## Contract

- `contracts/prediction_market.py` — `PredictionMarket` (9 methods: 5 view,
  4 write). Storage: `TreeMap[str, Market]`, nested
  `TreeMap[str, TreeMap[Address, Stake]]`, `market_count`, `market_ids`.
- Pinned runner `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`
  (never `test`/`latest`/unversioned).

## Tests

```bash
export PATH="$HOME/.local/bin:$PATH"
genvm-lint check contracts/prediction_market.py --json   # lint
python3 -m pytest tests/direct/ -v                       # direct mode (mocked web/LLM)
glsim --port 4000 --validators 5 --no-browser &          # local simulator
gltest tests/integration/ -v -s --network localnet       # GLSim consensus
```

Direct tests: 9 passed. Integration tests: 3 passed (full
stake → resolve → claim flow, VOID refunds, resolve-before-deadline fails).

### Local tooling notes (glsim / genlayer-test 0.29.2)

Two bugs in the installed tooling were worked around locally (see the
`NOTE (local fix ...)` comments in the patched files):

1. `glsim/engine.py` `deploy()`: it cached the calldata-proxy class instead
   of the real contract class, so a second deploy of the same code failed
   with "class is not marked for usage within storage" and schema
   extraction returned empty methods. Fixed by unwrapping the proxy before
   caching the class.
2. `glsim/server.py` `_rpc_eth_send_raw_transaction()`: the tx's native
   value was never forwarded to the VM, so `gl.message.value` was always 0
   and every payable call reverted. Fixed by setting `engine.vm.value` and
   moving the value in the VM balances for the call.
3. The contract source must stay pure ASCII: `genlayer_py`'s
   `get_contract_schema_for_code` hex-encodes the source with an ASCII
   codec, so any non-ASCII character (e.g. an em-dash in a comment) makes
   every schema fetch fail.

`genvm-lint` downloads its GenVM tarball to `~/.cache/genvm-linter/`; the
direct test runner looks in `~/.cache/gltest-direct/` and tries to download
`v0.3.0-rc7` (404) when empty — seed it with the v0.2.16 tarball:
`cp ~/.cache/genvm-linter/genvm-universal-v0.2.16.tar.xz ~/.cache/gltest-direct/`.

## Deploy (StudioNet, gasless)

Deployed 2026-11-19 to StudioNet (gasless, 0 GEN):

- **Contract address:** `0x0170f655B02435d3fA95fd883d43e57F7beAfe71`
- **Deploy tx hash:** `0x0f06c30d8e01a2b74bbb3ddf4d3817f22828c255c7b994262c4a32a7ca467b7c`
- **Studio:** https://studio.genlayer.com/ (GenLayer Studio Network)
- **Deployer account:** `genlayer-builder`
  (`0x964a26eae6b98b0b14de7e42175110f50d6e5559`)
- Verified on-chain: `genlayer schema` lists all 9 methods,
  `genlayer code` matches this repo, `get_market_count` returns 0.

```bash
genlayer account create --name genlayer-builder
genlayer account set-network studionet   # or: genlayer --network studionet ...
genlayer deploy --code contracts/prediction_market.py --account genlayer-builder
genlayer schema --address <address>
genlayer code --address <address>
genlayer receipt --tx <tx-hash>
```

No Bradbury deploy, no faucet claim — those need GEN / 0.01 ETH on mainnet
and are out of scope for this free build.

## Frontend (Project — live app)

A static single-page app that talks to the deployed StudioNet contract
directly through `genlayer-js` — no backend, no fake data:

- **Live:** https://mutkibubu9998.github.io/genlayer-prediction-market/
- **Source:** `frontend/` (Vite + `genlayer-js` 1.1.8; build output in `docs/`,
  served by GitHub Pages from `main` / `docs`)
- Lists markets live from `list_markets`, shows question / evidence /
  deadline / status / outcome / YES-NO totals / pool balance; create a market,
  stake YES/NO, resolve after the deadline, and claim — all as real StudioNet
  transactions. Reads need no wallet; writes use MetaMask (GenLayer Studio
  network, chain 61999) or a throwaway in-browser demo account.
- Verified end-to-end 2026-11-19 in headless Chromium: page renders live
  state; a demo-account stake of 1 GEN on `mkt_0` was accepted on-chain
  (tx `0xa4a775ae76b005c27e75da08a012becf0c01488190e39fbda0284fe03db5cea0`).
  StudioNet is gasless and 0-GEN accounts can transact, so staking works for
  any visitor. First market `mkt_0` was created the same day via the same
  `genlayer-js` write path (tx `0x0300baf5b492e0c5cd6e7be9854af4b8c70e727bc16a36c24a87052b2b1c00cf`).

```bash
cd frontend && npm install && npm run build   # builds into ../docs
npm run smoke                                   # node read + create_market check
```

## Portal submission

Draft (do NOT submit from here): `../submissions/prediction-market-submission.md`
— Title, Category (Builders), Description, links and tx hash for the user to
paste into the GenLayer Portal later.
