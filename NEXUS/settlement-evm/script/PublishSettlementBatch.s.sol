// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {InferenceEscrow, IERC20Settlement} from "../src/InferenceEscrow.sol";

interface IERC20SettlementApproval {
    function approve(address spender, uint256 value) external returns (bool);
}

interface VmPublishSettlement {
    function envUint(string calldata name) external view returns (uint256);
    function envAddress(string calldata name) external view returns (address);
    function envBytes32(string calldata name) external view returns (bytes32);
    function parseJsonBytes32(string calldata json, string calldata key) external pure returns (bytes32);
    function parseJsonUint(string calldata json, string calldata key) external pure returns (uint256);
    function parseJsonAddress(string calldata json, string calldata key) external pure returns (address);
    function addr(uint256 privateKey) external pure returns (address);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

/// @notice Fund from a payer account, then publish the receipt root from the
///         separately configured gateway signer. Simulate first; broadcast only
///         after reviewing the resolved chain, contract, token, and batch.
contract PublishSettlementBatch {
    VmPublishSettlement private constant vm =
        VmPublishSettlement(address(uint160(uint256(keccak256("hevm cheat code")))));

    struct Plan {
        address escrow;
        address token;
        address payer;
        address signer;
        uint256 payerKey;
        uint256 signerKey;
        bytes32 batchId;
        bytes32 root;
        uint256 rootSum;
        uint256 deadline;
    }

    function run(string calldata json) external {
        Plan memory plan = _prepare(json);
        _broadcast(plan);
        _checkPublished(plan);
    }

    function _prepare(string calldata json) private view returns (Plan memory plan) {
        uint256 expectedChainId = vm.envUint("NEXUS_SETTLEMENT_EXPECTED_CHAIN_ID");
        require(expectedChainId > 0 && block.chainid == expectedChainId, "NEXUS_SETTLEMENT_CHAIN_MISMATCH");
        plan.escrow = vm.envAddress("NEXUS_SETTLEMENT_ESCROW");
        plan.token = vm.envAddress("NEXUS_SETTLEMENT_TOKEN");
        require(plan.escrow.code.length > 0 && plan.token.code.length > 0, "NEXUS_SETTLEMENT_CONTRACT_INVALID");

        plan.batchId = vm.parseJsonBytes32(json, ".batchId");
        plan.root = vm.parseJsonBytes32(json, ".root");
        plan.rootSum = vm.parseJsonUint(json, ".rootSum");
        require(
            plan.batchId != bytes32(0) && plan.root != bytes32(0) && plan.rootSum > 0, "NEXUS_SETTLEMENT_BATCH_INVALID"
        );
        require(
            plan.rootSum <= vm.parseJsonUint(json, ".depositAmount"), "NEXUS_SETTLEMENT_ROOT_EXCEEDS_POLICY_DEPOSIT"
        );
        require(
            vm.parseJsonBytes32(json, ".settlementPolicyHash")
                == vm.envBytes32("NEXUS_SETTLEMENT_EXPECTED_POLICY_HASH"),
            "NEXUS_SETTLEMENT_POLICY_HASH_MISMATCH"
        );
        _checkBatchContext(json, expectedChainId, plan.escrow, plan.token);

        InferenceEscrow escrow = InferenceEscrow(plan.escrow);
        IERC20Settlement token = IERC20Settlement(plan.token);
        require(address(escrow.token()) == plan.token, "NEXUS_SETTLEMENT_ESCROW_TOKEN_MISMATCH");
        require(token.decimals() == escrow.tokenDecimals(), "NEXUS_SETTLEMENT_DECIMALS_MISMATCH");
        require(
            vm.parseJsonUint(json, ".tokenDecimals") == escrow.tokenDecimals(),
            "NEXUS_SETTLEMENT_BATCH_DECIMALS_MISMATCH"
        );
        require(escrow.treasury() == vm.envAddress("NEXUS_SETTLEMENT_TREASURY"), "NEXUS_SETTLEMENT_TREASURY_MISMATCH");
        require(
            escrow.verificationPool() == vm.envAddress("NEXUS_SETTLEMENT_VERIFICATION_POOL"),
            "NEXUS_SETTLEMENT_VERIFICATION_POOL_MISMATCH"
        );
        plan.payerKey = vm.envUint("NEXUS_SETTLEMENT_PAYER_PRIVATE_KEY");
        plan.signerKey = vm.envUint("NEXUS_SETTLEMENT_SIGNER_PRIVATE_KEY");
        plan.payer = vm.addr(plan.payerKey);
        plan.signer = vm.addr(plan.signerKey);
        require(plan.payer != plan.signer, "NEXUS_SETTLEMENT_ROLES_MUST_DIFFER");
        require(escrow.batchSigner() == plan.signer, "NEXUS_SETTLEMENT_SIGNER_MISMATCH");
        uint256 minimumGasBalance = vm.envUint("NEXUS_SETTLEMENT_MIN_GAS_BALANCE");
        require(plan.payer.balance >= minimumGasBalance, "NEXUS_SETTLEMENT_PAYER_GAS_LOW");
        require(plan.signer.balance >= minimumGasBalance, "NEXUS_SETTLEMENT_SIGNER_GAS_LOW");
        require(token.balanceOf(plan.payer) >= plan.rootSum, "NEXUS_SETTLEMENT_PAYER_BALANCE_LOW");
        (address existingPayer,,,,,) = escrow.batches(plan.batchId);
        require(existingPayer == address(0), "NEXUS_SETTLEMENT_BATCH_ALREADY_FUNDED");
        plan.deadline = vm.envUint("NEXUS_SETTLEMENT_CLAIM_DEADLINE");
        require(
            plan.deadline <= type(uint64).max && plan.deadline > block.timestamp + 60,
            "NEXUS_SETTLEMENT_DEADLINE_INVALID"
        );
        require(plan.deadline - block.timestamp <= escrow.maxClaimWindow(), "NEXUS_SETTLEMENT_DEADLINE_TOO_FAR");
    }

    function _checkBatchContext(string memory json, uint256 chainId, address escrow, address token) private pure {
        require(
            vm.parseJsonUint(json, ".settlementContext.chainId") == chainId, "NEXUS_SETTLEMENT_BATCH_CHAIN_MISMATCH"
        );
        require(
            vm.parseJsonAddress(json, ".settlementContext.escrowAddress") == escrow,
            "NEXUS_SETTLEMENT_BATCH_ESCROW_MISMATCH"
        );
        require(
            vm.parseJsonAddress(json, ".settlementContext.tokenAddress") == token,
            "NEXUS_SETTLEMENT_BATCH_TOKEN_MISMATCH"
        );
    }

    function _broadcast(Plan memory plan) private {
        vm.startBroadcast(plan.payerKey);
        require(IERC20SettlementApproval(plan.token).approve(plan.escrow, 0), "NEXUS_SETTLEMENT_APPROVAL_RESET_FAILED");
        require(
            IERC20SettlementApproval(plan.token).approve(plan.escrow, plan.rootSum), "NEXUS_SETTLEMENT_APPROVE_FAILED"
        );
        InferenceEscrow(plan.escrow).fundBatch(plan.batchId, plan.rootSum);
        vm.stopBroadcast();
        vm.startBroadcast(plan.signerKey);
        InferenceEscrow(plan.escrow).publishBatch(plan.batchId, plan.root, plan.rootSum, uint64(plan.deadline));
        vm.stopBroadcast();
    }

    function _checkPublished(Plan memory plan) private view {
        (address fundedBy, bytes32 publishedRoot, uint256 publishedSum,, uint64 publishedDeadline, bool published) =
            InferenceEscrow(plan.escrow).batches(plan.batchId);
        require(
            fundedBy == plan.payer && published && publishedRoot == plan.root && publishedSum == plan.rootSum
                && publishedDeadline == plan.deadline,
            "NEXUS_SETTLEMENT_POSTCONDITION_FAILED"
        );
    }
}
