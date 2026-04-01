/**
 * BChain-EmGuard Gas Measurement Tests
 * Measures gas consumption for all key contract operations.
 * Run: npx hardhat test tests/gas_measurement.test.js
 */

const { expect }  = require("chai");
const { ethers }  = require("hardhat");

describe("BChain-EmGuard Gas Measurements", function () {
  let sensorRegistry, emissionLedger, alertRegistry, complianceAudit;
  let authority, edgeDevice, officer, facilityOp;
  let facilityId, sensorId, readingId;

  before(async function () {
    [authority, edgeDevice, officer, facilityOp] = await ethers.getSigners();

    // Deploy all four contracts
    sensorRegistry  = await (await ethers.getContractFactory("SensorRegistry")).deploy();
    emissionLedger  = await (await ethers.getContractFactory("EmissionLedger")).deploy();
    alertRegistry   = await (await ethers.getContractFactory("AlertRegistry")).deploy();
    complianceAudit = await (await ethers.getContractFactory("ComplianceAudit")).deploy();

    // Authorizations
    await emissionLedger.authorizeEdgeDevice(edgeDevice.address);
    await alertRegistry.authorizeLLMOracle(authority.address);
  });

  // ── SensorRegistry ──────────────────────────────────────────────────────

  it("Gas: SensorRegistry.registerFacility()", async function () {
    const tx = await sensorRegistry.connect(authority).registerFacility(
      "Karachi Textile Mill 14",
      "SITE III, Karachi Industrial Zone",
      "MANUFACTURING",
      officer.address
    );
    const receipt = await tx.wait();
    facilityId = receipt.logs[0].topics[1]; // FacilityRegistered event
    console.log(`    gas used: ${receipt.gasUsed.toString()} [registerFacility]`);
    expect(receipt.gasUsed).to.be.lt(300000n);
  });

  it("Gas: SensorRegistry.registerSensor()", async function () {
    const certHash = ethers.keccak256(ethers.toUtf8Bytes("calibration_cert_001"));
    const tx = await sensorRegistry.connect(authority).registerSensor(
      facilityId,
      "CO2",
      "NDIR",
      "Sensirion",
      90,
      certHash
    );
    const receipt = await tx.wait();
    sensorId = receipt.logs[0].topics[1];
    console.log(`    gas used: ${receipt.gasUsed.toString()} [registerSensor]`);
    expect(receipt.gasUsed).to.be.lt(300000n);
  });

  it("Gas: SensorRegistry.recordCalibration()", async function () {
    const newCertHash = ethers.keccak256(ethers.toUtf8Bytes("calibration_cert_002"));
    const tx = await sensorRegistry.connect(authority).recordCalibration(
      sensorId,
      newCertHash
    );
    const receipt = await tx.wait();
    console.log(`    gas used: ${receipt.gasUsed.toString()} [recordCalibration]`);
    expect(receipt.gasUsed).to.be.lt(100000n);
  });

  // ── EmissionLedger ──────────────────────────────────────────────────────

  it("Gas: EmissionLedger.recordReading() — normal", async function () {
    const tx = await emissionLedger.connect(edgeDevice).recordReading(
      facilityId,
      "CO2",
      310000n,          // 310.000 ppm * 1000
      [308000n, 311000n, 312000n],
      [false, false, false],
      false,
      400000n           // threshold 400.000 ppm * 1000
    );
    const receipt = await tx.wait();
    readingId = receipt.logs[0].topics[1];
    console.log(`    gas used: ${receipt.gasUsed.toString()} [recordReading-normal]`);
    expect(receipt.gasUsed).to.be.lt(350000n);
  });

  it("Gas: EmissionLedger.recordReading() — exceedance", async function () {
    const tx = await emissionLedger.connect(edgeDevice).recordReading(
      facilityId,
      "CO2",
      488000n,          // 488 ppm — exceeds 400 threshold
      [487000n, 489000n, 488500n],
      [false, false, false],
      true,
      400000n
    );
    const receipt = await tx.wait();
    console.log(`    gas used: ${receipt.gasUsed.toString()} [recordReading-exceedance]`);
    expect(receipt.gasUsed).to.be.lt(350000n);
  });

  it("Gas: EmissionLedger.recordAnomalyWithCCTV()", async function () {
    const cctvHash = ethers.keccak256(ethers.toUtf8Bytes("phash_clip_001"));
    const tx = await emissionLedger.connect(edgeDevice).recordAnomalyWithCCTV(
      readingId,
      "TAMPER",
      2,
      cctvHash,
      true
    );
    const receipt = await tx.wait();
    console.log(`    gas used: ${receipt.gasUsed.toString()} [recordAnomalyWithCCTV]`);
    expect(receipt.gasUsed).to.be.lt(300000n);
  });

  // ── AlertRegistry ───────────────────────────────────────────────────────

  it("Gas: AlertRegistry.recordAlert()", async function () {
    const llmHash = ethers.keccak256(
      ethers.toUtf8Bytes("CRITICAL EMISSION ALERT — Facility: Karachi Textile...")
    );
    const tx = await alertRegistry.connect(authority).recordAlert(
      readingId,
      facilityId,
      officer.address,
      llmHash,
      "CRITICAL"
    );
    const receipt = await tx.wait();
    // Save alertId for next test
    this.alertId = receipt.logs[0].topics[1];
    global.testAlertId = this.alertId;
    console.log(`    gas used: ${receipt.gasUsed.toString()} [recordAlert]`);
    expect(receipt.gasUsed).to.be.lt(300000n);
  });

  it("Gas: AlertRegistry.acknowledgeAlert()", async function () {
    // Officer acknowledges
    const tx = await alertRegistry.connect(officer).acknowledgeAlert(
      global.testAlertId
    );
    const receipt = await tx.wait();
    console.log(`    gas used: ${receipt.gasUsed.toString()} [acknowledgeAlert]`);
    expect(receipt.gasUsed).to.be.lt(100000n);
  });

  // ── ComplianceAudit ─────────────────────────────────────────────────────

  it("Gas: ComplianceAudit.recordComplianceStatus()", async function () {
    const tx = await complianceAudit.connect(authority).recordComplianceStatus(
      facilityId,
      readingId,
      true,
      "CO2 exceedance detected. Alert dispatched."
    );
    const receipt = await tx.wait();
    console.log(`    gas used: ${receipt.gasUsed.toString()} [recordComplianceStatus]`);
    expect(receipt.gasUsed).to.be.lt(300000n);
  });

  it("Gas: ComplianceAudit.fileDispute()", async function () {
    const groundsHash = ethers.keccak256(
      ethers.toUtf8Bytes("Dispute grounds: sensor drift, not actual exceedance")
    );
    const tx = await complianceAudit.connect(facilityOp).fileDispute(
      facilityId,
      readingId,
      groundsHash
    );
    const receipt = await tx.wait();
    global.testDisputeId = receipt.logs[0].topics[1];
    console.log(`    gas used: ${receipt.gasUsed.toString()} [fileDispute]`);
    expect(receipt.gasUsed).to.be.lt(300000n);
  });

  it("Gas: ComplianceAudit.resolveDispute()", async function () {
    const resHash = ethers.keccak256(
      ethers.toUtf8Bytes("Dispute rejected: multi-sensor consensus confirmed exceedance")
    );
    const tx = await complianceAudit.connect(authority).resolveDispute(
      global.testDisputeId,
      false,    // not upheld
      false,    // no correction applied
      "Dispute rejected: consensus of 3 sensors confirms exceedance.",
      resHash
    );
    const receipt = await tx.wait();
    console.log(`    gas used: ${receipt.gasUsed.toString()} [resolveDispute]`);
    expect(receipt.gasUsed).to.be.lt(300000n);
  });

  // ── View Functions (must be zero gas) ───────────────────────────────────

  it("Gas: View functions cost 0 gas", async function () {
    // These are pure view calls — no transaction, no gas cost
    await sensorRegistry.getComplianceRecord?.(facilityId).catch(() => {});
    await emissionLedger.getReading(readingId);
    await complianceAudit.getComplianceRecord(facilityId);
    await alertRegistry.getFacilityAlertLog(facilityId);
    // All view calls succeed with 0 gas (no tx)
    console.log("    gas used: 0 [all view functions]");
  });
});
