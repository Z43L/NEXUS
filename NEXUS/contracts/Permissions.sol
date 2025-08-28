// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract NexusPermissions {
    struct Permission {
        address grantor;
        address grantee;
        bytes4 functionSelector;
        uint256 expiry;
        bytes conditions;
        bool revoked;
    }
    
    mapping(bytes32 => Permission) public permissions;
    mapping(address => mapping(bytes4 => bool)) public defaultPermissions;
    
    event PermissionGranted(
        bytes32 indexed permissionId,
        address indexed grantor,
        address indexed grantee,
        bytes4 functionSelector,
        uint256 expiry
    );
    
    event PermissionRevoked(bytes32 indexed permissionId);
    
    modifier onlyWithPermission(bytes4 _selector) {
        bytes32 permissionId = keccak256(abi.encodePacked(msg.sender, _selector));
        require(hasPermission(permissionId), "Permission denied");
        _;
    }
    
    function grantPermission(
        address _grantee,
        bytes4 _selector,
        uint256 _expiry,
        bytes calldata _conditions
    ) external returns (bytes32) {
        bytes32 permissionId = keccak256(abi.encodePacked(_grantee, _selector));
        
        permissions[permissionId] = Permission({
            grantor: msg.sender,
            grantee: _grantee,
            functionSelector: _selector,
            expiry: _expiry,
            conditions: _conditions,
            revoked: false
        });
        
        emit PermissionGranted(permissionId, msg.sender, _grantee, _selector, _expiry);
        return permissionId;
    }
    
    function hasPermission(bytes32 _permissionId) public view returns (bool) {
        Permission storage perm = permissions[_permissionId];
        
        return !perm.revoked &&
               perm.expiry > block.timestamp &&
               verifyConditions(perm.conditions);
    }
    
    function verifyConditions(bytes memory _conditions) internal pure returns (bool) {
        // Lógica de verificación de condiciones (límites de tiempo, uso, etc.)
        return true; // Simplificado para el ejemplo
    }
}