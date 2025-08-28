// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract NexusToken is ERC20, Ownable {
    mapping(address => bool) public serviceProviders;
    mapping(address => uint256) public serviceFees;
    
    event ServicePayment(address indexed user, address indexed provider, uint256 amount);
    event ProviderRegistered(address indexed provider, uint256 feeRate);
    
    constructor(uint256 initialSupply) ERC20("Nexus Token", "NEX") {
        _mint(msg.sender, initialSupply);
    }
    
    function payForService(address provider, uint256 amount) external {
        require(serviceProviders[provider], "Invalid service provider");
        require(balanceOf(msg.sender) >= amount, "Insufficient balance");
        
        uint256 fee = amount * serviceFees[provider] / 10000;
        uint256 netAmount = amount - fee;
        
        _transfer(msg.sender, provider, netAmount);
        
        if (fee > 0) {
            _transfer(msg.sender, address(this), fee);
        }
        
        emit ServicePayment(msg.sender, provider, amount);
    }
    
    function registerServiceProvider(address provider, uint256 feeRate) external onlyOwner {
        serviceProviders[provider] = true;
        serviceFees[provider] = feeRate;
        emit ProviderRegistered(provider, feeRate);
    }
}