// Contratos para la Fase 3: Descentralización Completa
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract NexusToken is ERC20, Ownable {
    // Token ERC-20 para la economía de NEXUS
    constructor() ERC20("Nexus Token", "NEXUS") {
        _mint(msg.sender, 1000000000 * 10 ** decimals()); // 1B tokens iniciales
    }
    
    function mint(address to, uint256 amount) public onlyOwner {
        _mint(to, amount);
    }
}

contract Governance is Ownable {
    // Sistema de gobernanza descentralizada
    struct Proposal {
        string description;
        uint256 voteCount;
        bool executed;
        mapping(address => bool) voters;
    }
    
    NexusToken public token;
    mapping(uint256 => Proposal) public proposals;
    uint256 public proposalCount;
    
    constructor(address tokenAddress) {
        token = NexusToken(tokenAddress);
    }
    
    function createProposal(string memory description) public returns (uint256) {
        proposalCount++;
        proposals[proposalCount].description = description;
        return proposalCount;
    }
    
    function vote(uint256 proposalId) public {
        require(token.balanceOf(msg.sender) > 0, "Must hold tokens to vote");
        require(!proposals[proposalId].voters[msg.sender], "Already voted");
        
        proposals[proposalId].voters[msg.sender] = true;
        proposals[proposalId].voteCount += token.balanceOf(msg.sender);
    }
}

contract RewardSystem is Ownable {
    // Sistema de recompensas para participantes de la red
    mapping(address => uint256) public rewards;
    mapping(address => uint256) public lastClaim;
    
    function calculateReward(address participant, uint256 contribution) public onlyOwner returns (uint256) {
        // Lógica compleja de cálculo de recompensas basada en contribución
        uint256 baseReward = contribution * 100; // 100 tokens por unidad de contribución
        rewards[participant] += baseReward;
        return baseReward;
    }
    
    function claimReward() public {
        require(rewards[msg.sender] > 0, "No rewards to claim");
        require(block.timestamp > lastClaim[msg.sender] + 1 days, "Can only claim once per day");
        
        uint256 reward = rewards[msg.sender];
        rewards[msg.sender] = 0;
        lastClaim[msg.sender] = block.timestamp;
        
        // Transferir recompensas
        // Implementación específica depende del sistema de tokens
    }
}