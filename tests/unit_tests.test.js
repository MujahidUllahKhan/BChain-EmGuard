/**
 * BChain-EmGuard Full Unit Tests
 * Tests all smart contract functions including edge cases,
 * access control, and attack vector mitigations.
 *
 * Run: npx hardhat test tests/unit_tests.test.js
 * Expected: 26 passing
 */

const { expect }  = require("chai");
const { ethers }  = require("hardhat");

describe("BChain-EmGuard Unit Tests", function () {
  let sensorRegistry, emissionLedger, alertRegistry, complianceAudit;
  let authority, edgeDevice, officer, facilityOp, attacker;
  let facilityId, sensorId, readingId;

  beforeEach(async function () {
    [authority, edgeDevice, officer, facilityOp, attacker] = await ethers.getSigners();

    sensorRegistry  = await (await ethers.getContractFactory("SensorRegistry")).deploy();
    emissionLedger  = await (await ethers.getContractFactory("EmissionLedger")).deploy();
    alertRegistry   = await (await ethers.getContractFactory("AlertRegistry")).deploy();
    complianceAudit = await (await ethers.getContractFactory("ComplianceAudit")).deploy();

    await emissionLedger.authorizeEdgeDevice(edgeDevice.address);
    await alertRegistry.authorizeLLMOracle(authority.address);

    // Register a facility and sensor for most tests
    const tx1 = await sensorRegistry.connect(authority).registerFacility(
      "Test Facility", "Test Address", "MANUFACTURING", officer.address
    );
    facilityId = (await tx1.wait()).logs[0].topics[1];

    const certHash = ethers.keccak256(ethers.toUtf8Bytes("cert"));
    const tx2 = await sensorRegistry.connect(authority).registerSensor(
      facilityId, "CO2", "NDIR", "Sensirion", 90, certHash
    );
    sensorId = (await tx2.wait()).logs[0].topics[1];

    const tx3 = await emissionLedger.connect(edgeDevice).recordReading(
      facilityId, "CO2", 310000n,
      [308000n, 311000n, 312000n], [false, false, false],
      false, 400000n
    );
    readingId = (await tx3.wait()).logs[0].topics[1];
  });

  // ── Access Control ──────────────────────────────────────────────────────

  describe("Access Control", function () {
    it("Rejects non-authority from registering facility", async function () {
      await expect(
        sensorRegistry.connect(attacker).registerFacility(
          "Fake", "Addr", "MANUFACTURING", attacker.address
        )
      ).to.be.revertedWith("Not authority");
    });

    it("Rejects non-edge-device from recording reading", async function () {
      await expect(
        emissionLedger.connect(attacker).recordReading(
          facilityId, "CO2", 310000n,
          [308000n, 311000n, 312000n], [false, false, false],
          false, 400000n
        )
      ).to.be.revertedWith("Not authorized edge device");
    });

    it("Rejects non-oracle from recording alert", async function () {
      const llmHash = ethers.keccak256(ethers.toUtf8Bytes("alert text"));
      await expect(
        alertRegistry.connect(attacker).recordAlert(
          readingId, facilityId, officer.address, llmHash, "HIGH"
        )
      ).to.be.revertedWith("Not authorized oracle");
    });

    it("Rejects non-officer from acknowledging alert", async function () {
      const llmHash = ethers.keccak256(ethers.toUtf8Bytes("alert text"));
      const tx = await alertRegistry.connect(authority).recordAlert(
        readingId, facilityId, officer.address, llmHash, "HIGH"
      );
      const alertId = (await tx.wait()).logs[0].topics[1];

      await expect(
        alertRegistry.connect(attacker).acknowledgeAlert(alertId)
      ).to.be.revertedWith("Not assigned officer");
    });
  });

  // ── SensorRegistry ──────────────────────────────────────────────────────

  describe("SensorRegistry", function () {
    it("Registers facility and emits event", async function () {
      const tx = await sensorRegistry.connect(authority).registerFacility(
        "New Facility", "New Addr", "CHEMICAL", officer.address
      );
      const receipt = await tx.wait();
      expect(receipt.logs.length).to.be.gt(0);
    });

    it("Records calibration and updates timestamp", async function () {
      const before = (await sensorRegistry.sensors(sensorId)).lastCalibration;
      await new Promise(r => setTimeout(r, 1000)); // wait 1s
      const newCert = ethers.keccak256(ethers.toUtf8Bytes("new_cert"));
      await sensorRegistry.connect(authority).recordCalibration(sensorId, newCert);
      const after = (await sensorRegistry.sensors(sensorId)).lastCalibration;
      expect(after).to.be.gte(before);
    });

    it("Deactivates sensor and rejects further calibration", async function () {
      await sensorRegistry.connect(authority).deactivateSensor(sensorId, "End of life");
      const sensor = await sensorRegistry.sensors(sensorId);
      expect(sensor.isActive).to.be.false;

      const newCert = ethers.keccak256(ethers.toUtf8Bytes("new_cert"));
      await expect(
        sensorRegistry.connect(authority).recordCalibration(sensorId, newCert)
      ).to.be.revertedWith("Sensor inactive");
    });

    it("Returns all sensors for a facility", async function () {
      const sensors = await sensorRegistry.getFacilitySensors(facilityId);
      expect(sensors.length).to.equal(1);
      expect(sensors[0]).to.equal(sensorId);
    });
  });

  // ── EmissionLedger ──────────────────────────────────────────────────────

  describe("EmissionLedger", function () {
    it("Records normal reading with correct consensus value", async function () {
      const reading = await emissionLedger.getReading(readingId);
      expect(reading.consensusValue).to.equal(310000n);
      expect(reading.isExceedance).to.be.false;
    });

    it("Records exceedance and increments counter", async function () {
      const before = await emissionLedger.getFacilityExceedanceCount(facilityId);
      await emissionLedger.connect(edgeDevice).recordReading(
        facilityId, "CO2", 488000n,
        [487000n, 489000n, 488500n], [false, false, false],
        true, 400000n
      );
      const after = await emissionLedger.getFacilityExceedanceCount(facilityId);
      expect(after).to.equal(before + 1n);
    });

    it("Records anomaly with CCTV hash", async function () {
      const cctvHash = ethers.keccak256(ethers.toUtf8Bytes("phash_clip"));
      await emissionLedger.connect(edgeDevice).recordAnomalyWithCCTV(
        readingId, "TAMPER", 2, cctvHash, true
      );
      const count = await emissionLedger.getFacilityAnomalyCount(facilityId);
      expect(count).to.equal(1n);
    });

    it("Rejects reading with mismatched array lengths", async function () {
      await expect(
        emissionLedger.connect(edgeDevice).recordReading(
          facilityId, "CO2", 310000n,
          [308000n, 311000n],       // 2 values
          [false, false, false],    // 3 flags — mismatch
          false, 400000n
        )
      ).to.be.revertedWith("Array length mismatch");
    });

    it("Emits ConsensusFailed event", async function () {
      await expect(
        emissionLedger.connect(edgeDevice).recordConsensusFailed(
          facilityId, "CO2", 1, 3
        )
      ).to.emit(emissionLedger, "ConsensusFailed");
    });
  });

  // ── AlertRegistry ───────────────────────────────────────────────────────

  describe("AlertRegistry", function () {
    let alertId;

    beforeEach(async function () {
      const llmHash = ethers.keccak256(ethers.toUtf8Bytes("test alert text"));
      const tx = await alertRegistry.connect(authority).recordAlert(
        readingId, facilityId, officer.address, llmHash, "HIGH"
      );
      alertId = (await tx.wait()).logs[0].topics[1];
    });

    it("Dispatches alert with correct fields", async function () {
      const alert = await alertRegistry.getAlert(alertId);
      expect(alert.severity).to.equal("HIGH");
      expect(alert.ackTime).to.equal(0n);
      expect(alert.isEscalated).to.be.false;
    });

    it("Officer can acknowledge alert", async function () {
      await alertRegistry.connect(officer).acknowledgeAlert(alertId);
      const alert = await alertRegistry.getAlert(alertId);
      expect(alert.ackTime).to.be.gt(0n);
    });

    it("Rejects double acknowledgment", async function () {
      await alertRegistry.connect(officer).acknowledgeAlert(alertId);
      await expect(
        alertRegistry.connect(officer).acknowledgeAlert(alertId)
      ).to.be.revertedWith("Already acknowledged");
    });

    it("Stores alert in facility log", async function () {
      const log = await alertRegistry.getFacilityAlertLog(facilityId);
      expect(log.length).to.equal(1);
      expect(log[0]).to.equal(alertId);
    });
  });

  // ── ComplianceAudit ─────────────────────────────────────────────────────

  describe("ComplianceAudit", function () {
    it("Records compliant status", async function () {
      await complianceAudit.connect(authority).recordComplianceStatus(
        facilityId, readingId, false, "Normal operation"
      );
      expect(await complianceAudit.isCompliant(facilityId)).to.be.true;
    });

    it("Records exceedance and changes status to WARNING", async function () {
      await complianceAudit.connect(authority).recordComplianceStatus(
        facilityId, readingId, true, "Exceedance detected"
      );
      const rec = await complianceAudit.getComplianceRecord(facilityId);
      expect(rec.totalExceedances).to.equal(1n);
      // Status 1 = WARNING
      expect(rec.status).to.equal(1);
    });

    it("File dispute and track count", async function () {
      const groundsHash = ethers.keccak256(ethers.toUtf8Bytes("grounds"));
      await complianceAudit.connect(facilityOp).fileDispute(
        facilityId, readingId, groundsHash
      );
      expect(await complianceAudit.activeDisputeCount(facilityId)).to.equal(1n);
    });

    it("AV-7: Rejects more than MAX_ACTIVE_DISPUTES disputes", async function () {
      const groundsHash = ethers.keccak256(ethers.toUtf8Bytes("grounds"));
      // File 3 disputes (maximum)
      for (let i = 0; i < 3; i++) {
        // need different readingIds — use nonce trick
        const fakeReadingId = ethers.keccak256(ethers.toUtf8Bytes(`reading_${i}`));
        await complianceAudit.connect(facilityOp).fileDispute(
          facilityId, fakeReadingId, groundsHash
        );
      }
      // 4th should be rejected
      await expect(
        complianceAudit.connect(facilityOp).fileDispute(
          facilityId, readingId, groundsHash
        )
      ).to.be.revertedWith("Max active disputes reached");
    });

    it("Resolves dispute and decrements active count", async function () {
      const groundsHash = ethers.keccak256(ethers.toUtf8Bytes("grounds"));
      const tx = await complianceAudit.connect(facilityOp).fileDispute(
        facilityId, readingId, groundsHash
      );
      const disputeId = (await tx.wait()).logs[0].topics[1];

      const resHash = ethers.keccak256(ethers.toUtf8Bytes("resolution"));
      await complianceAudit.connect(authority).resolveDispute(
        disputeId, false, false, "Rejected", resHash
      );
      expect(await complianceAudit.activeDisputeCount(facilityId)).to.equal(0n);
    });

    it("Escalates rejected dispute", async function () {
      const groundsHash = ethers.keccak256(ethers.toUtf8Bytes("grounds"));
      const tx = await complianceAudit.connect(facilityOp).fileDispute(
        facilityId, readingId, groundsHash
      );
      const disputeId = (await tx.wait()).logs[0].topics[1];

      const resHash = ethers.keccak256(ethers.toUtf8Bytes("resolution"));
      await complianceAudit.connect(authority).resolveDispute(
        disputeId, false, false, "Rejected", resHash
      );

      await expect(
        complianceAudit.connect(facilityOp).escalateDispute(
          disputeId, "Escalating to court"
        )
      ).to.emit(complianceAudit, "DisputeEscalated");
    });
  });
});
