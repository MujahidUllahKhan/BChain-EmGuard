// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title AlertRegistry
 * @notice Records LLM-generated notification hashes, officer
 *         acknowledgments, and escalation events immutably on-chain.
 */
contract AlertRegistry {

    address public authority;
    mapping(address => bool) public authorizedLLMOracles;

    // ── Structs ───────────────────────────────────────────────────────────────

    struct Alert {
        bytes32 alertId;
        bytes32 readingId;
        bytes32 facilityId;
        address officerWallet;
        bytes32 llmSummaryHash;  // keccak256 of full LLM-generated alert text
        string  severity;        // "LOW","MEDIUM","HIGH","CRITICAL"
        uint256 dispatchTime;
        uint256 ackTime;         // 0 = unacknowledged
        bool    isEscalated;
        address escalatedTo;
        uint256 escalationTime;
    }

    uint256 public constant ACK_TIMEOUT = 1800;  // 30 minutes in seconds

    // ── State ─────────────────────────────────────────────────────────────────

    mapping(bytes32 => Alert) public alerts;
    mapping(bytes32 => bytes32[]) public facilityAlerts;
    mapping(address => bytes32[]) public officerAlerts;

    // ── Events ────────────────────────────────────────────────────────────────

    event AlertDispatched(
        bytes32 indexed alertId,
        bytes32 indexed facilityId,
        address officer,
        string  severity,
        bytes32 llmHash,
        uint256 timestamp
    );

    event AlertAcknowledged(
        bytes32 indexed alertId,
        address officer,
        uint256 responseTime,
        uint256 timestamp
    );

    event AlertEscalated(
        bytes32 indexed alertId,
        address escalatedTo,
        string  reason,
        uint256 timestamp
    );

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier onlyOracle() {
        require(authorizedLLMOracles[msg.sender], "Not authorized oracle");
        _;
    }

    modifier onlyAuthority() {
        require(msg.sender == authority, "Not authority");
        _;
    }

    constructor() {
        authority = msg.sender;
    }

    function authorizeLLMOracle(address _oracle) external onlyAuthority {
        authorizedLLMOracles[_oracle] = true;
    }

    // ── Core Functions ────────────────────────────────────────────────────────

    function recordAlert(
        bytes32       _readingId,
        bytes32       _facilityId,
        address       _officerWallet,
        bytes32       _llmSummaryHash,
        string memory _severity
    ) external onlyOracle returns (bytes32) {
        bytes32 alertId = keccak256(abi.encodePacked(
            _readingId, _officerWallet, block.timestamp
        ));
        alerts[alertId] = Alert({
            alertId:        alertId,
            readingId:      _readingId,
            facilityId:     _facilityId,
            officerWallet:  _officerWallet,
            llmSummaryHash: _llmSummaryHash,
            severity:       _severity,
            dispatchTime:   block.timestamp,
            ackTime:        0,
            isEscalated:    false,
            escalatedTo:    address(0),
            escalationTime: 0
        });
        facilityAlerts[_facilityId].push(alertId);
        officerAlerts[_officerWallet].push(alertId);

        emit AlertDispatched(alertId, _facilityId, _officerWallet,
            _severity, _llmSummaryHash, block.timestamp);
        return alertId;
    }

    function acknowledgeAlert(bytes32 _alertId) external {
        Alert storage alert = alerts[_alertId];
        require(msg.sender == alert.officerWallet, "Not assigned officer");
        require(alert.ackTime == 0, "Already acknowledged");
        alert.ackTime = block.timestamp;
        uint256 responseTime = block.timestamp - alert.dispatchTime;
        emit AlertAcknowledged(_alertId, msg.sender, responseTime, block.timestamp);
    }

    function escalateAlert(
        bytes32       _alertId,
        address       _escalateTo,
        string memory _reason
    ) external onlyOracle {
        Alert storage alert = alerts[_alertId];
        require(!alert.isEscalated, "Already escalated");
        require(
            block.timestamp >= alert.dispatchTime + ACK_TIMEOUT,
            "Ack timeout not reached"
        );
        alert.isEscalated    = true;
        alert.escalatedTo    = _escalateTo;
        alert.escalationTime = block.timestamp;
        emit AlertEscalated(_alertId, _escalateTo, _reason, block.timestamp);
    }

    // ── View Functions ────────────────────────────────────────────────────────

    function getAlert(bytes32 _alertId)
        external view returns (Alert memory)
    {
        return alerts[_alertId];
    }

    function getFacilityAlertLog(bytes32 _facilityId)
        external view returns (bytes32[] memory)
    {
        return facilityAlerts[_facilityId];
    }

    function isAckOverdue(bytes32 _alertId)
        external view returns (bool)
    {
        Alert memory a = alerts[_alertId];
        return (a.ackTime == 0 &&
            block.timestamp >= a.dispatchTime + ACK_TIMEOUT);
    }
}
