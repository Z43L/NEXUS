// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract NexusStaking is ReentrancyGuard {
    IERC20 public nexusToken;
    
    struct Stake {
        uint256 amount;
        uint256 stakedSince;
        uint256 unlockTime;
        bool locked;
    }
    
    mapping(address => Stake) public stakes;
    mapping(address => uint256) public slashingEvents;
    
    uint256 public minimumStake = 1000 * 10**18; // 1000 tokens
    uint256 public lockingPeriod = 30 days;
    uint256 public slashPercentage = 10; // 10% slashing por mal comportamiento
    
    event Staked(address indexed user, uint256 amount, uint256 unlockTime);
    event Unstaked(address indexed user, uint256 amount);
    event Slashed(address indexed user, uint256 amount, string reason);
    
    constructor(address _nexusToken) {
        nexusToken = IERC20(_nexusToken);
    }
    
    function stake(uint256 amount) external nonReentrant {
        require(amount >= minimumStake, "Stake below minimum");
        require(nexusToken.transferFrom(msg.sender, address(this), amount), "Transfer failed");
        
        Stake storage userStake = stakes[msg.sender];
        
        if (userStake.amount > 0) {
            // Ya tiene stake, añadir al existente
            userStake.amount += amount;
        } else:
            // Nuevo stake
            stakes[msg.sender] = Stake({
                amount: amount,
                stakedSince: block.timestamp,
                unlockTime: block.timestamp + lockingPeriod,
                locked: true
            });
        }
        
        emit Staked(msg.sender, amount, block.timestamp + lockingPeriod);
    }
    
    function unstake() external nonReentrant {
        Stake storage userStake = stakes[msg.sender];
        require(userStake.amount > 0, "No stake found");
        require(block.timestamp >= userStake.unlockTime, "Stake still locked");
        require(!userStake.locked, "Stake is locked");
        
        uint256 amount = userStake.amount;
        userStake.amount = 0;
        
        require(nexusToken.transfer(msg.sender, amount), "Transfer failed");
        emit Unstaked(msg.sender, amount);
    }
    
    function slash(address user, string memory reason) external onlyGovernance {
        Stake storage userStake = stakes[user];
        require(userStake.amount > 0, "No stake to slash");
        
        uint256 slashAmount = (userStake.amount * slashPercentage) / 100;
        userStake.amount -= slashAmount;
        slashingEvents[user]++;
        
        // Quemar los tokens slashados o enviarlos a treasury
        require(nexusToken.transfer(address(0xdead), slashAmount), "Slash transfer failed");
        
        emit Slashed(user, slashAmount, reason);
    }
    
    function getVotingPower(address user) external view returns (uint256) {
        Stake memory userStake = stakes[user];
        uint256 basePower = userStake.amount;
        
        // Bonificación por stake a largo plazo
        uint256 stakingDuration = block.timestamp - userStake.stakedSince;
        uint256 timeBonus = (basePower * min(stakingDuration, 365 days)) / (365 days * 10);
        
        // Penalización por slashing events
        uint256 slashPenalty = (basePower * slashingEvents[user] * 5) / 100;
        
        return basePower + timeBonus - slashPenalty;
    }
    
    modifier onlyGovernance() {
        require(msg.sender == governance, "Only governance can slash");
        _;
    }
    
    function min(uint256 a, uint256 b) internal pure returns (uint256) {
        return a < b ? a : b;
    }
}