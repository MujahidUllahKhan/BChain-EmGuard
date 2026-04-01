/**
 * BChain-EmGuard Deployment Script
 * Deploys all four contracts in dependency order and links them.
 *
 * Usage:
 *   npx hardhat run scripts/deploy.js --network hardhat
 *   npx hardhat run scripts/deploy.js --network besu_local
 */

const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("=".repeat(60));
  console.log("  BChain-EmGuard Contract Deployment");
  console.log("=".repeat(60));
  console.log(`Deployer address : ${deployer.address}`);
  console.log(`Network          : ${network.name}`);
  console.log(`Block number     : ${await ethers.provider.getBlockNumber()}`);
  console.log("");

  // ── 1. SensorRegistry ────────────────────────────────────────────────────
  console.log("[1/4] Deploying SensorRegistry...");
  const SensorRegistry = await ethers.getContractFactory("SensorRegistry");
  const sensorRegistry = await SensorRegistry.deploy();
  await sensorRegistry.waitForDeployment();
  const srAddr = await sensorRegistry.getAddress();
  console.log(`      SensorRegistry  → ${srAddr}`);

  // ── 2. EmissionLedger ────────────────────────────────────────────────────
  console.log("[2/4] Deploying EmissionLedger...");
  const EmissionLedger = await ethers.getContractFactory("EmissionLedger");
  const emissionLedger = await EmissionLedger.deploy();
  await emissionLedger.waitForDeployment();
  const elAddr = await emissionLedger.getAddress();
  console.log(`      EmissionLedger  → ${elAddr}`);

  // Authorize deployer as edge device (for testing)
  await emissionLedger.authorizeEdgeDevice(deployer.address);
  console.log("      Edge device authorized for testing.");

  // ── 3. AlertRegistry ─────────────────────────────────────────────────────
  console.log("[3/4] Deploying AlertRegistry...");
  const AlertRegistry = await ethers.getContractFactory("AlertRegistry");
  const alertRegistry = await AlertRegistry.deploy();
  await alertRegistry.waitForDeployment();
  const arAddr = await alertRegistry.getAddress();
  console.log(`      AlertRegistry   → ${arAddr}`);

  // Authorize deployer as LLM oracle (for testing)
  await alertRegistry.authorizeLLMOracle(deployer.address);
  console.log("      LLM oracle authorized for testing.");

  // ── 4. ComplianceAudit ───────────────────────────────────────────────────
  console.log("[4/4] Deploying ComplianceAudit...");
  const ComplianceAudit = await ethers.getContractFactory("ComplianceAudit");
  const complianceAudit = await ComplianceAudit.deploy();
  await complianceAudit.waitForDeployment();
  const caAddr = await complianceAudit.getAddress();
  console.log(`      ComplianceAudit → ${caAddr}`);

  // ── Summary ───────────────────────────────────────────────────────────────
  console.log("");
  console.log("=".repeat(60));
  console.log("  DEPLOYMENT COMPLETE");
  console.log("=".repeat(60));
  console.log(`SensorRegistry  : ${srAddr}`);
  console.log(`EmissionLedger  : ${elAddr}`);
  console.log(`AlertRegistry   : ${arAddr}`);
  console.log(`ComplianceAudit : ${caAddr}`);
  console.log("");

  // Save addresses to file for test scripts
  const fs = require("fs");
  const addresses = {
    network:        network.name,
    deployer:       deployer.address,
    SensorRegistry: srAddr,
    EmissionLedger: elAddr,
    AlertRegistry:  arAddr,
    ComplianceAudit: caAddr,
    deployedAt:     new Date().toISOString(),
  };
  fs.writeFileSync(
    "scripts/deployed_addresses.json",
    JSON.stringify(addresses, null, 2)
  );
  console.log("Addresses saved → scripts/deployed_addresses.json");
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
