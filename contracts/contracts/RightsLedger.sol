// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract RightsLedger {
    address public owner;
    mapping(address => bool) public authorizedProviders;

    struct Licence {
        bytes32 contentHash;
        uint32 version;
        address issuer;
        uint64 expiresAt;
        bool derivativesAllowed;
        bool redistributionAllowed;
        bool revoked;
        bool exists;
        uint64 registeredAt;
    }
    mapping(bytes32 => Licence) private licences;
    mapping(bytes32 => mapping(bytes32 => bool)) private purposes;
    mapping(bytes32 => mapping(bytes32 => bool)) private regions;
    mapping(bytes32 => bytes32[]) private purposeKeys;
    mapping(bytes32 => bytes32[]) private regionKeys;

    event LicenceRegistered(bytes32 indexed datasetId, bytes32 indexed contentHash, uint32 version, address indexed issuer);
    event LicenceUpdated(bytes32 indexed datasetId, uint32 version, address indexed actor, uint64 timestamp);
    event LicenceRevoked(bytes32 indexed datasetId, address indexed issuer, uint64 timestamp);
    event ProviderAuthorized(address indexed provider, address indexed admin, uint64 timestamp);
    event ProviderAuthorizationRevoked(address indexed provider, address indexed admin, uint64 timestamp);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    error AlreadyRegistered(); error UnknownDataset(); error NotIssuer(); error NotOwner();
    error ProviderNotAuthorized(); error ProviderAlreadyAuthorized(); error InvalidInput();

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function authorizeProvider(address provider) external onlyOwner {
        if (provider == address(0)) revert InvalidInput();
        if (authorizedProviders[provider]) revert ProviderAlreadyAuthorized();
        authorizedProviders[provider] = true;
        emit ProviderAuthorized(provider, msg.sender, uint64(block.timestamp));
    }

    function revokeProvider(address provider) external onlyOwner {
        if (provider == address(0)) revert InvalidInput();
        if (!authorizedProviders[provider]) revert ProviderNotAuthorized();
        authorizedProviders[provider] = false;
        emit ProviderAuthorizationRevoked(provider, msg.sender, uint64(block.timestamp));
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidInput();
        address previousOwner = owner;
        owner = newOwner;
        emit OwnershipTransferred(previousOwner, newOwner);
    }

    function register(bytes32 datasetId, bytes32 contentHash, uint32 version, uint64 expiresAt,
        bool derivativesAllowed, bool redistributionAllowed, bytes32[] calldata allowedPurposes,
        bytes32[] calldata allowedRegions) external {
        if (!authorizedProviders[msg.sender]) revert ProviderNotAuthorized();
        if (datasetId == bytes32(0) || contentHash == bytes32(0) || version == 0 || expiresAt <= block.timestamp) revert InvalidInput();
        if (licences[datasetId].exists) revert AlreadyRegistered();
        licences[datasetId] = Licence(contentHash, version, msg.sender, expiresAt, derivativesAllowed, redistributionAllowed, false, true, uint64(block.timestamp));
        _setList(datasetId, allowedPurposes, allowedRegions);
        emit LicenceRegistered(datasetId, contentHash, version, msg.sender);
    }

    function update(bytes32 datasetId, bytes32 contentHash, uint32 version, uint64 expiresAt,
        bool derivativesAllowed, bool redistributionAllowed, bytes32[] calldata allowedPurposes,
        bytes32[] calldata allowedRegions) external {
        Licence storage l=licences[datasetId]; if(!l.exists) revert UnknownDataset(); if(msg.sender!=l.issuer) revert NotIssuer();
        if(contentHash==bytes32(0)||version<=l.version||expiresAt<=block.timestamp||l.revoked) revert InvalidInput();
        l.contentHash=contentHash; l.version=version; l.expiresAt=expiresAt; l.derivativesAllowed=derivativesAllowed; l.redistributionAllowed=redistributionAllowed;
        _clear(datasetId); _setList(datasetId,allowedPurposes,allowedRegions); emit LicenceUpdated(datasetId,version,msg.sender,uint64(block.timestamp));
    }

    function revoke(bytes32 datasetId) external { Licence storage l=licences[datasetId]; if(!l.exists) revert UnknownDataset(); if(msg.sender!=l.issuer) revert NotIssuer(); if(l.revoked) revert InvalidInput(); l.revoked=true; emit LicenceRevoked(datasetId,msg.sender,uint64(block.timestamp)); }
    function _clear(bytes32 id) private {
        for(uint i;i<purposeKeys[id].length;i++) purposes[id][purposeKeys[id][i]]=false;
        for(uint i;i<regionKeys[id].length;i++) regions[id][regionKeys[id][i]]=false;
        delete purposeKeys[id]; delete regionKeys[id];
    }
    function _setList(bytes32 id, bytes32[] calldata ps, bytes32[] calldata rs) private {
        for(uint i;i<ps.length;i++){ if(ps[i]==bytes32(0)||purposes[id][ps[i]]) revert InvalidInput(); purposes[id][ps[i]]=true; purposeKeys[id].push(ps[i]); }
        for(uint i;i<rs.length;i++){ if(rs[i]==bytes32(0)||regions[id][rs[i]]) revert InvalidInput(); regions[id][rs[i]]=true; regionKeys[id].push(rs[i]); }
    }
    function getLicence(bytes32 id) external view returns(Licence memory){ return licences[id]; }
    function verifyHash(bytes32 id, bytes32 suppliedHash) external view returns(bool){ Licence memory l=licences[id]; return l.exists&&l.contentHash==suppliedHash; }
    function permits(bytes32 id,bytes32 purpose,bytes32 region,bool derivatives,bool redistribution) external view returns(bool){ Licence memory l=licences[id]; return l.exists&&!l.revoked&&block.timestamp<l.expiresAt&&purposes[id][purpose]&&(regions[id][region]||regions[id][keccak256(abi.encodePacked("GLOBAL"))])&&(!derivatives||l.derivativesAllowed)&&(!redistribution||l.redistributionAllowed); }
}
