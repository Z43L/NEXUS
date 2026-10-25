// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {InferenceEscrow, IERC20Settlement} from "../src/InferenceEscrow.sol";

interface Vm {
    function warp(uint256 timestamp) external;
    function chainId(uint256 newChainId) external;
    function prank(address sender) external;
    function expectRevert(bytes calldata revertData) external;
}

contract MockToken is IERC20Settlement {
    mapping(address => uint256) public override balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    uint256 public transferFeeBps;

    function decimals() external pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function setTransferFeeBps(uint256 feeBps) external {
        transferFeeBps = feeBps;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _move(msg.sender, to, amount);
        uint256 fee = amount * transferFeeBps / 10_000;
        balanceOf[to] -= fee;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 approved = allowance[from][msg.sender];
        require(approved >= amount, "allowance");
        allowance[from][msg.sender] = approved - amount;
        _move(from, to, amount);
        return true;
    }

    function _move(address from, address to, uint256 amount) private {
        require(balanceOf[from] >= amount, "balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
    }
}

contract InferenceEscrowTest {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address private constant CLIENT = address(0x1001);
    address private constant SIGNER = address(0x1002);
    address private constant TREASURY = address(0x1003);
    address private constant VALIDATORS = address(0x1004);
    address private constant NODE = address(0x1005);
    address private constant AUTHOR = address(0x1006);
    address private constant BURN = 0x000000000000000000000000000000000000dEaD;
    bytes32 private constant BATCH = keccak256("batch-1");
    bytes32 private constant JOB = keccak256("job-1");
    uint256 private constant AMOUNT = 10_000;

    MockToken private token;
    InferenceEscrow private escrow;

    function setUp() public {
        token = new MockToken();
        escrow = new InferenceEscrow(IERC20Settlement(address(token)), SIGNER, TREASURY, VALIDATORS, 6, 30 days);
        token.mint(CLIENT, AMOUNT * 2);
        vm.prank(CLIENT);
        token.approve(address(escrow), type(uint256).max);
    }

    function testSettlementConservesAndSplitsFunds() public {
        _fundAndPublish(BATCH, JOB, NODE, AUTHOR, AMOUNT, uint64(block.timestamp + 1 days));
        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        _claimSingle(BATCH, JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);

        require(token.balanceOf(NODE) == 7_500, "node share");
        require(token.balanceOf(AUTHOR) == 1_000, "author share");
        require(token.balanceOf(VALIDATORS) == 500, "verification share");
        require(token.balanceOf(BURN) == 500, "burn share");
        require(token.balanceOf(TREASURY) == 500, "treasury share");
        require(token.balanceOf(address(escrow)) == 0, "escrow remainder");
    }

    function testLeafProofIsBoundToCurrentChainId() public {
        _fundAndPublish(BATCH, JOB, NODE, AUTHOR, AMOUNT, uint64(block.timestamp + 1 days));
        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        InferenceEscrow.JobClaim memory job = InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);

        vm.chainId(block.chainid + 1);
        (bool ok,) = address(escrow).call(abi.encodeCall(escrow.claim, (BATCH, job)));
        require(!ok, "proof replayed on another chain id");
    }

    function testLeafProofIsBoundToEscrowInstance() public {
        InferenceEscrow otherEscrow =
            new InferenceEscrow(IERC20Settlement(address(token)), SIGNER, TREASURY, VALIDATORS, 6, 30 days);
        vm.prank(CLIENT);
        token.approve(address(otherEscrow), type(uint256).max);

        bytes32 leaf = _leaf(address(escrow), address(token), BATCH, JOB, NODE, AUTHOR, AMOUNT);
        bytes32 root = _leafNode(leaf, AMOUNT);
        vm.prank(CLIENT);
        otherEscrow.fundBatch(BATCH, AMOUNT);
        vm.prank(SIGNER);
        otherEscrow.publishBatch(BATCH, root, AMOUNT, uint64(block.timestamp + 1 days));

        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        InferenceEscrow.JobClaim memory job = InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);
        (bool ok,) = address(otherEscrow).call(abi.encodeCall(otherEscrow.claim, (BATCH, job)));
        require(!ok, "proof replayed on another escrow");
    }

    function testLeafProofIsBoundToTokenAddress() public {
        MockToken otherToken = new MockToken();
        InferenceEscrow otherEscrow =
            new InferenceEscrow(IERC20Settlement(address(otherToken)), SIGNER, TREASURY, VALIDATORS, 6, 30 days);
        otherToken.mint(CLIENT, AMOUNT);
        vm.prank(CLIENT);
        otherToken.approve(address(otherEscrow), AMOUNT);

        bytes32 leaf = _leaf(address(escrow), address(token), BATCH, JOB, NODE, AUTHOR, AMOUNT);
        bytes32 root = _leafNode(leaf, AMOUNT);
        vm.prank(CLIENT);
        otherEscrow.fundBatch(BATCH, AMOUNT);
        vm.prank(SIGNER);
        otherEscrow.publishBatch(BATCH, root, AMOUNT, uint64(block.timestamp + 1 days));

        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        InferenceEscrow.JobClaim memory job = InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);
        (bool ok,) = address(otherEscrow).call(abi.encodeCall(otherEscrow.claim, (BATCH, job)));
        require(!ok, "proof replayed with another token");
    }

    function testConstructorRejectsWrongExpectedTokenDecimals() public {
        vm.expectRevert(abi.encodeWithSignature("Error(string)", "token decimals mismatch"));
        new InferenceEscrow(IERC20Settlement(address(token)), SIGNER, TREASURY, VALIDATORS, 18, 30 days);
    }

    function testNoAuthorRoutesRoyaltyToNode() public {
        _fundAndPublish(BATCH, JOB, NODE, address(0), AMOUNT, uint64(block.timestamp + 1 days));
        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        _claimSingle(BATCH, JOB, NODE, address(0), AMOUNT, proof, proofSums);
        require(token.balanceOf(NODE) == 8_500, "node receives unused royalty");
        require(token.balanceOf(address(escrow)) == 0, "all amount allocated");
    }

    function testSmallAmountDustMatchesH0TreasurySplit() public {
        _fundAndPublish(BATCH, JOB, NODE, AUTHOR, 3, uint64(block.timestamp + 1 days));
        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        _claimSingle(BATCH, JOB, NODE, AUTHOR, 3, proof, proofSums);
        require(token.balanceOf(NODE) == 2, "node floor mismatch");
        require(token.balanceOf(TREASURY) == 1, "H0 remainder must go to treasury");
        require(token.balanceOf(address(escrow)) == 0, "small amount remains");
    }

    function testReceiptCannotBeClaimedAgainInAnotherBatch() public {
        bytes32 secondBatch = keccak256("batch-2");
        _fundAndPublish(BATCH, JOB, NODE, AUTHOR, AMOUNT, uint64(block.timestamp + 1 days));
        _fundAndPublish(secondBatch, JOB, NODE, AUTHOR, AMOUNT, uint64(block.timestamp + 1 days));
        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        _claimSingle(BATCH, JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);

        InferenceEscrow.JobClaim memory replay = InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);
        (bool ok,) = address(escrow).call(abi.encodeCall(escrow.claim, (secondBatch, replay)));
        require(!ok, "receipt replayed across batches");
        (,,, uint256 remaining,,) = escrow.batches(secondBatch);
        require(remaining == AMOUNT, "replayed claim consumed second batch");
    }

    function testClaimManySettlesTwoJobsFromOneBatch() public {
        bytes32 secondJob = keccak256("job-2");
        bytes32 firstLeaf = _leaf(address(escrow), address(token), BATCH, JOB, NODE, AUTHOR, AMOUNT);
        bytes32 secondLeaf = _leaf(address(escrow), address(token), BATCH, secondJob, address(0x2005), AUTHOR, AMOUNT);
        bytes32 firstNode = _leafNode(firstLeaf, AMOUNT);
        bytes32 secondNode = _leafNode(secondLeaf, AMOUNT);
        bytes32 root = _parent(firstNode, AMOUNT, secondNode, AMOUNT);

        vm.prank(CLIENT);
        escrow.fundBatch(BATCH, AMOUNT * 2);
        vm.prank(SIGNER);
        escrow.publishBatch(BATCH, root, AMOUNT * 2, uint64(block.timestamp + 1 days));

        bytes32[] memory firstProof = new bytes32[](1);
        firstProof[0] = secondNode;
        bytes32[] memory secondProof = new bytes32[](1);
        secondProof[0] = firstNode;
        uint256[] memory firstProofSums = new uint256[](1);
        firstProofSums[0] = AMOUNT;
        uint256[] memory secondProofSums = new uint256[](1);
        secondProofSums[0] = AMOUNT;
        InferenceEscrow.JobClaim[] memory jobs = new InferenceEscrow.JobClaim[](2);
        jobs[0] = InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, firstProof, firstProofSums);
        jobs[1] = InferenceEscrow.JobClaim(secondJob, address(0x2005), AUTHOR, AMOUNT, secondProof, secondProofSums);

        escrow.claimMany(BATCH, jobs);
        require(token.balanceOf(NODE) == 7_500, "first node share");
        require(token.balanceOf(address(0x2005)) == 7_500, "second node share");
        require(token.balanceOf(AUTHOR) == 2_000, "author total");
        require(token.balanceOf(VALIDATORS) == 1_000, "verification total");
        require(token.balanceOf(BURN) == 1_000, "burn total");
        require(token.balanceOf(TREASURY) == 1_000, "treasury total");
        require(token.balanceOf(address(escrow)) == 0, "batch not fully settled");
    }

    function testRejectsInvalidProofAndDuplicateClaim() public {
        _fundAndPublish(BATCH, JOB, NODE, AUTHOR, AMOUNT, uint64(block.timestamp + 1 days));
        bytes32[] memory proof = new bytes32[](1);
        proof[0] = keccak256("wrong sibling");
        uint256[] memory proofSums = new uint256[](1);
        proofSums[0] = AMOUNT;
        InferenceEscrow.JobClaim memory invalidJob =
            InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);
        (bool invalidProof,) = address(escrow).call(abi.encodeCall(escrow.claim, (BATCH, invalidJob)));
        require(!invalidProof, "accepted invalid proof");

        proof = new bytes32[](0);
        proofSums = new uint256[](0);
        InferenceEscrow.JobClaim memory validJob = InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);
        escrow.claim(BATCH, validJob);
        (bool duplicate,) = address(escrow).call(abi.encodeCall(escrow.claim, (BATCH, validJob)));
        require(!duplicate, "accepted duplicate claim");
    }

    function testOnlySignerCanPublish() public {
        vm.prank(address(0xBAD));
        (bool ok,) = address(escrow)
            .call(abi.encodeCall(escrow.publishBatch, (BATCH, JOB, AMOUNT, uint64(block.timestamp + 1 days))));
        require(!ok, "unauthorized publisher accepted");
    }

    function testRootSumCannotExceedFundedBudget() public {
        vm.prank(CLIENT);
        escrow.fundBatch(BATCH, AMOUNT);
        vm.prank(SIGNER);
        (bool ok,) = address(escrow)
            .call(abi.encodeCall(escrow.publishBatch, (BATCH, JOB, AMOUNT + 1, uint64(block.timestamp + 1 days))));
        require(!ok, "root overcommits batch");
    }

    function testProofCannotLieAboutSiblingSum() public {
        bytes32 secondJob = keccak256("sum-proof-job-2");
        bytes32 firstLeaf = _leaf(address(escrow), address(token), BATCH, JOB, NODE, AUTHOR, AMOUNT);
        bytes32 secondLeaf = _leaf(address(escrow), address(token), BATCH, secondJob, address(0x2005), AUTHOR, AMOUNT);
        bytes32 secondNode = _leafNode(secondLeaf, AMOUNT);
        bytes32 root = _parent(_leafNode(firstLeaf, AMOUNT), AMOUNT, secondNode, AMOUNT);
        vm.prank(CLIENT);
        escrow.fundBatch(BATCH, AMOUNT * 2);
        vm.prank(SIGNER);
        escrow.publishBatch(BATCH, root, AMOUNT * 2, uint64(block.timestamp + 1 days));

        bytes32[] memory proof = new bytes32[](1);
        proof[0] = secondNode;
        uint256[] memory proofSums = new uint256[](1);
        proofSums[0] = AMOUNT - 1;
        InferenceEscrow.JobClaim memory job = InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);
        (bool ok,) = address(escrow).call(abi.encodeCall(escrow.claim, (BATCH, job)));
        require(!ok, "accepted false sibling sum");
        require(token.balanceOf(address(escrow)) == AMOUNT * 2, "invalid proof consumed funds");
    }

    function testClaimDeadlineIsBounded() public {
        vm.prank(CLIENT);
        escrow.fundBatch(BATCH, AMOUNT);
        vm.prank(SIGNER);
        (bool ok,) = address(escrow)
            .call(abi.encodeCall(escrow.publishBatch, (BATCH, JOB, AMOUNT, uint64(block.timestamp + 31 days))));
        require(!ok, "unbounded claim deadline");
    }

    function testPayerCanCancelUnpublishedBatch() public {
        vm.prank(CLIENT);
        escrow.fundBatch(BATCH, AMOUNT);
        uint256 beforeBalance = token.balanceOf(CLIENT);
        vm.prank(CLIENT);
        escrow.cancelUnpublished(BATCH);
        require(token.balanceOf(CLIENT) == beforeBalance + AMOUNT, "cancel refund");
    }

    function testRejectsFeeOnPayoutTokenWithoutLosingEscrowLiability() public {
        _fundAndPublish(BATCH, JOB, NODE, AUTHOR, AMOUNT, uint64(block.timestamp + 1 days));
        token.setTransferFeeBps(100);
        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        InferenceEscrow.JobClaim memory job = InferenceEscrow.JobClaim(JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);
        (bool ok,) = address(escrow).call(abi.encodeCall(escrow.claim, (BATCH, job)));
        require(!ok, "accepted fee on payout token");
        require(token.balanceOf(address(escrow)) == AMOUNT, "failed claim consumed escrow");
        require(token.balanceOf(NODE) == 0, "failed claim paid node");
    }

    function testLargeAmountsDoNotOverflowSplitMath() public {
        address largeClient = address(0x7777);
        bytes32 batchId = keccak256("large-batch");
        bytes32 jobId = keccak256("large-job");
        uint256 amount = type(uint256).max;
        token.mint(largeClient, amount);
        vm.prank(largeClient);
        token.approve(address(escrow), amount);
        vm.prank(largeClient);
        escrow.fundBatch(batchId, amount);

        bytes32 leaf = _leaf(address(escrow), address(token), batchId, jobId, NODE, AUTHOR, amount);
        bytes32 root = keccak256(abi.encodePacked(leaf, amount));
        vm.prank(SIGNER);
        escrow.publishBatch(batchId, root, amount, uint64(block.timestamp + 1 days));
        bytes32[] memory proof = new bytes32[](0);
        uint256[] memory proofSums = new uint256[](0);
        _claimSingle(batchId, jobId, NODE, AUTHOR, amount, proof, proofSums);

        uint256 totalPaid = token.balanceOf(NODE) + token.balanceOf(AUTHOR) + token.balanceOf(VALIDATORS)
            + token.balanceOf(BURN) + token.balanceOf(TREASURY);
        require(totalPaid == amount, "large amount not conserved");
    }

    function testExpiredBatchRefundsUnclaimedDeposit() public {
        bytes32 batchId = keccak256("refund-batch");
        bytes32 jobId = keccak256("refund-job");
        _fundAndPublish(batchId, jobId, NODE, AUTHOR, AMOUNT, uint64(block.timestamp + 1 days));
        vm.warp(block.timestamp + 1 days + 1);
        uint256 beforeBalance = token.balanceOf(CLIENT);
        escrow.refundExpired(batchId);
        require(token.balanceOf(CLIENT) == beforeBalance + AMOUNT, "refund amount");
        require(token.balanceOf(address(escrow)) == 0, "escrow retains funds");
    }

    function testRefundAfterPartialBatchSettlement() public {
        bytes32 secondJob = keccak256("partial-job-2");
        bytes32 firstLeaf = _leaf(address(escrow), address(token), BATCH, JOB, NODE, AUTHOR, AMOUNT);
        bytes32 secondLeaf = _leaf(address(escrow), address(token), BATCH, secondJob, address(0x2005), AUTHOR, AMOUNT);
        bytes32 secondNode = _leafNode(secondLeaf, AMOUNT);
        bytes32 root = _parent(_leafNode(firstLeaf, AMOUNT), AMOUNT, secondNode, AMOUNT);

        vm.prank(CLIENT);
        escrow.fundBatch(BATCH, AMOUNT * 2);
        uint64 deadline = uint64(block.timestamp + 1 days);
        vm.prank(SIGNER);
        escrow.publishBatch(BATCH, root, AMOUNT * 2, deadline);
        bytes32[] memory proof = new bytes32[](1);
        proof[0] = secondNode;
        uint256[] memory proofSums = new uint256[](1);
        proofSums[0] = AMOUNT;
        _claimSingle(BATCH, JOB, NODE, AUTHOR, AMOUNT, proof, proofSums);

        vm.warp(uint256(deadline) + 1);
        uint256 beforeBalance = token.balanceOf(CLIENT);
        escrow.refundExpired(BATCH);
        require(token.balanceOf(CLIENT) == beforeBalance + AMOUNT, "partial remainder refund");
        require(token.balanceOf(address(escrow)) == 0, "partial batch funds remain");
    }

    function _fundAndPublish(
        bytes32 batchId,
        bytes32 jobId,
        address node,
        address author,
        uint256 amount,
        uint64 deadline
    ) private {
        vm.prank(CLIENT);
        escrow.fundBatch(batchId, amount);
        bytes32 leaf = _leaf(address(escrow), address(token), batchId, jobId, node, author, amount);
        bytes32 root = keccak256(abi.encodePacked(leaf, amount));
        vm.prank(SIGNER);
        escrow.publishBatch(batchId, root, amount, deadline);
    }

    function _parent(bytes32 a, uint256 aSum, bytes32 b, uint256 bSum) private pure returns (bytes32) {
        return a < b ? keccak256(abi.encodePacked(a, aSum, b, bSum)) : keccak256(abi.encodePacked(b, bSum, a, aSum));
    }

    function _leafNode(bytes32 leafHash, uint256 amount) private pure returns (bytes32) {
        return keccak256(abi.encodePacked(leafHash, amount));
    }

    function _leaf(
        address escrowAddress,
        address tokenAddress,
        bytes32 batchId,
        bytes32 jobId,
        address node,
        address author,
        uint256 amount
    ) private view returns (bytes32) {
        return keccak256(
            abi.encode(
                keccak256("NEXUS_INFERENCE_ESCROW_LEAF_V2"),
                block.chainid,
                escrowAddress,
                tokenAddress,
                batchId,
                jobId,
                node,
                author,
                amount
            )
        );
    }

    function _claimSingle(
        bytes32 batchId,
        bytes32 jobId,
        address node,
        address author,
        uint256 amount,
        bytes32[] memory proof,
        uint256[] memory proofSums
    ) private {
        InferenceEscrow.JobClaim memory job = InferenceEscrow.JobClaim(jobId, node, author, amount, proof, proofSums);
        escrow.claim(batchId, job);
    }
}
