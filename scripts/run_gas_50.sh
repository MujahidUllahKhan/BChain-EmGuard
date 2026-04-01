#!/bin/bash
# ============================================================
# BChain-EmGuard Gas Measurement Script
# Runs the gas measurement test 50 times and reports statistics
# Usage: bash scripts/run_gas_50.sh
# ============================================================

echo "=================================================="
echo "  BChain-EmGuard Gas Measurement (n=50 runs)"
echo "=================================================="

RESULTS_DIR="scripts/gas_results"
mkdir -p $RESULTS_DIR

# Run gas measurement test 50 times
for i in $(seq 1 50); do
  printf "\rRun %d/50..." $i
  npx hardhat test tests/gas_measurement.test.js \
    --network hardhat \
    2>/dev/null | grep "gas used" >> $RESULTS_DIR/raw_gas.txt
done

echo ""
echo ""
echo "Raw results saved to $RESULTS_DIR/raw_gas.txt"
echo "Run python3 ml/analyze_gas.py to compute statistics."
