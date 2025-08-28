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
        uint256 slashingCount;
    }
    
    mapping(address => Stake) public stakes;
    uint256 public totalStaked;
    uint256 public minimumStake = 1000 * 10**18; // 1000 tokens
    uint256 public lockingPeriod = 30 days;
    uint256 public slashPercentage = 10; // 10% por mala conducta
    
    event Staked(address indexed user, uint256 amount, uint256 unlockTime);
    event Unstaked(address indexed user, uint256 amount);
    event Slashed(address indexed user, uint256 amount, string reason);
    event RewardsClaimed(address indexed user, uint256 amount);
    
    constructor(address _nexusToken) {
        nexusToken = IERC20(_nexusToken);
    }
    
    function stake(uint256 amount) external nonReentrant {
        require(amount >= minimumStake, "Below minimum stake");
        require(nexusToken.transferFrom(msg.sender, address(this), amount), "Transfer failed");
        
        Stake storage userStake = stakes[msg.sender];
        
        if (userStake.amount > 0) {
            userStake.amount += amount;
        } else {
            stakes[msg.sender] = Stake({
                amount: amount,
                stakedSince: block.timestamp,
                unlockTime: block.timestamp + lockingPeriod,
                locked: true,
                slashingCount: 0
            });
        }
        
        totalStaked += amount;
        emit Staked(msg.sender, amount, block.timestamp + lockingPeriod);
    }
    
    function unstake() external nonReentrant {
        Stake storage userStake = stakes[msg.sender];
        require(userStake.amount > 0, "No stake");
        require(block.timestamp >= userStake.unlockTime, "Stake locked");
        require(!userStake.locked, "Stake is locked");
        
        uint256 amount = userStake.amount;
        userStake.amount = 0;
        totalStaked -= amount;
        
        require(nexusToken.transfer(msg.sender, amount), "Transfer failed");
        emit Unstaked(msg.sender, amount);
    }
    
    function slash(address user, string memory reason) external onlyGovernance {
        Stake storage userStake = stakes[user];
        require(userStake.amount > 0, "No stake to slash");
        
        uint256 slashAmount = (userStake.amount * slashPercentage) / 100;
        userStake.amount -= slashAmount;
        userStake.slashingCount++;
        totalStaked -= slashAmount;
        
        // Quemar tokens slashados
        require(nexusToken.transfer(address(0xdead), slashAmount), "Slash failed");
        emit Slashed(user, slashAmount, reason);
    }
    
    function calculateVotingPower(address user) external view returns (uint256) {
        Stake memory userStake = stakes[user];
        uint256 basePower = userStake.amount;
        
        // Bonificación por stake de largo plazo
        uint256 stakingDuration = block.timestamp - userStake.stakedSince;
        uint256 timeBonus = (basePower * min(stakingDuration, 365 days)) / (365 days * 10);
        
        // Penalización por slashing
        uint256 slashPenalty = (basePower * userStake.slashingCount * 5) / 100;
        
        return basePower + timeBonus - slashPenalty;
    }
    
    modifier onlyGovernance() {
        require(msg.sender == governance, "Only governance");
        _;
    }
    
    function min(uint256 a, uint256 b) internal pure returns (uint256) {
        return a < b ? a : b;
    }
}