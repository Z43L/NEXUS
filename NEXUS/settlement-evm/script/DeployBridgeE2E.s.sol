// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import "../src/MockSettlementToken.sol";

interface VmDeployE2E {
    function envUint(string calldata name) external view returns (uint256);
    function addr(uint256 privateKey) external pure returns (address);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

/// @dev Deploys the test token and funds the test payer on local Anvil. The
///      E2E separately exercises the generic escrow deployment script.
contract DeployBridgeE2E {
    VmDeployE2E private constant vm = VmDeployE2E(address(uint160(uint256(keccak256("hevm cheat code")))));

    function run() external {
        uint256 privateKey = vm.envUint("NEXUS_E2E_PRIVATE_KEY");
        uint256 funding = vm.envUint("NEXUS_E2E_FUNDING");
        address payer = vm.addr(privateKey);
        vm.startBroadcast(privateKey);
        MockSettlementToken token = new MockSettlementToken();
        token.mint(payer, funding);
        vm.stopBroadcast();
        require(token.balanceOf(payer) == funding, "E2E funding failed");
    }
}
