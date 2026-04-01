// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title SensorRegistry
 * @notice Manages facility registration, sensor onboarding,
 *         calibration records, and sensor lifecycle for
 *         BChain-EmGuard emission monitoring system.
 * @author Mujahid Ullah Khan Afridi, NMSU Industrial Engineering
 */
contract SensorRegistry {

    address public regulatoryAuthority;

    // ── Structs ───────────────────────────────────────────────────────────────

    struct Facility {
        bytes32 facilityId;
        string  name;
        string  physicalAddress;
        string  facilityType;      // "MANUFACTURING","CEMENT","POWER","CHEMICAL"
        address officerWallet;
        bool    isActive;
        uint256 registrationDate;
    }

    struct Sensor {
        bytes32 sensorId;
        bytes32 facilityId;
        string  gasType;           // "CO2","CH4","NOx","PM25"
        string  sensorPrinciple;   // "NDIR","Electrochemical","Optical","Catalytic"
        string  manufacturer;
        uint256 installDate;
        uint256 lastCalibration;
        uint256 calibrationIntervalDays;
        bool    isActive;
        bytes32 calibCertHash;     // keccak256 of calibration certificate PDF
    }

    // ── State ─────────────────────────────────────────────────────────────────

    mapping(bytes32 => Facility) public facilities;
    mapping(bytes32 => Sensor)   public sensors;
    mapping(bytes32 => bytes32[]) public facilitySensorIds;
    mapping(address => bytes32)  public officerFacility;

    // ── Events ────────────────────────────────────────────────────────────────

    event FacilityRegistered(bytes32 indexed facilityId, string name,
        address officer, uint256 timestamp);
    event SensorRegistered(bytes32 indexed sensorId, bytes32 indexed facilityId,
        string gasType, string principle, uint256 timestamp);
    event CalibrationRecorded(bytes32 indexed sensorId, bytes32 certHash,
        uint256 timestamp);
    event SensorDeactivated(bytes32 indexed sensorId, string reason,
        uint256 timestamp);
    event CalibrationOverdue(bytes32 indexed sensorId, uint256 daysSinceLast);

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier onlyAuthority() {
        require(msg.sender == regulatoryAuthority, "Not authority");
        _;
    }

    modifier facilityExists(bytes32 _facilityId) {
        require(facilities[_facilityId].isActive, "Facility not active");
        _;
    }

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor() {
        regulatoryAuthority = msg.sender;
    }

    // ── Functions ─────────────────────────────────────────────────────────────

    function registerFacility(
        string memory _name,
        string memory _physicalAddress,
        string memory _facilityType,
        address _officerWallet
    ) external onlyAuthority returns (bytes32) {
        bytes32 facilityId = keccak256(abi.encodePacked(
            _name, _physicalAddress, block.timestamp
        ));
        facilities[facilityId] = Facility({
            facilityId:       facilityId,
            name:             _name,
            physicalAddress:  _physicalAddress,
            facilityType:     _facilityType,
            officerWallet:    _officerWallet,
            isActive:         true,
            registrationDate: block.timestamp
        });
        officerFacility[_officerWallet] = facilityId;
        emit FacilityRegistered(facilityId, _name, _officerWallet, block.timestamp);
        return facilityId;
    }

    function registerSensor(
        bytes32 _facilityId,
        string memory _gasType,
        string memory _sensorPrinciple,
        string memory _manufacturer,
        uint256 _calibIntervalDays,
        bytes32 _calibCertHash
    ) external onlyAuthority facilityExists(_facilityId) returns (bytes32) {
        bytes32 sensorId = keccak256(abi.encodePacked(
            _facilityId, _gasType, _sensorPrinciple, block.timestamp
        ));
        sensors[sensorId] = Sensor({
            sensorId:               sensorId,
            facilityId:             _facilityId,
            gasType:                _gasType,
            sensorPrinciple:        _sensorPrinciple,
            manufacturer:           _manufacturer,
            installDate:            block.timestamp,
            lastCalibration:        block.timestamp,
            calibrationIntervalDays: _calibIntervalDays,
            isActive:               true,
            calibCertHash:          _calibCertHash
        });
        facilitySensorIds[_facilityId].push(sensorId);
        emit SensorRegistered(sensorId, _facilityId, _gasType,
            _sensorPrinciple, block.timestamp);
        return sensorId;
    }

    function recordCalibration(
        bytes32 _sensorId,
        bytes32 _certHash
    ) external onlyAuthority {
        require(sensors[_sensorId].isActive, "Sensor inactive");
        sensors[_sensorId].lastCalibration = block.timestamp;
        sensors[_sensorId].calibCertHash   = _certHash;
        emit CalibrationRecorded(_sensorId, _certHash, block.timestamp);
    }

    function deactivateSensor(
        bytes32 _sensorId,
        string memory _reason
    ) external onlyAuthority {
        sensors[_sensorId].isActive = false;
        emit SensorDeactivated(_sensorId, _reason, block.timestamp);
    }

    function checkCalibrationStatus(bytes32 _sensorId)
        external view returns (bool overdue, uint256 daysSinceLast)
    {
        Sensor memory s = sensors[_sensorId];
        daysSinceLast = (block.timestamp - s.lastCalibration) / 1 days;
        overdue = daysSinceLast > s.calibrationIntervalDays;
    }

    function getFacilitySensors(bytes32 _facilityId)
        external view returns (bytes32[] memory)
    {
        return facilitySensorIds[_facilityId];
    }
}
