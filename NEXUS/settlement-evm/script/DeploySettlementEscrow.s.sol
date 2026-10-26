// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {InferenceEscrow, IERC20Settlement} from "../src/InferenceEscrow.sol";

interface VmSettlementDeploy {
    function envUint(string calldata name) external view returns (uint256);
    function envAddress(string calldata name) external view returns (address);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

/// @notice Deploy the production escrow against an already-deployed ERC-20.
/// @dev Always set an explicit expected chain ID. This script never deploys a
///      token and does not submit transactions unless Foundry receives --broadcast.
contract DeploySettlementEscrow {
    VmSettlementDeploy private constant vm =
        VmSettlementDeploy(address(uint160(uint256(keccak256("hevm cheat code")))));

    function run() external returns (address escrowAddress) {
        uint256 expectedChainId = vm.envUint("NEXUS_SETTLEMENT_EXPECTED_CHAIN_ID");
        require(expectedChainId > 0 && block.chainid == expectedChainId, "NEXUS_SETTLEMENT_CHAIN_MISMATCH");

        uint256 privateKey = vm.envUint("NEXUS_SETTLEMENT_DEPLOYER_PRIVATE_KEY");
        address owner = vm.envAddress("NEXUS_SETTLEMENT_OWNER");
        address tokenAddress = vm.envAddress("NEXUS_SETTLEMENT_TOKEN");
        uint256 decimalsValue = vm.envUint("NEXUS_SETTLEMENT_TOKEN_DECIMALS");
        uint256 claimWindowValue = vm.envUint("NEXUS_SETTLEMENT_MAX_CLAIM_WINDOW");
        require(tokenAddress != address(0) && tokenAddress.code.length > 0, "NEXUS_SETTLEMENT_TOKEN_INVALID");
        require(decimalsValue <= 36, "NEXUS_SETTLEMENT_DECIMALS_INVALID");
        require(claimWindowValue > 0 && claimWindowValue <= type(uint64).max, "NEXUS_SETTLEMENT_CLAIM_WINDOW_INVALID");

        uint8 decimals = uint8(decimalsValue);
        require(IERC20Settlement(tokenAddress).decimals() == decimals, "NEXUS_SETTLEMENT_DECIMALS_MISMATCH");
        address signer = vm.envAddress("NEXUS_SETTLEMENT_BATCH_SIGNER");
        address treasury = vm.envAddress("NEXUS_SETTLEMENT_TREASURY");
        address verificationPool = vm.envAddress("NEXUS_SETTLEMENT_VERIFICATION_POOL");

        vm.startBroadcast(privateKey);
        InferenceEscrow escrow = new InferenceEscrow(
            IERC20Settlement(tokenAddress),
            owner,
            signer,
            treasury,
            verificationPool,
            decimals,
            uint64(claimWindowValue)
        );
        require(escrow.owner() == owner, "NEXUS_SETTLEMENT_OWNER_MISMATCH");
        require(address(escrow.token()) == tokenAddress, "NEXUS_SETTLEMENT_TOKEN_MISMATCH");
        require(escrow.batchSigner() == signer, "NEXUS_SETTLEMENT_SIGNER_MISMATCH");
        require(escrow.maxClaimWindow() == claimWindowValue, "NEXUS_SETTLEMENT_WINDOW_MISMATCH");
        escrowAddress = address(escrow);
        vm.stopBroadcast();
    }
}
