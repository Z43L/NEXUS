// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract KnowledgeRegistry {
    struct KnowledgeRecord {
        bytes32 contentHash;
        string category;
        uint256 blockNumber;
        bytes32 transactionHash;
        uint256 validationCount;
        uint8 confidenceScore;
        string metadata;
        bool active;
    }
    
    struct UpdateProposal {
        bytes32 originalHash;
        bytes32 proposedHash;
        address proposer;
        string reason;
        uint256 supportVotes;
        uint256 opposeVotes;
        mapping(address => bool) hasVoted;
        bool executed;
    }
    
    mapping(bytes32 => KnowledgeRecord) public knowledgeRecords;
    mapping(bytes32 => UpdateProposal) public updateProposals;
    mapping(address => uint256) public validatorReputation;
    
    uint256 public constant MIN_VALIDATIONS = 3;
    uint256 public constant VOTING_PERIOD = 7 days;
    
    event KnowledgeRegistered(
        bytes32 indexed knowledgeHash,
        address indexed submitter,
        string category,
        uint256 validationCount
    );
    
    event ValidationRecorded(
        bytes32 indexed knowledgeHash,
        address indexed validator,
        bool supported,
        uint8 confidence
    );
    
    event UpdateProposed(
        bytes32 indexed proposalHash,
        bytes32 indexed originalHash,
        address proposer,
        string reason
    );
    
    event UpdateVoted(
        bytes32 indexed proposalHash,
        address voter,
        bool support,
        string rationale
    );
    
    event UpdateExecuted(
        bytes32 indexed proposalHash,
        bytes32 indexed newKnowledgeHash,
        bool success
    );
    
    modifier onlyValidKnowledge(bytes32 knowledgeHash) {
        require(knowledgeRecords[knowledgeHash].contentHash != 0, "Knowledge not found");
        _;
    }
    
    function registerKnowledge(
        bytes32 knowledgeHash,
        bytes32 contentHash,
        string calldata category,
        string calldata metadata
    ) external returns (bool) {
        require(knowledgeRecords[knowledgeHash].contentHash == 0, "Knowledge already exists");
        
        knowledgeRecords[knowledgeHash] = KnowledgeRecord({
            contentHash: contentHash,
            category: category,
            blockNumber: block.number,
            transactionHash: blockhash(block.number - 1),
            validationCount: 1, // Auto-validación inicial
            confidenceScore: 70, // Confianza inicial moderada
            metadata: metadata,
            active: true
        });
        
        // Auto-validación inicial
        emit ValidationRecorded(knowledgeHash, msg.sender, true, 70);
        emit KnowledgeRegistered(knowledgeHash, msg.sender, category, 1);
        
        return true;
    }
    
    function validateKnowledge(
        bytes32 knowledgeHash,
        bool support,
        uint8 confidence
    ) external onlyValidKnowledge(knowledgeHash) {
        KnowledgeRecord storage record = knowledgeRecords[knowledgeHash];
        
        // Actualizar contadores de validación
        if (support) {
            record.validationCount++;
            record.confidenceScore = uint8((uint256(record.confidenceScore) * (record.validationCount - 1) + confidence) / record.validationCount);
        }
        
        emit ValidationRecorded(knowledgeHash, msg.sender, support, confidence);
        
        // Actualizar reputación del validador
        _updateValidatorReputation(msg.sender, support, confidence, record.confidenceScore);
    }
    
    function _updateValidatorReputation(
        address validator,
        bool support,
        uint8 submittedConfidence,
        uint8 currentConfidence
    ) internal {
        uint256 confidenceDiff = submittedConfidence > currentConfidence 
            ? submittedConfidence - currentConfidence
            : currentConfidence - submittedConfidence;
        
        if (support) {
            // Recompensa por validación precisa
            uint256 reward = 100 - confidenceDiff;
            validatorReputation[validator] += reward;
        } else {
            // Penalización por desacuerdo sin justificación
            validatorReputation[validator] -= confidenceDiff;
        }
    }
    
    function proposeUpdate(
        bytes32 originalHash,
        bytes32 proposedHash,
        string calldata reason
    ) external onlyValidKnowledge(originalHash) returns (bytes32) {
        bytes32 proposalHash = keccak256(abi.encodePacked(originalHash, proposedHash, block.timestamp));
        
        UpdateProposal storage proposal = updateProposals[proposalHash];
        proposal.originalHash = originalHash;
        proposal.proposedHash = proposedHash;
        proposal.proposer = msg.sender;
        proposal.reason = reason;
        proposal.supportVotes = 0;
        proposal.opposeVotes = 0;
        proposal.executed = false;
        
        emit UpdateProposed(proposalHash, originalHash, msg.sender, reason);
        return proposalHash;
    }
    
    function voteOnUpdate(
        bytes32 proposalHash,
        bool support,
        string calldata rationale
    ) external {
        UpdateProposal storage proposal = updateProposals[proposalHash];
        require(!proposal.hasVoted[msg.sender], "Already voted");
        require(block.timestamp <= proposal.creationTime + VOTING_PERIOD, "Voting period ended");
        
        proposal.hasVoted[msg.sender] = true;
        
        if (support) {
            proposal.supportVotes++;
        } else {
            proposal.opposeVotes++;
        }
        
        emit UpdateVoted(proposalHash, msg.sender, support, rationale);
    }
}