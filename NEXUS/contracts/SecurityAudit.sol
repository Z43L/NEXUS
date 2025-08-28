// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract SecurityAudit {
    struct AuditFinding {
        string severity;
        string description;
        string location;
        string recommendation;
        bool resolved;
        uint256 reportedAt;
        uint256 resolvedAt;
    }
    
    struct ContractAudit {
        address contractAddress;
        string version;
        uint256 auditDate;
        AuditFinding[] findings;
        uint256 score;
        bool approved;
    }
    
    mapping(address => ContractAudit) public contractAudits;
    mapping(address => bool) public approvedAuditors;
    
    event NewAudit(
        address indexed contractAddress,
        address indexed auditor,
        uint256 findingsCount,
        uint256 score
    );
    
    event FindingResolved(
        address indexed contractAddress,
        uint256 findingIndex,
        address resolvedBy
    );
    
    modifier onlyApprovedAuditor() {
        require(approvedAuditors[msg.sender], "Not an approved auditor");
        _;
    }
    
    function submitAudit(
        address _contractAddress,
        string calldata _version,
        AuditFinding[] calldata _findings
    ) external onlyApprovedAuditor {
        uint256 severityScore = 0;
        
        for (uint i = 0; i < _findings.length; i++) {
            severityScore += _calculateSeverityScore(_findings[i].severity);
        }
        
        uint256 auditScore = 100 - (severityScore * 10);
        auditScore = auditScore < 0 ? 0 : auditScore;
        
        contractAudits[_contractAddress] = ContractAudit({
            contractAddress: _contractAddress,
            version: _version,
            auditDate: block.timestamp,
            findings: _findings,
            score: auditScore,
            approved: auditScore >= 80
        });
        
        emit NewAudit(_contractAddress, msg.sender, _findings.length, auditScore);
    }
    
    function _calculateSeverityScore(string memory _severity) internal pure returns (uint256) {
        if (keccak256(abi.encodePacked(_severity)) == keccak256(abi.encodePacked("CRITICAL"))) {
            return 5;
        } else if (keccak256(abi.encodePacked(_severity)) == keccak256(abi.encodePacked("HIGH"))) {
            return 3;
        } else if (keccak256(abi.encodePacked(_severity)) == keccak256(abi.encodePacked("MEDIUM"))) {
            return 2;
        } else if (keccak256(abi.encodePacked(_severity)) == keccak256(abi.encodePacked("LOW"))) {
            return 1;
        }
        return 0;
    }
}