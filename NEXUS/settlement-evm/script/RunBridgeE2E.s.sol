// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "../src/InferenceEscrow.sol";
import "../src/MockSettlementToken.sol";

interface VmE2E {
    function parseJsonBytes32(string calldata json, string calldata key) external pure returns (bytes32);
    function parseJsonUint(string calldata json, string calldata key) external pure returns (uint256);
    function parseJsonAddress(string calldata json, string calldata key) external pure returns (address);
    function parseJsonBytes32Array(string calldata json, string calldata key) external pure returns (bytes32[] memory);
    function parseJsonUintArray(string calldata json, string calldata key) external pure returns (uint256[] memory);
    function envUint(string calldata name) external view returns (uint256);
    function addr(uint256 privateKey) external pure returns (address);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

/// @dev TEST ONLY. Deploys mock token + escrow, then settles a bridge-produced
/// batch on a disposable Anvil chain and checks every expected recipient balance.
contract RunBridgeE2E {
    VmE2E private constant vm = VmE2E(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 private constant CLAIM_WINDOW = 1 days;

    struct BatchData {
        bytes32 batchId;
        bytes32 root;
        uint256 rootSum;
        InferenceEscrow.JobClaim[] claims;
    }

    struct Payouts {
        uint256 node;
        uint256 author;
        uint256 verification;
        uint256 burn;
        uint256 treasury;
    }

    function run(string calldata json) external {
        BatchData memory data = BatchData({
            batchId: vm.parseJsonBytes32(json, ".batchId"),
            root: vm.parseJsonBytes32(json, ".root"),
            rootSum: vm.parseJsonUint(json, ".rootSum"),
            claims: new InferenceEscrow.JobClaim[](2)
        });
        // This harness fixture intentionally contains exactly two claims. Parse
        // typed fields explicitly because generic parseJson treats hex strings
        // as dynamic strings, not bytes32/address ABI words.
        data.claims[0] = _parseClaim(json, 0);
        data.claims[1] = _parseClaim(json, 1);
        require(data.claims.length > 0 && data.rootSum > 0, "empty bridge batch");
        _runBatch(data, vm.envUint("NEXUS_E2E_PRIVATE_KEY"));
    }

    function _parseClaim(string calldata json, uint256 index)
        private
        pure
        returns (InferenceEscrow.JobClaim memory claim)
    {
        string memory prefix = index == 0 ? ".claims[0]." : ".claims[1].";
        claim.jobId = vm.parseJsonBytes32(json, string.concat(prefix, "jobId"));
        claim.node = vm.parseJsonAddress(json, string.concat(prefix, "node"));
        claim.author = vm.parseJsonAddress(json, string.concat(prefix, "author"));
        claim.amount = vm.parseJsonUint(json, string.concat(prefix, "amount"));
        claim.proof = vm.parseJsonBytes32Array(json, string.concat(prefix, "proof"));
        claim.proofSums = vm.parseJsonUintArray(json, string.concat(prefix, "proofSums"));
    }

    function _runBatch(BatchData memory data, uint256 privateKey) private {
        address payer = vm.addr(privateKey);
        Payouts memory expected = _calculatePayouts(data.claims);
        (MockSettlementToken token, InferenceEscrow escrow) = _broadcastSettlement(data, privateKey, payer);
        _checkBalances(data, token, escrow, expected);
    }

    function _broadcastSettlement(BatchData memory data, uint256 privateKey, address payer)
        private
        returns (MockSettlementToken token, InferenceEscrow escrow)
    {
        vm.startBroadcast(privateKey);
        token = new MockSettlementToken();
        escrow = new InferenceEscrow(
            IERC20Settlement(address(token)), payer, address(0x1001), address(0x1002), 6, uint64(CLAIM_WINDOW)
        );
        token.mint(payer, data.rootSum);
        token.approve(address(escrow), data.rootSum);
        escrow.fundBatch(data.batchId, data.rootSum);
        escrow.publishBatch(data.batchId, data.root, data.rootSum, uint64(block.timestamp + 1 hours));
        escrow.claimMany(data.batchId, data.claims);
        vm.stopBroadcast();
    }

    function _calculatePayouts(InferenceEscrow.JobClaim[] memory claims) private pure returns (Payouts memory total) {
        for (uint256 i; i < claims.length; ++i) {
            InferenceEscrow.JobClaim memory claim = claims[i];
            require(claim.amount > 0 && claim.jobId != bytes32(0), "invalid bridge claim");
            uint256 authorShare = claim.author == address(0) ? 0 : _bps(claim.amount, 1_000);
            uint256 verifierShare = _bps(claim.amount, 500);
            uint256 burnShare = _bps(claim.amount, 500);
            uint256 nodeShare = _bps(claim.amount, 7_500);
            if (claim.author == address(0)) nodeShare += _bps(claim.amount, 1_000);
            uint256 treasuryShare = claim.amount - nodeShare - authorShare - verifierShare - burnShare;
            total.author += authorShare;
            total.verification += verifierShare;
            total.burn += burnShare;
            total.treasury += treasuryShare;
            total.node += nodeShare;
        }
    }

    function _checkBalances(
        BatchData memory data,
        MockSettlementToken token,
        InferenceEscrow escrow,
        Payouts memory expected
    ) private view {
        require(token.balanceOf(address(0x1001)) == expected.treasury, "treasury balance mismatch");
        require(token.balanceOf(address(0x1002)) == expected.verification, "verification balance mismatch");
        require(token.balanceOf(escrow.BURN_SINK()) == expected.burn, "burn sink balance mismatch");
        (,,, uint256 remaining,,) = escrow.batches(data.batchId);
        require(remaining == 0, "batch remaining mismatch");
        for (uint256 i; i < data.claims.length; ++i) {
            InferenceEscrow.JobClaim memory claim = data.claims[i];
            uint256 expectedNode;
            uint256 expectedAuthor;
            for (uint256 j; j < data.claims.length; ++j) {
                InferenceEscrow.JobClaim memory other = data.claims[j];
                uint256 authorShare = other.author == address(0) ? 0 : _bps(other.amount, 1_000);
                uint256 nodeShare = _bps(other.amount, 7_500);
                if (other.author == address(0)) nodeShare += _bps(other.amount, 1_000);
                if (other.node == claim.node) expectedNode += nodeShare;
                if (claim.author != address(0) && other.author == claim.author) expectedAuthor += authorShare;
            }
            require(token.balanceOf(claim.node) == expectedNode, "node balance mismatch");
            if (claim.author != address(0)) {
                require(token.balanceOf(claim.author) == expectedAuthor, "author balance mismatch");
            }
        }
        require(
            expected.node + expected.author + expected.verification + expected.burn + expected.treasury == data.rootSum,
            "payouts do not conserve root sum"
        );
    }

    function _bps(uint256 amount, uint256 rate) private pure returns (uint256) {
        return (amount / 10_000) * rate + ((amount % 10_000) * rate) / 10_000;
    }
}
