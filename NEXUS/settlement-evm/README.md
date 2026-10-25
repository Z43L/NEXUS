# NEXUS aggregate inference settlement (Base EVM)

An isolated Foundry project for the H1 escrow vertical described in `docs/spec-fusion-nexus-atenea.md` §§7–9 and 11. It does not modify or import the legacy contracts.

## Scope

- Clients fund one ERC-20 batch escrow.
- A configured gateway signer publishes a Merkle-sum root of verified job receipts before a bounded deadline. The committed sum cannot exceed the funded batch.
- Anyone can submit valid `(batchId, jobId, node, author, amount)` leaves and proofs through `claimMany` in one transaction (or use `claim` for an individual leaf). A job can be claimed once.
- Each claimed amount is split in ERC-20 base units: 75% to the worker, 10% royalty to the author when present (otherwise the unused 10% goes to the worker), 5% verification pool, 5% dead-address sink, and 5% treasury. Percentage shares are floored independently; remaining integer dust goes to treasury. The EVM split is authoritative after converting the total price into token base units. H0's signed `shares` are accounting amounts in whole micro-USD and can differ below one micro-USD because H0 rounds each share at lower precision.
- After expiry, the original payer can reclaim the remaining unclaimed batch balance.
- The payer can cancel and recover a funded batch before the gateway publishes a root.

## Trust and accounting boundaries

The gateway signer is trusted to validate the off-chain worker receipts and construct the batch root. The spec uses Ed25519 worker signatures, which this EVM contract does **not** verify; its signer attests to receipts off-chain. A compromised signer could authorize incorrect payouts, capped by the amount deposited in the batch. Signer rotation is owner-controlled. No public deployment or token issuance has been performed. A parameterized escrow deployment script exists and is tested only on local Anvil. Dispute resolution, node staking, marketplace registry, and NEX price policy are not implemented in this vertical.

Merkle V2 leaves bind their execution context and use `keccak256(abi.encode(LEAF_DOMAIN, chainId, escrowAddress, tokenAddress, batchId, jobId, node, author, amount))`, where `LEAF_DOMAIN = keccak256("NEXUS_INFERENCE_ESCROW_LEAF_V2")`. This prevents a valid proof from being replayed across chains, escrow deployments, or token contracts. Parent nodes commit both child hashes and their sums, with children sorted by hash. The configured maximum claim window bounds how long a published batch can remain locked. The contract caps the committed root sum and each claim total at the funded amount, and returns unused funds after expiry.

H0 job IDs are globally unique in the Router ledger, and the escrow records a
claimed job ID globally within that contract, preventing a receipt from being
replayed in a later batch at the same deployment. Separate escrow deployments
have separate replay state. Router-native IDs such as `job_000001` are mapped
to a deterministic bytes32 key using Ethereum Keccak-256 over a domain tag,
the canonical signed receipt and its Ed25519 signature. This keeps the same
receipt's key stable across batches while separating identical local counters
from different receipts. CLI output includes a `sourceReceipts` index back to
the original Router job ID and node ID. The escrow constructor reads the ERC-20
`decimals()` and requires it to match the expected value supplied at deploy
time. The offline bridge still relies on the operator to set the rational
USD/token price correctly and to use the same token contract and chain for the
escrow. It verifies the signed H0 micro-USD `shares` as receipt accounting, but
the contract splits the converted total in token base units, so sub-micro-USD
rounding can differ. Before signing a production root, compare token address,
chain ID, decimals, price source and policy with the deployed escrow; the token
contract does not prove the USD price. The SQLite ledger and registered
public-key table are privileged bridge inputs: protect the database and take
snapshots through a controlled, auditable process before using a production
signer.

The 5% “burn” is transferred to the conventional `0x...dEaD` sink; it is not an ERC-20 supply burn because the contract accepts any ERC-20 and cannot call a token-specific `burn` method. Fee-on-transfer tokens are rejected at deposit. Use a reviewed, non-rebasing token with standard transfer behavior.

## Run locally

With Foundry installed, from this directory:

```sh
forge test -vv
```

### Full receipt bridge → Anvil settlement

The local integration harness starts the actual H0 Router, mock Atenhea engine,
and signed worker as separate processes. It submits two jobs through the Router,
waits for the Router to verify the worker's Ed25519 receipts, invokes
`receipt_to_batch.py` against the resulting Router database, starts a disposable
Anvil node bound exclusively to `127.0.0.1`, deploys a test-only mock ERC-20 and
the escrow, funds and publishes the exact bridge-produced root, then calls
`claimMany`. It checks exact aggregate node and author balances, verification,
burn-sink and treasury balances, and zero remaining escrow. The test policy uses
an explicit synthetic token price and wallet mapping; all generated files are
removed with the temporary directory after the run.

```sh
python3 -m pip install -r ../nexus/h0/requirements-h0.txt
python3 e2e_local.py
```

The first line installs the same pinned `cryptography` dependency used by the
H0 receipt verifier. Use the same Python environment for both commands.

Foundry binaries are detected from `PATH`; optionally set `FORGE_BIN` and
`ANVIL_BIN` to explicit executable paths. This harness never contacts a public
chain. Its deterministic Anvil private key is public test-only material and
must never hold real assets. `src/MockSettlementToken.sol` is test-only and
must never be deployed to a public network. The integration validates local
receipt-to-contract encoding and claim accounting, but does not prove the
operational H0-to-H1 network path, production wallet authorization, token
economics, or Base Sepolia deployment.

The project pins Solidity 0.8.24, has no external Solidity dependencies, and includes tests for split conservation, rounding dust, no-author routing, multi-job aggregate claims, invalid and duplicate claims, sibling-sum tampering, signer authorization, root budget and deadline bounds, unpublished cancellation, fee-on-payout token rejection, large-amount arithmetic, and expired refunds. Base Sepolia deployment remains a later step after local test execution, receipt/root integration, review, and testnet faucet funding.

### Deploy an escrow against an existing token

`script/DeploySettlementEscrow.s.sol` is the non-fixture deployment path. It
requires an explicit expected chain ID, checks the connected chain, token code
and token decimals, deploys only `InferenceEscrow` (never a token), and verifies
the resulting owner, signer, token and claim window. The deployer key becomes
the contract owner; use an appropriately controlled key and record the emitted
deployment event. The script does not send transactions without Foundry's
`--broadcast` flag. Start with a simulation:

```sh
: "${SETTLEMENT_RPC_URL:?Set the RPC URL for the intended chain}"
: "${NEXUS_SETTLEMENT_EXPECTED_CHAIN_ID:?Set the independently verified chain ID}"
: "${NEXUS_SETTLEMENT_DEPLOYER_PRIVATE_KEY:?Load the deployment key securely}"
: "${NEXUS_SETTLEMENT_TOKEN:?Set the reviewed ERC-20 address}"
: "${NEXUS_SETTLEMENT_TOKEN_DECIMALS:?Set the reviewed token decimals}"
: "${NEXUS_SETTLEMENT_BATCH_SIGNER:?Set the gateway signer address}"
: "${NEXUS_SETTLEMENT_TREASURY:?Set the treasury address}"
: "${NEXUS_SETTLEMENT_VERIFICATION_POOL:?Set the verification pool address}"
: "${NEXUS_SETTLEMENT_MAX_CLAIM_WINDOW:?Set the approved claim window in seconds}"
forge script script/DeploySettlementEscrow.s.sol:DeploySettlementEscrow --rpc-url "$SETTLEMENT_RPC_URL"
```

Only after reviewing the simulation, chain ID, token, decimals, owner and
recipients should an operator explicitly add `--broadcast` to that command.
This is a deployment primitive, not an endorsement or automatic Base Sepolia
release: token policy,
signer custody, wallet mappings, funding and root review remain operator gates.

## Build batches from explicit settlement inputs

`batch_builder.py` uses only Python's standard library and emits `settlementContext` alongside `batchId`, `root`, `rootSum`, and `claims`. Context is mandatory and contains a positive integer `chainId`, nonzero `escrowAddress`, and nonzero `tokenAddress`. Inputs also include a bytes32 `batchId`, integer `depositAmount`, and `jobs` containing `jobId` (bytes32), `node` and `author` (20-byte EVM addresses), and positive integer `amount`:

```sh
python3 batch_builder.py settlement-input.json > settlement-batch.json
```

Amounts are raw ERC-20 base units, never decimal token values. The builder rejects malformed values, duplicate job IDs, uint256 overflow, and a job total above the declared deposit. An omitted `author` is encoded as the zero address. The odd final node at a tree level is promoted unchanged, matching the contract's proof format.

### Local H0 receipt bridge

`receipt_to_batch.py` is a read-only local bridge from the H0 Router SQLite
ledger to the batch builder. It selects only rows with the Router database's
`verified=1` flag, then rechecks the Ed25519 signature against the registered
node key, node identity, completed job association, requested-versus-reported NRAM
authors, H0 token pricing, H0 share calculation, and the Router's reported
metering discrepancy. Any inconsistency
aborts the whole batch. Unverified receipts are omitted; if none remain, it
fails. It makes no network calls and never submits a transaction.

Create an explicit policy file (do not copy the example addresses into a real
settlement):

```json
{
  "settlementContext": {
    "chainId": 31337,
    "escrowAddress": "0x3333333333333333333333333333333333333333",
    "tokenAddress": "0x4444444444444444444444444444444444444444"
  },
  "batchId": "0x<64 hex characters>",
  "depositAmount": 1000000,
  "token": {
    "symbol": "USDC",
    "decimals": 6,
    "usdPerTokenNumerator": 1,
    "usdPerTokenDenominator": 1
  },
  "nodeWallets": {
    "node_<exact H0 node id>": "0x<40 hex characters>"
  },
  "authorWallets": {
    "<exact NRAM author identifier>": "0x<40 hex characters>"
  }
}
```

The root is valid only for the exact chain, escrow and token in this object.
Compare these values with the destination contract and ERC-20 before publishing
a root. V1 leaf roots are not accepted by the Python builder.

The token price is the explicit rational `USD per token` (numerator /
denominator); `decimals` declares the ERC-20 base-unit scale. Conversion is
exact: `micro-USD × 10^decimals × price denominator / (1,000,000 × price
numerator)`. A non-integral result is rejected instead of rounded. Each
receipt's `nram_used` must be empty (zero author) or contain exactly one
identifier with an explicit `authorWallets` mapping. Multiple authors are
ambiguous for the contract's single `author` field and cause a hard failure.
Every verified node must have an explicit `nodeWallets` mapping. The final
deposit cap, duplicate job IDs, token amount range and contract Merkle-sum
format are checked by `batch_builder.py`.

Run it against the path printed by `run_h0_local.sh` or the Router's configured
`--dir`:

```sh
python3 receipt_to_batch.py --db /path/to/nexus_h0.db --config settlement-policy.json > settlement-batch.json
```

The Router database contains identities, signatures and accounting metadata;
keep both it and the policy file private. Archive the output with the exact
Router database snapshot and policy used to produce it for auditability. The
bridge cannot independently prove a Router database was not rewritten by a
database administrator; protect its filesystem and retain independent
checkpoints/backups. A prior `verified=1` records that the Router checked the
output hash at completion; since H0 may purge output content under its
retention policy, this bridge relies on that persisted Router decision and
does not claim to re-check purged output content.

Python vectors and tests run with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests_python -v
```

The GitHub Actions workflow runs those tests and `forge test` on pushes and pull requests that touch this vertical. It validates code only; it does not deploy or sign transactions.
