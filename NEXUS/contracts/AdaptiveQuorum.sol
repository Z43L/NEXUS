// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract AdaptiveQuorum {
    struct Proposal {
        string description;
        uint256 forVotes;
        uint256 againstVotes;
        uint256 totalVotesAtCreation;
        uint256 startBlock;
        uint256 endBlock;
        uint256 quorumRequired;
        ProposalType proposalType;
        bool executed;
    }
    
    enum ProposalType {
        PARAMETER_CHANGE,    // Cambio de parámetros
        TREASURY,           // Gestión de tesorería
        PROTOCOL_UPGRADE,   // Actualización de protocolo
        EMERGENCY           // Emergencia
    }
    
    mapping(uint256 => Proposal) public proposals;
    mapping(ProposalType => uint256) public baseQuorumRequirements;
    mapping(uint256 => uint256) public participationHistory;
    
    uint256 public proposalCount;
    uint256 public constant QUORUM_UPDATE_INTERVAL = 10000 blocks;
    
    event QuorumUpdated(ProposalType proposalType, uint256 newQuorum);
    
    constructor() {
        // Configurar quórums base para cada tipo de propuesta
        baseQuorumRequirements[ProposalType.PARAMETER_CHANGE] = 100000 * 10**18; // 100k tokens
        baseQuorumRequirements[ProposalType.TREASURY] = 200000 * 10**18;       // 200k tokens
        baseQuorumRequirements[ProposalType.PROTOCOL_UPGRADE] = 500000 * 10**18; // 500k tokens
        baseQuorumRequirements[ProposalType.EMERGENCY] = 250000 * 10**18;      // 250k tokens
    }
    
    function calculateAdaptiveQuorum(uint256 proposalId) public view returns (uint256) {
        Proposal storage proposal = proposals[proposalId];
        uint256 baseQuorum = baseQuorumRequirements[proposal.proposalType];
        
        // Ajustar basado en participación histórica
        uint256 historicalParticipation = participationHistory[proposalId];
        uint256 participationFactor = historicalParticipation * 100 / getTotalSupply();
        
        // Quórum más bajo para alta participación histórica
        if (participationFactor > 60) {
            return baseQuorum * 80 / 100; // 20% reduction
        } else if (participationFactor < 30) {
            return baseQuorum * 120 / 100; // 20% increase
        }
        
        return baseQuorum;
    }
    
    function updateQuorumRequirements() external {
        require(block.number % QUORUM_UPDATE_INTERVAL == 0, "Not update time");
        
        // Ajustar quórums basado en participación reciente
        uint256 recentParticipation = getRecentParticipation();
        
        for (uint256 i = 0; i < uint256(ProposalType.EMERGENCY); i++) {
            ProposalType proposalType = ProposalType(i);
            uint256 newQuorum = baseQuorumRequirements[proposalType];
            
            if (recentParticipation < 30) {
                newQuorum = newQuorum * 90 / 100; // Reduce quorum for low participation
            } else if (recentParticipation > 70) {
                newQuorum = newQuorum * 110 / 100; // Increase quorum for high participation
            }
            
            baseQuorumRequirements[proposalType] = newQuorum;
            emit QuorumUpdated(proposalType, newQuorum);
        }
    }
}