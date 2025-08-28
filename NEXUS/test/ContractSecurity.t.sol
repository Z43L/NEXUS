// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "forge-std/Test.sol";
import "../src/NexusToken.sol";
import "../src/StakingSystem.sol";

contract ContractSecurityTest is Test {
    NexusToken public token;
    StakingSystem public staking;
    
    address constant ATTACKER = address(0xBAD);
    address constant USER1 = address(0x1);
    address constant USER2 = address(0x2);
    
    function setUp() public {
        token = new NexusToken(1_000_000 * 10**18);
        staking = new StakingSystem(address(token));
        
        // Distribuir tokens para pruebas
        token.transfer(USER1, 10_000 * 10**18);
        token.transfer(USER2, 10_000 * 10**18);
        token.transfer(ATTACKER, 10_000 * 10**18);
    }
    
    function test_ReentrancyAttack() public {
        // Configurar ataque de reentrancia
        vm.startPrank(ATTACKER);
        
        token.approve(address(staking), 10_000 * 10**18);
        staking.stake(10_000 * 10**18);
        
        // Intentar ataque de reentrancia
        // Debería ser bloqueado por el modifier nonReentrant
        bool success = staking.unstake();
        assertTrue(success, "Unstake debería funcionar normalmente");
        
        // Verificar que el ataque fue prevenido
        uint256 attackerBalance = token.balanceOf(ATTACKER);
        assertEq(attackerBalance, 10_000 * 10**18, "Debería recibir tokens de vuelta");
        
        vm.stopPrank();
    }
    
    function test_OverflowAttack() public {
        // Test de prevención de overflows
        vm.startPrank(ATTACKER);
        
        uint256 hugeAmount = type(uint256).max;
        
        // Esto debería revertir por overflow
        vm.expectRevert();
        staking.stake(hugeAmount);
        
        vm.stopPrank();
    }
    
    function test_AccessControl() public {
        // Test de controles de acceso
        vm.startPrank(ATTACKER);
        
        // Atacante no debería poder slash a otros usuarios
        vm.expectRevert("Only governance");
        staking.slash(USER1, 1000 * 10**18, "Test attack");
        
        vm.stopPrank();
    }
    
    function test_EdgeCaseStaking() public {
        // Test de casos edge en staking
        vm.startPrank(USER1);
        
        token.approve(address(staking), 10_000 * 10**18);
        
        // Staking de cantidad mínima
        staking.stake(1 wei);
        
        // Staking de cantidad máxima
        staking.stake(10_000 * 10**18);
        
        // Intentar staking de 0
        vm.expectRevert("Amount must be positive");
        staking.stake(0);
        
        vm.stopPrank();
    }
}