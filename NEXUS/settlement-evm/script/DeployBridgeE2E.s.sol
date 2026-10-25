// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "../src/InferenceEscrow.sol";
import "../src/MockSettlementToken.sol";

interface VmDeployE2E {
    function envUint(string calldata name) external view returns (uint256);
    function envAddress(string calldata name) external view returns (address);
    function addr(uint256 privateKey) external pure returns (address);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

/// @dev Deploys isolated E2E fixtures and funds the test payer on local Anvil.
contract DeployBridgeE2E {
    VmDeployE2E private constant vm = VmDeployE2E(address(uint160(uint256(keccak256("hevm cheat code")))));

    function run() external {
        uint256 privateKey = vm.envUint("NEXUS_E2E_PRIVATE_KEY");
        uint256 funding = vm.envUint("NEXUS_E2E_FUNDING");
        address payer = vm.addr(privateKey);
        vm.startBroadcast(privateKey);
        MockSettlementToken token = new MockSettlementToken();
        InferenceEscrow escrow =
            new InferenceEscrow(IERC20Settlement(address(token)), payer, address(0x1001), address(0x1002), 6, 1 days);
        token.mint(payer, funding);
        vm.stopBroadcast();
        require(token.balanceOf(payer) == funding, "E2E funding failed");
        require(address(escrow.token()) == address(token), "E2E escrow token mismatch");
    }
}
