// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract SecurityProtections {
    // Protección contra reentrancy
    bool private _reentrancyLock;
    
    modifier nonReentrant() {
        require(!_reentrancyLock, "ReentrancyGuard: reentrant call");
        _reentrancyLock = true;
        _;
        _reentrancyLock = false;
    }
    
    // Protección contra front-running
    mapping(bytes32 => bool) public executedTransactions;
    
    modifier preventReplay(bytes32 _txHash) {
        require(!executedTransactions[_txHash], "Transaction already executed");
        _;
        executedTransactions[_txHash] = true;
    }
    
    // Límites de tasa (rate limiting)
    mapping(address => uint256) public lastOperation;
    mapping(address => uint256) public operationCount;
    
    modifier rateLimit(address _user, uint256 _delay, uint256 _maxOperations) {
        require(block.timestamp >= lastOperation[_user] + _delay, "Rate limit: too soon");
        require(operationCount[_user] < _maxOperations, "Rate limit: too many operations");
        _;
        lastOperation[_user] = block.timestamp;
        operationCount[_user]++;
        
        // Reset counter cada 24 horas
        if (block.timestamp - lastOperation[_user] > 1 days) {
            operationCount[_user] = 0;
        }
    }
    
    // Validación de inputs
    modifier validAddress(address _addr) {
        require(_addr != address(0), "Invalid address");
        _;
    }
    
    modifier validAmount(uint256 _amount) {
        require(_amount > 0, "Invalid amount");
        _;
    }
    
    // Safe math functions
    function safeAdd(uint256 a, uint256 b) internal pure returns (uint256) {
        uint256 c = a + b;
        require(c >= a, "SafeMath: addition overflow");
        return c;
    }
    
    function safeSub(uint256 a, uint256 b) internal pure returns (uint256) {
        require(b <= a, "SafeMath: subtraction overflow");
        return a - b;
    }
    
    function safeMul(uint256 a, uint256 b) internal pure returns (uint256) {
        if (a == 0) {
            return 0;
        }
        uint256 c = a * b;
        require(c / a == b, "SafeMath: multiplication overflow");
        return c;
    }
}