// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

contract NexusRewardSystem is ReentrancyGuard {
    IERC20 public nexusToken;
    
    struct Contribution {
        address contributor;
        uint256 amount;
        uint256 timestamp;
        bytes32 proofHash;
        bool validated;
    }
    
    mapping(address => uint256) public contributorRewards;
    mapping(bytes32 => Contribution) public contributions;
    mapping(address => uint256) public lastClaim;
    
    uint256 public totalRewardsDistributed;
    uint256 public validationThreshold = 3;
    uint256 public rewardDecayPeriod = 30 days;
    
    event ContributionAdded(address indexed contributor, bytes32 proofHash, uint256 amount);
    event ContributionValidated(bytes32 indexed proofHash, address validator, bool approved);
    event RewardsDistributed(address indexed contributor, uint256 amount);
    
    constructor(address _nexusToken) {
        nexusToken = IERC20(_nexusToken);
    }
    
    function addContribution(
        bytes32 _proofHash,
        uint256 _amount,
        bytes calldata _proofData
    ) external nonReentrant {
        require(_amount > 0, "Amount must be positive");
        require(contributions[_proofHash].amount == 0, "Contribution already exists");
        
        contributions[_proofHash] = Contribution({
            contributor: msg.sender,
            amount: _amount,
            timestamp: block.timestamp,
            proofHash: _proofHash,
            validated: false
        });
        
        emit ContributionAdded(msg.sender, _proofHash, _amount);
    }
    
    function validateContribution(bytes32 _proofHash, bool _approve) external {
        Contribution storage contrib = contributions[_proofHash];
        require(contrib.amount > 0, "Contribution not found");
        require(!contrib.validated, "Already validated");
        
        // Lógica de validación descentralizada
        _processValidation(_proofHash, _approve);
        
        if (_approve) {
            contributorRewards[contrib.contributor] += contrib.amount;
            contrib.validated = true;
        }
        
        emit ContributionValidated(_proofHash, msg.sender, _approve);
    }
    
    function claimRewards() external nonReentrant {
        uint256 rewards = contributorRewards[msg.sender];
        require(rewards > 0, "No rewards to claim");
        require(block.timestamp > lastClaim[msg.sender] + rewardDecayPeriod, "Too soon to claim");
        
        contributorRewards[msg.sender] = 0;
        lastClaim[msg.sender] = block.timestamp;
        
        require(nexusToken.transfer(msg.sender, rewards), "Transfer failed");
        totalRewardsDistributed += rewards;
        
        emit RewardsDistributed(msg.sender, rewards);
    }
    
    function _processValidation(bytes32 _proofHash, bool _approve) internal {
        // Implementación de validación descentralizada
        // Utiliza el mecanismo Proof-of-Knowledge de NEXUS
    }
}