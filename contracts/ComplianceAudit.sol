// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title ComplianceAudit
 * @notice Maintains the regulatory compliance status of each facility,
 *         manages dispute filings, and records enforcement decisions.
 *         Part of the BChain-EmGuard four-contract emission monitoring system.
 *
 * @author Mujahid Ullah Khan Afridi
 *         Department of Industrial Engineering
 *         New Mexico State University, Las Cruces, NM 88003
 *         mujahida@nmsu.edu
 *
 * @dev Deployed on Hyperledger Besu (IBFT 2.0).
 *      All write functions cost < 300,000 gas.
 *      All view functions are free (0 gas).
 */
contract ComplianceAudit {

    address public regulatoryAuthority;

    // ── Enums ─────────────────────────────────────────────────────────────────

    enum ComplianceStatus { COMPLIANT, WARNING, VIOLATION, SUSPENDED }
    enum DisputeStatus    { FILED, UNDER_REVIEW, UPHELD, REJECTED, ESCALATED }

    // ── Structs ───────────────────────────────────────────────────────────────

    struct ComplianceRecord {
        bytes32          facilityId;
        ComplianceStatus status;
        uint256          totalExceedances;
        uint256          totalViolations;
        uint256          lastViolationTimestamp;
        uint256          lastUpdated;
        bytes32          latestReadingId;   // linked to EmissionLedger
        string           notes;
    }

    struct Dispute {
        bytes32       disputeId;
        bytes32       facilityId;
        bytes32       readingId;        // disputed EmissionLedger reading
        address       filedBy;          // facility operator wallet
        bytes32       groundsHash;      // keccak256 of dispute document
        DisputeStatus status;
        uint256       filedAt;
        uint256       resolvedAt;
        string        resolution;       // plain-text resolution summary
        bytes32       resolutionHash;   // keccak256 of resolution document
        bool          correctionApplied;
    }

    struct EnforcementAction {
        bytes32 facilityId;
        bytes32 readingId;
        string  actionType;    // "WARNING_NOTICE","FINE","SHUTDOWN","PROSECUTION"
        uint256 fineAmountUSD; // 0 if not a fine
        bytes32 officerWallet;
        bytes32 documentHash;
        uint256 timestamp;
    }

    // ── State ─────────────────────────────────────────────────────────────────

    mapping(bytes32 => ComplianceRecord)    public complianceRecords;
    mapping(bytes32 => Dispute)             public disputes;
    mapping(bytes32 => bytes32[])           public facilityDisputes;
    mapping(bytes32 => EnforcementAction[]) public facilityEnforcement;

    uint256 public constant MAX_ACTIVE_DISPUTES = 3;  // AV-7 mitigation
    mapping(bytes32 => uint256) public activeDisputeCount;

    // ── Events ────────────────────────────────────────────────────────────────

    event ComplianceUpdated(
        bytes32 indexed facilityId,
        ComplianceStatus status,
        uint256 totalExceedances,
        uint256 timestamp
    );

    event DisputeFiled(
        bytes32 indexed disputeId,
        bytes32 indexed facilityId,
        bytes32 readingId,
        bytes32 groundsHash,
        uint256 timestamp
    );

    event DisputeResolved(
        bytes32 indexed disputeId,
        DisputeStatus   outcome,
        bool            correctionApplied,
        uint256         timestamp
    );

    event DisputeEscalated(
        bytes32 indexed disputeId,
        bytes32 indexed facilityId,
        string  reason,
        uint256 timestamp
    );

    event EnforcementRecorded(
        bytes32 indexed facilityId,
        string  actionType,
        uint256 fineAmountUSD,
        uint256 timestamp
    );

    // ── Modifiers ─────────────────────────────────────────────────────────────

    modifier onlyAuthority() {
        require(msg.sender == regulatoryAuthority, "Not authority");
        _;
    }

    // ── Constructor ───────────────────────────────────────────────────────────

    constructor() {
        regulatoryAuthority = msg.sender;
    }

    // ── Compliance Management ─────────────────────────────────────────────────

    /**
     * @notice Update compliance status after an emission reading event.
     * @param _facilityId    Facility identifier
     * @param _readingId     Linked EmissionLedger reading ID
     * @param _isExceedance  Whether the reading exceeded the threshold
     * @param _notes         Optional regulatory notes
     */
    function recordComplianceStatus(
        bytes32       _facilityId,
        bytes32       _readingId,
        bool          _isExceedance,
        string memory _notes
    ) external onlyAuthority {
        ComplianceRecord storage rec = complianceRecords[_facilityId];
        rec.facilityId       = _facilityId;
        rec.latestReadingId  = _readingId;
        rec.lastUpdated      = block.timestamp;
        rec.notes            = _notes;

        if (_isExceedance) {
            rec.totalExceedances++;
            rec.lastViolationTimestamp = block.timestamp;

            // Escalate status based on exceedance count
            if (rec.totalExceedances >= 10) {
                rec.status = ComplianceStatus.SUSPENDED;
            } else if (rec.totalExceedances >= 5) {
                rec.status = ComplianceStatus.VIOLATION;
                rec.totalViolations++;
            } else {
                rec.status = ComplianceStatus.WARNING;
            }
        } else {
            // Grace period: restore COMPLIANT only if no exceedance in 30 days
            if (block.timestamp > rec.lastViolationTimestamp + 30 days) {
                rec.status = ComplianceStatus.COMPLIANT;
            }
        }

        emit ComplianceUpdated(_facilityId, rec.status,
            rec.totalExceedances, block.timestamp);
    }

    // ── Dispute Management ────────────────────────────────────────────────────

    /**
     * @notice File a dispute against a specific emission reading.
     *         Rate-limited to MAX_ACTIVE_DISPUTES per facility (AV-7 mitigation).
     */
    function fileDispute(
        bytes32 _facilityId,
        bytes32 _readingId,
        bytes32 _groundsHash
    ) external returns (bytes32) {
        require(
            activeDisputeCount[_facilityId] < MAX_ACTIVE_DISPUTES,
            "Max active disputes reached"
        );

        bytes32 disputeId = keccak256(abi.encodePacked(
            _facilityId, _readingId, msg.sender, block.timestamp
        ));

        disputes[disputeId] = Dispute({
            disputeId:          disputeId,
            facilityId:         _facilityId,
            readingId:          _readingId,
            filedBy:            msg.sender,
            groundsHash:        _groundsHash,
            status:             DisputeStatus.FILED,
            filedAt:            block.timestamp,
            resolvedAt:         0,
            resolution:         "",
            resolutionHash:     bytes32(0),
            correctionApplied:  false
        });

        facilityDisputes[_facilityId].push(disputeId);
        activeDisputeCount[_facilityId]++;

        emit DisputeFiled(disputeId, _facilityId, _readingId,
            _groundsHash, block.timestamp);
        return disputeId;
    }

    /**
     * @notice Resolve a dispute (upheld or rejected).
     *         Corrections are additive — original reading is never modified.
     */
    function resolveDispute(
        bytes32       _disputeId,
        bool          _upheld,
        bool          _correctionApplied,
        string memory _resolution,
        bytes32       _resolutionHash
    ) external onlyAuthority {
        Dispute storage d = disputes[_disputeId];
        require(d.status == DisputeStatus.FILED ||
                d.status == DisputeStatus.UNDER_REVIEW,
                "Dispute not open");

        d.status             = _upheld ? DisputeStatus.UPHELD : DisputeStatus.REJECTED;
        d.resolvedAt         = block.timestamp;
        d.resolution         = _resolution;
        d.resolutionHash     = _resolutionHash;
        d.correctionApplied  = _correctionApplied;

        if (activeDisputeCount[d.facilityId] > 0) {
            activeDisputeCount[d.facilityId]--;
        }

        emit DisputeResolved(_disputeId, d.status,
            _correctionApplied, block.timestamp);
    }

    /**
     * @notice Escalate a rejected dispute to court/tribunal.
     *         Records the escalation immutably; original records untouched.
     */
    function escalateDispute(
        bytes32       _disputeId,
        string memory _reason
    ) external {
        Dispute storage d = disputes[_disputeId];
        require(msg.sender == d.filedBy, "Not dispute filer");
        require(d.status == DisputeStatus.REJECTED, "Can only escalate rejected disputes");
        d.status = DisputeStatus.ESCALATED;
        emit DisputeEscalated(_disputeId, d.facilityId, _reason, block.timestamp);
    }

    // ── Enforcement Recording ─────────────────────────────────────────────────

    function recordEnforcementAction(
        bytes32       _facilityId,
        bytes32       _readingId,
        string memory _actionType,
        uint256       _fineAmountUSD,
        bytes32       _documentHash
    ) external onlyAuthority {
        facilityEnforcement[_facilityId].push(EnforcementAction({
            facilityId:    _facilityId,
            readingId:     _readingId,
            actionType:    _actionType,
            fineAmountUSD: _fineAmountUSD,
            officerWallet: bytes32(uint256(uint160(msg.sender))),
            documentHash:  _documentHash,
            timestamp:     block.timestamp
        }));

        emit EnforcementRecorded(_facilityId, _actionType,
            _fineAmountUSD, block.timestamp);
    }

    // ── View Functions (free) ─────────────────────────────────────────────────

    function getComplianceRecord(bytes32 _facilityId)
        external view returns (ComplianceRecord memory)
    {
        return complianceRecords[_facilityId];
    }

    function getDispute(bytes32 _disputeId)
        external view returns (Dispute memory)
    {
        return disputes[_disputeId];
    }

    function getFacilityDisputeCount(bytes32 _facilityId)
        external view returns (uint256)
    {
        return facilityDisputes[_facilityId].length;
    }

    function getFacilityEnforcementCount(bytes32 _facilityId)
        external view returns (uint256)
    {
        return facilityEnforcement[_facilityId].length;
    }

    function isCompliant(bytes32 _facilityId)
        external view returns (bool)
    {
        return complianceRecords[_facilityId].status == ComplianceStatus.COMPLIANT;
    }
}
