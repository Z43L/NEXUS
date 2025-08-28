// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract NexusGovernance {
    IERC20 public nexusToken;
    
    struct Proposal {
        string description;
        bytes32 executionHash;
        uint256 voteCount;
        uint256 againstCount;
        uint256 startBlock;
        uint256 endBlock;
        bool executed;
        mapping(address => bool) voters;
    }
    
    mapping(uint256 => Proposal) public proposals;
    uint256 public proposalCount;
    uint256 public votingPeriod = 10000 blocks; // ~7 días
    uint256 public quorumThreshold = 100000 * 10**18; // 100k tokens
    
    event ProposalCreated(uint256 indexed proposalId, string description);
    event Voted(uint256 indexed proposalId, address indexed voter, bool support, uint256 weight);
    event ProposalExecuted(uint256 indexed proposalId, bool success);
    
    constructor(address _nexusToken) {
        nexusToken = IERC20(_nexusToken);
    }
    
    function createProposal(
        string calldata _description,
        bytes32 _executionHash
    ) external returns (uint256) {
        uint256 voterWeight = nexusToken.balanceOf(msg.sender);
        require(voterWeight >= quorumThreshold / 10, "Insufficient tokens");
        
        proposalCount++;
        Proposal storage proposal = proposals[proposalCount];
        proposal.description = _description;
        proposal.executionHash = _executionHash;
        proposal.startBlock = block.number;
        proposal.endBlock = block.number + votingPeriod;
        
        emit ProposalCreated(proposalCount, _description);
        return proposalCount;
    }
    
    function vote(uint256 _proposalId, bool _support) external {
        Proposal storage proposal = proposals[_proposalId];
        require(block.number >= proposal.startBlock, "Voting not started");
        require(block.number <= proposal.endBlock, "Voting ended");
        require(!proposal.voters[msg.sender], "Already voted");
        
        uint256 voteWeight = nexusToken.balanceOf(msg.sender);
        require(voteWeight > 0, "No voting power");
        
        proposal.voters[msg.sender] = true;
        
        if (_support) {
            proposal.voteCount += voteWeight;
        } else {
            proposal.againstCount += voteWeight;
        }
        
        emit Voted(_proposalId, msg.sender, _support, voteWeight);
    }
    
    function executeProposal(uint256 _proposalId) external {
        Proposal storage proposal = proposals[_proposalId];
        require(block.number > proposal.endBlock, "Voting not ended");
        require(!proposal.executed, "Already executed");
        require(proposal.voteCount > proposal.againstCount, "Proposal rejected");
        require(proposal.voteCount >= quorumThreshold, "Quorum not reached");
        
        proposal.executed = true;
        
        // Ejecutar lógica de la propuesta
        bool success = _executeProposalLogic(proposal.executionHash);
        
        emit ProposalExecuted(_proposalId, success);
    }
    
    function _executeProposalLogic(bytes32 _executionHash) internal returns (bool) {
        // Lógica de ejecución de propuestas
        // Esto podría interactuar con otros contratos del sistema
        return true;
    }
}