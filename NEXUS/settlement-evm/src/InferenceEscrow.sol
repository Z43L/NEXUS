// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IERC20Settlement {
    function balanceOf(address account) external view returns (uint256);
    function decimals() external view returns (uint8);
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

/// @notice Escrows one aggregate client deposit and pays verified job leaves.
/// @dev A trusted gateway signer attests the root after checking signed receipts
///      off-chain. This contract does not verify Ed25519 worker signatures.
///      Every published batch has a DISPUTE_WINDOW before claims are allowed. A dispute
///      opened inside that window freezes the batch until the owner resolves it. An upheld
///      dispute forfeits the accused node's payout for the disputed job back to the payer.
///      The owner acts as the testnet arbiter; there is no node bond or stake in this contract.
contract InferenceEscrow {
    bytes32 private constant LEAF_DOMAIN = keccak256("NEXUS_INFERENCE_ESCROW_LEAF_V2");
    uint256 public constant BPS = 10_000;
    uint256 public constant NODE_BPS = 7_500;
    uint256 public constant AUTHOR_BPS = 1_000;
    uint256 public constant VERIFICATION_BPS = 500;
    uint256 public constant BURN_BPS = 500;
    uint256 public constant TREASURY_BPS = 500;
    address public constant BURN_SINK = 0x000000000000000000000000000000000000dEaD;
    /// @notice Window between publication and the first moment claims are allowed.
    uint256 public constant DISPUTE_WINDOW = 7 days;
    /// @notice Token units posted by a disputer. Returned if upheld, forfeited to treasury if rejected.
    uint256 public constant DISPUTE_BOND = 1_000;

    IERC20Settlement public immutable token;
    uint8 public immutable tokenDecimals;
    address public immutable owner;
    address public immutable treasury;
    address public immutable verificationPool;
    uint64 public immutable maxClaimWindow;
    address public batchSigner;

    struct Batch {
        address payer;
        bytes32 root;
        uint256 rootSum;
        uint256 remaining;
        uint64 claimDeadline;
        bool published;
    }

    struct JobClaim {
        bytes32 jobId;
        address node;
        address author;
        uint256 amount;
        bytes32[] proof;
        uint256[] proofSums;
    }

    struct Dispute {
        address disputer;
        address node;
        uint256 amount;
        bool resolved;
    }

    mapping(bytes32 => Batch) public batches;
    mapping(bytes32 => mapping(bytes32 => bool)) public claimed;
    // Job IDs are globally unique in the H0 Router ledger. Prevent a verified
    // receipt from being replayed in a later batch as well as in this batch.
    mapping(bytes32 => bool) public claimedJobs;
    // Earliest timestamp at which a published batch may be claimed.
    mapping(bytes32 => uint64) public settleAt;
    // Number of unresolved disputes on a batch. Claims and refunds are frozen while non-zero.
    mapping(bytes32 => uint256) public openDisputes;
    mapping(bytes32 => mapping(bytes32 => Dispute)) public disputes;
    bool private entered;

    event BatchFunded(bytes32 indexed batchId, address indexed payer, uint256 amount);
    event BatchPublished(bytes32 indexed batchId, bytes32 root, uint64 claimDeadline);
    event JobSettled(bytes32 indexed batchId, bytes32 indexed jobId, address node, address author, uint256 amount);
    event BatchRefunded(bytes32 indexed batchId, address indexed payer, uint256 amount);
    event UnpublishedBatchCancelled(bytes32 indexed batchId, address indexed payer, uint256 amount);
    event DisputeOpened(bytes32 indexed batchId, bytes32 indexed jobId, address indexed disputer, address node);
    event DisputeResolved(
        bytes32 indexed batchId, bytes32 indexed jobId, address node, bool nodeFaulted, uint256 slashedAmount
    );
    event BatchSignerChanged(address indexed signer);
    event EscrowConfigured(
        address indexed owner,
        address indexed token,
        address indexed batchSigner,
        address treasury,
        address verificationPool,
        uint8 tokenDecimals,
        uint64 maxClaimWindow
    );

    modifier nonReentrant() {
        require(!entered, "reentrant call");
        entered = true;
        _;
        entered = false;
    }

    constructor(
        IERC20Settlement token_,
        address owner_,
        address signer_,
        address treasury_,
        address verificationPool_,
        uint8 expectedTokenDecimals_,
        uint64 maxClaimWindow_
    ) {
        require(address(token_) != address(0) && address(token_).code.length > 0, "token must be contract");
        require(token_.decimals() == expectedTokenDecimals_, "token decimals mismatch");
        require(
            owner_ != address(0) && signer_ != address(0) && treasury_ != address(0) && verificationPool_ != address(0),
            "zero recipient"
        );
        require(treasury_ != address(this) && verificationPool_ != address(this), "escrow cannot receive fees");
        require(maxClaimWindow_ > 0, "zero claim window");
        token = token_;
        tokenDecimals = expectedTokenDecimals_;
        owner = owner_;
        batchSigner = signer_;
        treasury = treasury_;
        verificationPool = verificationPool_;
        maxClaimWindow = maxClaimWindow_;
        emit EscrowConfigured(
            owner_, address(token_), signer_, treasury_, verificationPool_, expectedTokenDecimals_, maxClaimWindow_
        );
    }

    function setBatchSigner(address signer_) external {
        require(msg.sender == owner, "only owner");
        require(signer_ != address(0), "zero signer");
        batchSigner = signer_;
        emit BatchSignerChanged(signer_);
    }

    /// @notice Client funds the batch before the gateway publishes its verified root.
    function fundBatch(bytes32 batchId, uint256 amount) external nonReentrant {
        require(batchId != bytes32(0) && amount > 0, "invalid batch");
        require(batches[batchId].payer == address(0), "batch already funded");
        uint256 beforeBalance = token.balanceOf(address(this));
        batches[batchId] = Batch(msg.sender, bytes32(0), 0, amount, 0, false);
        emit BatchFunded(batchId, msg.sender, amount);
        require(token.transferFrom(msg.sender, address(this), amount), "fund transfer failed");
        require(token.balanceOf(address(this)) - beforeBalance == amount, "fee token unsupported");
    }

    /// @notice Publish a Merkle-sum root of context-bound V2 job leaves.
    /// @dev Claims open at block.timestamp + DISPUTE_WINDOW. The claim deadline must fall after that.
    function publishBatch(bytes32 batchId, bytes32 root, uint256 rootSum, uint64 claimDeadline) external nonReentrant {
        require(msg.sender == batchSigner, "only batch signer");
        Batch storage batch = batches[batchId];
        require(batch.payer != address(0) && !batch.published, "unknown or published batch");
        require(root != bytes32(0) && rootSum > 0, "empty root");
        require(rootSum <= batch.remaining, "root exceeds funding");
        uint64 windowEnd = uint64(block.timestamp + DISPUTE_WINDOW);
        require(claimDeadline > windowEnd, "deadline inside dispute window");
        require(uint256(claimDeadline) - block.timestamp <= maxClaimWindow, "deadline too far");
        batch.root = root;
        batch.rootSum = rootSum;
        batch.claimDeadline = claimDeadline;
        batch.published = true;
        settleAt[batchId] = windowEnd;
        emit BatchPublished(batchId, root, claimDeadline);
    }

    /// @notice Open a dispute on one job leaf before the batch's dispute window closes.
    /// @dev The leaf must verify against the published root. The disputer posts DISPUTE_BOND,
    ///      and the batch's claims stay frozen until the owner resolves the dispute.
    function openDispute(bytes32 batchId, JobClaim calldata job) external nonReentrant {
        require(batches[batchId].published && block.timestamp < settleAt[batchId], "dispute window closed");
        require(!claimed[batchId][job.jobId] && !claimedJobs[job.jobId], "job already claimed");
        require(disputes[batchId][job.jobId].disputer == address(0), "job already disputed");
        _verifyLeaf(batchId, job);

        uint256 beforeBalance = token.balanceOf(address(this));
        require(token.transferFrom(msg.sender, address(this), DISPUTE_BOND), "bond transfer failed");
        require(token.balanceOf(address(this)) - beforeBalance == DISPUTE_BOND, "fee token unsupported");

        disputes[batchId][job.jobId] = Dispute(msg.sender, job.node, job.amount, false);
        openDisputes[batchId] += 1;
        emit DisputeOpened(batchId, job.jobId, msg.sender, job.node);
    }

    /// @notice Owner (testnet arbiter) resolves an open dispute.
    /// @dev Upheld: the disputed job is consumed, its amount goes back to the payer (the node
    ///      forfeits that payout), and the bond returns to the disputer.
    ///      Rejected: the job stays claimable and the bond goes to the treasury.
    function resolveDispute(bytes32 batchId, bytes32 jobId, bool nodeFaulted) external nonReentrant {
        require(msg.sender == owner, "only owner");
        Dispute storage dispute = disputes[batchId][jobId];
        require(dispute.disputer != address(0) && !dispute.resolved, "no open dispute");
        Batch storage batch = batches[batchId];
        dispute.resolved = true;
        openDisputes[batchId] -= 1;

        uint256 slashed = 0;
        if (nodeFaulted) {
            uint256 amount = dispute.amount;
            require(batch.remaining >= amount, "batch overdrawn");
            batch.remaining -= amount;
            claimed[batchId][jobId] = true;
            claimedJobs[jobId] = true;
            slashed = amount;
            _transfer(batch.payer, amount);
            _transfer(dispute.disputer, DISPUTE_BOND);
        } else {
            _transfer(treasury, DISPUTE_BOND);
        }
        emit DisputeResolved(batchId, jobId, dispute.node, nodeFaulted, slashed);
    }

    /// @notice Anyone may submit a valid leaf; funds always go to the leaf recipients.
    function claim(bytes32 batchId, JobClaim calldata job) external nonReentrant {
        _claim(batchId, job);
    }

    /// @notice Settle multiple job receipts against one batch in a single transaction.
    function claimMany(bytes32 batchId, JobClaim[] calldata jobs) external nonReentrant {
        require(jobs.length > 0, "empty claims");
        for (uint256 i = 0; i < jobs.length; i++) {
            _claim(batchId, jobs[i]);
        }
    }

    function _claim(bytes32 batchId, JobClaim calldata job) private {
        Batch storage batch = batches[batchId];
        require(batch.published && block.timestamp <= batch.claimDeadline, "batch not claimable");
        require(block.timestamp >= settleAt[batchId], "dispute window open");
        require(openDisputes[batchId] == 0, "batch frozen by dispute");
        require(!claimed[batchId][job.jobId] && !claimedJobs[job.jobId], "job already claimed");
        _verifyLeaf(batchId, job);
        require(batch.remaining >= job.amount, "batch overdrawn");
        claimed[batchId][job.jobId] = true;
        claimedJobs[job.jobId] = true;
        batch.remaining -= job.amount;

        uint256 nodeShare = _bps(job.amount, NODE_BPS);
        uint256 authorShare = job.author == address(0) ? 0 : _bps(job.amount, AUTHOR_BPS);
        if (job.author == address(0)) nodeShare += _bps(job.amount, AUTHOR_BPS);
        uint256 verificationShare = _bps(job.amount, VERIFICATION_BPS);
        uint256 burnShare = _bps(job.amount, BURN_BPS);
        // Match H0: floor each percentage share, route an unused author share
        // to the node, and assign all integer-division remainder to treasury.
        uint256 treasuryShare = job.amount - nodeShare - authorShare - verificationShare - burnShare;

        _transfer(job.node, nodeShare);
        if (authorShare != 0) _transfer(job.author, authorShare);
        _transfer(verificationPool, verificationShare);
        _transfer(BURN_SINK, burnShare);
        _transfer(treasury, treasuryShare);

        emit JobSettled(batchId, job.jobId, job.node, job.author, job.amount);
    }

    function _verifyLeaf(bytes32 batchId, JobClaim calldata job) private view {
        Batch storage batch = batches[batchId];
        require(
            job.jobId != bytes32(0) && job.node != address(0) && job.node != address(this) && job.amount > 0,
            "invalid leaf"
        );
        require(job.author != address(this), "escrow cannot receive royalty");
        require(job.proof.length == job.proofSums.length, "proof shape mismatch");
        bytes32 leaf = keccak256(
            abi.encode(
                LEAF_DOMAIN,
                block.chainid,
                address(this),
                address(token),
                batchId,
                job.jobId,
                job.node,
                job.author,
                job.amount
            )
        );
        require(_verifySum(job.proof, job.proofSums, batch.root, batch.rootSum, leaf, job.amount), "invalid proof");
    }

    /// @notice Return any unclaimed aggregate funds to the original payer after expiry.
    function refundExpired(bytes32 batchId) external nonReentrant {
        Batch storage batch = batches[batchId];
        require(batch.published && block.timestamp > batch.claimDeadline, "not expired");
        require(openDisputes[batchId] == 0, "batch frozen by dispute");
        uint256 amount = batch.remaining;
        require(amount > 0, "nothing to refund");
        batch.remaining = 0;
        _transfer(batch.payer, amount);
        emit BatchRefunded(batchId, batch.payer, amount);
    }

    /// @notice Let the payer recover a batch if the gateway never publishes its root.
    function cancelUnpublished(bytes32 batchId) external nonReentrant {
        Batch storage batch = batches[batchId];
        require(batch.payer == msg.sender && !batch.published, "not cancellable");
        uint256 amount = batch.remaining;
        require(amount > 0, "nothing to refund");
        batch.remaining = 0;
        _transfer(batch.payer, amount);
        emit UnpublishedBatchCancelled(batchId, batch.payer, amount);
    }

    function _transfer(address to, uint256 amount) private {
        if (amount == 0) return;
        uint256 escrowBefore = token.balanceOf(address(this));
        uint256 recipientBefore = token.balanceOf(to);
        require(token.transfer(to, amount), "payout failed");
        uint256 escrowAfter = token.balanceOf(address(this));
        uint256 recipientAfter = token.balanceOf(to);
        require(escrowBefore >= escrowAfter && escrowBefore - escrowAfter == amount, "nonstandard token debit");
        require(
            recipientAfter >= recipientBefore && recipientAfter - recipientBefore == amount, "nonstandard token credit"
        );
    }

    function _verifySum(
        bytes32[] calldata proof,
        uint256[] calldata proofSums,
        bytes32 root,
        uint256 rootSum,
        bytes32 leaf,
        uint256 leafSum
    ) private pure returns (bool) {
        bytes32 computedHash = keccak256(abi.encodePacked(leaf, leafSum));
        uint256 computedSum = leafSum;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 sibling = proof[i];
            uint256 siblingSum = proofSums[i];
            require(type(uint256).max - computedSum >= siblingSum, "proof sum overflow");
            uint256 combinedSum = computedSum + siblingSum;
            if (computedHash < sibling) {
                computedHash = keccak256(abi.encodePacked(computedHash, computedSum, sibling, siblingSum));
            } else {
                computedHash = keccak256(abi.encodePacked(sibling, siblingSum, computedHash, computedSum));
            }
            computedSum = combinedSum;
        }
        return computedHash == root && computedSum == rootSum;
    }

    function _bps(uint256 amount, uint256 rate) private pure returns (uint256) {
        return (amount / BPS) * rate + ((amount % BPS) * rate) / BPS;
    }
}
