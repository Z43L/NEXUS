// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract VoteDelegation {
    struct Delegation {
        address delegatee;
        uint256 timestamp;
        uint256 untilBlock;
        bool active;
    }
    
    mapping(address => Delegation) public delegations;
    mapping(address => uint256) public receivedDelegations;
    
    event VoteDelegated(address indexed delegator, address indexed delegatee, uint256 untilBlock);
    event DelegationRevoked(address indexed delegator, address indexed delegatee);
    
    function delegateVote(address delegatee, uint256 untilBlock) external {
        require(delegatee != msg.sender, "Cannot delegate to self");
        require(untilBlock > block.number, "Invalid block number");
        
        // Revocar delegación anterior si existe
        if (delegations[msg.sender].active) {
            _revokeDelegation(msg.sender);
        }
        
        delegations[msg.sender] = Delegation({
            delegatee: delegatee,
            timestamp: block.timestamp,
            untilBlock: untilBlock,
            active: true
        });
        
        receivedDelegations[delegatee] += getVotingPower(msg.sender);
        
        emit VoteDelegated(msg.sender, delegatee, untilBlock);
    }
    
    function revokeDelegation() external {
        require(delegations[msg.sender].active, "No active delegation");
        _revokeDelegation(msg.sender);
    }
    
    function _revokeDelegation(address delegator) internal {
        Delegation storage delegation = delegations[delegator];
        receivedDelegations[delegation.delegatee] -= getVotingPower(delegator);
        
        emit DelegationRevoked(delegator, delegation.delegatee);
        
        delegation.active = false;
    }
    
    function getEffectiveVotingPower(address account) public view returns (uint256) {
        uint256 basePower = getVotingPower(account);
        uint256 delegatedPower = receivedDelegations[account];
        
        return basePower + delegatedPower;
    }
    
    function getVotingPower(address account) internal view returns (uint256) {
        // Implementación específica del cálculo de poder de voto
        return IERC20(nexusToken).balanceOf(account);
    }
}