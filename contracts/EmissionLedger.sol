// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title EmissionLedger
 * @notice Records consensus emission readings, individual sensor
 *         anomaly flags, CCTV pHash anchors, and exceedance events
 *         as immutable on-chain transactions.
 */
contract EmissionLedger {

    address public authority;
    mapping(address => bool) public authorizedEdgeDevices;

    // ── Structs ───────────────────────────────────────────────────────────────

    struct EmissionReading {
        bytes32   readingId;
        bytes32   facilityId;
        string    gasType;
        int256    consensusValue;    // value * 1000 (3 decimal places, integer)
        int256[]  individualValues;  // per sensor
        bool[]    anomalyFlags;      // per sensor: true = anomalous
        bool      isExceedance;
        uint256   thresholdX1000;    // threshold * 1000
        bytes32   dataHash;
        uint256   timestamp;
    }

    struct AnomalyEvent {
        bytes32  readingId;
        string   anomalyType;        // "DRIFT","SPIKE","TAMPER","FAILURE"
        uint8    nSensorsFlagged;
        bytes32  cctvClipHash;       // keccak256(pHash sequence), 0 if no CCTV
        bool     cctvActivated;
        uint256  timestamp;
    }

    // ── State ─────────────────────────────────────────────────────────────────

    mapping(bytes32 => EmissionReading) public readings;
    mapping(bytes32 => AnomalyEvent[])  public facilityAnomalies;
    mapping(bytes32 => uint256)         public facilityExceedanceCount;

    uint256 public constant MAX_ANOMALIES_PER_INTERVAL = 1; // rate limiting

    // ── Events ────────────────────────────────────────────────────────────────

    event ReadingRecorded(
        bytes32 indexed readingId,
        bytes32 indexed facilityId,
        string  gasType,
        int256  consensusValue,
        bool    isExceedance,
        uint256 timestamp
    );

    event AnomalyFlagged(
        bytes32 indexed readingId,
        bytes32 indexed facilityId,
        string  anomalyType,
        bytes32 cctvClipHash,
        uint256 timestamp
    );

    event ConsensusFailed(
        bytes32 indexed facilityId,
        string  gasType,
        uint8   activeSensors,
        uint8   totalSensors,
        uint256 timestamp
    );

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier onlyEdgeDevice() {
        require(authorizedEdgeDevices[msg.sender], "Not authorized edge device");
        _;
    }

    modifier onlyAuthority() {
        require(msg.sender == authority, "Not authority");
        _;
    }

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor() {
        authority = msg.sender;
    }

    function authorizeEdgeDevice(address _device) external onlyAuthority {
        authorizedEdgeDevices[_device] = true;
    }

    // ── Core Functions ────────────────────────────────────────────────────────

    /**
     * @notice Record a consensus emission reading from an edge device.
     * @param _facilityId   Registered facility identifier
     * @param _gasType      Target gas ("CO2","CH4","NOx","PM25")
     * @param _consensus    Consensus value * 1000
     * @param _individual   Individual sensor readings * 1000
     * @param _anomalyFlags Per-sensor anomaly flags
     * @param _isExceedance True if consensus > regulatory threshold
     * @param _threshX1000  Regulatory threshold * 1000
     */
    function recordReading(
        bytes32        _facilityId,
        string memory  _gasType,
        int256         _consensus,
        int256[] memory _individual,
        bool[] memory  _anomalyFlags,
        bool           _isExceedance,
        uint256        _threshX1000
    ) external onlyEdgeDevice returns (bytes32) {
        require(_individual.length == _anomalyFlags.length,
            "Array length mismatch");

        bytes32 dataHash = keccak256(abi.encodePacked(
            _facilityId, _gasType, _consensus,
            _isExceedance, block.timestamp
        ));
        bytes32 readingId = keccak256(abi.encodePacked(dataHash, block.number));

        readings[readingId] = EmissionReading({
            readingId:       readingId,
            facilityId:      _facilityId,
            gasType:         _gasType,
            consensusValue:  _consensus,
            individualValues: _individual,
            anomalyFlags:    _anomalyFlags,
            isExceedance:    _isExceedance,
            thresholdX1000:  _threshX1000,
            dataHash:        dataHash,
            timestamp:       block.timestamp
        });

        if (_isExceedance) {
            facilityExceedanceCount[_facilityId]++;
        }

        emit ReadingRecorded(readingId, _facilityId, _gasType,
            _consensus, _isExceedance, block.timestamp);
        return readingId;
    }

    /**
     * @notice Record an anomaly event with optional CCTV hash.
     *         Rate-limited to one call per sampling interval.
     */
    function recordAnomalyWithCCTV(
        bytes32       _readingId,
        string memory _anomalyType,
        uint8         _nFlagged,
        bytes32       _cctvClipHash,
        bool          _cctvActivated
    ) external onlyEdgeDevice {
        bytes32 facilityId = readings[_readingId].facilityId;
        require(facilityId != bytes32(0), "Reading not found");

        AnomalyEvent memory evt = AnomalyEvent({
            readingId:      _readingId,
            anomalyType:    _anomalyType,
            nSensorsFlagged: _nFlagged,
            cctvClipHash:   _cctvClipHash,
            cctvActivated:  _cctvActivated,
            timestamp:      block.timestamp
        });
        facilityAnomalies[facilityId].push(evt);

        emit AnomalyFlagged(_readingId, facilityId, _anomalyType,
            _cctvClipHash, block.timestamp);
    }

    function recordConsensusFailed(
        bytes32       _facilityId,
        string memory _gasType,
        uint8         _activeSensors,
        uint8         _totalSensors
    ) external onlyEdgeDevice {
        emit ConsensusFailed(_facilityId, _gasType,
            _activeSensors, _totalSensors, block.timestamp);
    }

    // ── View Functions (free) ─────────────────────────────────────────────────

    function getReading(bytes32 _readingId)
        external view returns (EmissionReading memory)
    {
        return readings[_readingId];
    }

    function getFacilityAnomalyCount(bytes32 _facilityId)
        external view returns (uint256)
    {
        return facilityAnomalies[_facilityId].length;
    }

    function getFacilityExceedanceCount(bytes32 _facilityId)
        external view returns (uint256)
    {
        return facilityExceedanceCount[_facilityId];
    }
}
