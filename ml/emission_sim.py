"""
BChain-EmGuard Simulation Framework
====================================
Simulates multi-sensor industrial emission monitoring with
injected anomalies and evaluates detection performance.

Usage:
    python emission_sim.py

All results are reproducible with seed=42.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings("ignore")

# ─── Reproducibility ──────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)

# ─── Simulation Parameters ────────────────────────────────────────────────────
N_FACILITIES    = 10
N_SENSORS       = 3          # per gas type per facility
GAS_TYPES       = ["CO2", "CH4", "NOx", "PM25"]
SAMPLE_INTERVAL = 60         # seconds
SIM_DAYS        = 30
N_SAMPLES       = SIM_DAYS * 24 * 60  # 43,200 per sensor

# Regulatory thresholds (ppm for gases, ug/m3 for PM)
THRESHOLDS = {"CO2": 400.0, "CH4": 1.9, "NOx": 0.1, "PM25": 35.0}

# Baseline emission levels (fraction of threshold, mean)
BASELINE_FRAC   = {"CO2": 0.75, "CH4": 0.65, "NOx": 0.70, "PM25": 0.60}

# Sensor noise model (std as fraction of reading)
NOISE_STD_FRAC  = 0.02

# Anomaly injection counts per gas per run
ANOMALY_COUNTS  = {
    "DRIFT":           120,
    "SPIKE":            80,
    "TAMPER":           40,
    "FAILURE":          60,
    "GENUINE_EXCEEDANCE": 200
}

TAU             = 3.0        # sigma threshold for consensus detection


# ─── Emission Profile Generation ──────────────────────────────────────────────

def generate_emission_profile(gas: str, n_samples: int) -> np.ndarray:
    """
    Generate a realistic baseline emission time series using
    diurnal variation, weekly patterns, and Gaussian noise.
    Based on EPA CEMS industrial emission profile characteristics.
    """
    threshold = THRESHOLDS[gas]
    base_level = BASELINE_FRAC[gas] * threshold

    t = np.arange(n_samples)

    # Diurnal variation: higher emissions during working hours
    hour_of_day = (t // 60) % 24
    diurnal = 0.15 * base_level * np.sin(2 * np.pi * hour_of_day / 24 - np.pi/2)

    # Weekly variation: lower emissions on weekends
    day_of_week = (t // 1440) % 7
    weekly = np.where(day_of_week >= 5, -0.10 * base_level, 0.0)

    # Slow trend (maintenance cycles)
    trend = 0.05 * base_level * np.sin(2 * np.pi * t / (n_samples * 0.3))

    # Random process noise
    noise = np.random.normal(0, NOISE_STD_FRAC * base_level, n_samples)

    profile = base_level + diurnal + weekly + trend + noise
    return np.clip(profile, 0.1 * threshold, 0.95 * threshold)


def add_sensor_noise(profile: np.ndarray, sensor_id: int) -> np.ndarray:
    """Add per-sensor measurement noise (heterogeneous sensors have different noise levels)."""
    noise_factors = {0: 1.0, 1: 1.3, 2: 0.8}  # Different sensor types
    noise_std = NOISE_STD_FRAC * noise_factors.get(sensor_id, 1.0) * np.mean(profile)
    return profile + np.random.normal(0, noise_std, len(profile))


# ─── Anomaly Injection ────────────────────────────────────────────────────────

def inject_drift(readings: np.ndarray, start: int, duration: int,
                 direction: float = -0.4) -> tuple:
    """Inject a gradual drift in one sensor (simulates calibration offset)."""
    result = readings.copy()
    labels = np.zeros(len(readings), dtype=int)
    end = min(start + duration, len(readings))
    drift = np.linspace(0, direction * np.mean(readings[start:end]), end - start)
    result[start:end] += drift
    labels[start:end] = 1
    return result, labels


def inject_spike(readings: np.ndarray, positions: list) -> tuple:
    """Inject instantaneous spikes."""
    result = readings.copy()
    labels = np.zeros(len(readings), dtype=int)
    for pos in positions:
        if pos < len(readings):
            spike_magnitude = np.random.uniform(3.0, 6.0) * np.std(readings)
            result[pos] += spike_magnitude * np.random.choice([-1, 1])
            labels[pos] = 1
    return result, labels


def inject_tamper(readings: np.ndarray, start: int, duration: int,
                  reduction: float = 0.15) -> tuple:
    """
    Simulate clean-air injection tampering: sensor reports implausibly low values
    while true emissions are ongoing.
    """
    result = readings.copy()
    labels = np.zeros(len(readings), dtype=int)
    end = min(start + duration, len(readings))
    result[start:end] = reduction * np.mean(readings)
    labels[start:end] = 1
    return result, labels


def inject_failure(readings: np.ndarray, start: int, duration: int) -> tuple:
    """Simulate complete sensor failure (outputs zero or NaN)."""
    result = readings.copy()
    labels = np.zeros(len(readings), dtype=int)
    end = min(start + duration, len(readings))
    result[start:end] = 0.0
    labels[start:end] = 1
    return result, labels


def inject_genuine_exceedance(readings: np.ndarray, start: int, duration: int,
                               threshold: float, exceedance_factor: float = 1.25) -> tuple:
    """Genuine emission event where facility actually exceeds regulatory threshold."""
    result = readings.copy()
    labels = np.zeros(len(readings), dtype=int)
    end = min(start + duration, len(readings))
    true_emission = exceedance_factor * threshold
    result[start:end] = true_emission + np.random.normal(0, 0.02 * true_emission, end - start)
    labels[start:end] = 1
    return result, labels


# ─── Multi-Sensor Consensus Algorithm ─────────────────────────────────────────

def compute_consensus(readings_matrix: np.ndarray, tau: float = TAU) -> tuple:
    """
    Multi-sensor consensus using Median Absolute Deviation (MAD).
    
    Parameters
    ----------
    readings_matrix : shape (n_sensors, n_samples)
    tau : detection threshold in sigma units
    
    Returns
    -------
    consensus : shape (n_samples,)
    anomaly_flags : shape (n_sensors, n_samples), bool
    """
    n_sensors, n_samples = readings_matrix.shape
    consensus = np.zeros(n_samples)
    anomaly_flags = np.zeros((n_sensors, n_samples), dtype=bool)

    for t in range(n_samples):
        vals = readings_matrix[:, t]
        med = np.median(vals)
        mad = np.median(np.abs(vals - med))
        robust_std = 1.4826 * mad
        sigma_min = 0.5  # minimum floor to avoid division by zero

        for j in range(n_sensors):
            deviation = abs(vals[j] - med)
            if deviation > tau * max(robust_std, sigma_min):
                anomaly_flags[j, t] = True

        clean_mask = ~anomaly_flags[:, t]
        if clean_mask.sum() >= 1:
            # Trimmed mean of clean sensors
            clean_vals = vals[clean_mask]
            consensus[t] = np.mean(clean_vals)
        else:
            # Consensus failure: use median as fallback but flag
            consensus[t] = med

    return consensus, anomaly_flags


# ─── Anomaly Type Classification ──────────────────────────────────────────────

def extract_features(consensus: np.ndarray, anomaly_flags: np.ndarray,
                     threshold: float, window: int = 30) -> pd.DataFrame:
    """Extract ML features from consensus time series for anomaly classification."""
    n = len(consensus)
    features = []

    for t in range(window, n):
        window_data = consensus[t - window:t]
        current = consensus[t]
        n_flagged = anomaly_flags[:, t].sum()

        feat = {
            "mean_window":      np.mean(window_data),
            "std_window":       np.std(window_data),
            "trend":            np.polyfit(np.arange(window), window_data, 1)[0],
            "current_val":      current,
            "pct_threshold":    (current / threshold) * 100,
            "deviation_from_mean": abs(current - np.mean(window_data)),
            "n_sensors_flagged": n_flagged,
            "min_window":       np.min(window_data),
            "max_window":       np.max(window_data),
            "range_window":     np.max(window_data) - np.min(window_data),
            "near_zero":        int(current < 0.05 * threshold),
            "is_exceedance":    int(current > threshold),
        }
        features.append(feat)

    return pd.DataFrame(features)


# ─── Main Simulation ──────────────────────────────────────────────────────────

def run_simulation():
    print("=" * 65)
    print("  BChain-EmGuard Simulation Framework  (seed=42)")
    print("=" * 65)

    all_results = []
    all_labels  = []
    all_types   = []

    for gas in GAS_TYPES:
        threshold   = THRESHOLDS[gas]
        print(f"\n[Gas: {gas}] Threshold={threshold} | Simulating {N_SENSORS} sensors...")

        # Generate baseline for all sensors
        baseline = generate_emission_profile(gas, N_SAMPLES)
        sensor_readings = np.array([
            add_sensor_noise(baseline, j) for j in range(N_SENSORS)
        ])  # shape: (N_SENSORS, N_SAMPLES)

        true_labels = np.zeros(N_SAMPLES, dtype=int)

        # ── Inject anomalies on sensor 0 ──────────────────────────────────────
        n_each = {
            "DRIFT":              ANOMALY_COUNTS["DRIFT"] // len(GAS_TYPES),
            "SPIKE":              ANOMALY_COUNTS["SPIKE"] // len(GAS_TYPES),
            "TAMPER":             ANOMALY_COUNTS["TAMPER"] // len(GAS_TYPES),
            "FAILURE":            ANOMALY_COUNTS["FAILURE"] // len(GAS_TYPES),
            "GENUINE_EXCEEDANCE": ANOMALY_COUNTS["GENUINE_EXCEEDANCE"] // len(GAS_TYPES),
        }

        anomaly_type_labels = ["NORMAL"] * N_SAMPLES

        for _ in range(n_each["DRIFT"]):
            start    = np.random.randint(0, N_SAMPLES - 480)
            duration = np.random.randint(240, 480)
            sensor_readings[0], lbl = inject_drift(
                sensor_readings[0], start, duration,
                direction=np.random.uniform(-0.5, -0.2)
            )
            true_labels = np.logical_or(true_labels, lbl).astype(int)
            for t in np.where(lbl)[0]:
                anomaly_type_labels[t] = "DRIFT"

        spike_positions = np.random.randint(0, N_SAMPLES, n_each["SPIKE"])
        sensor_readings[0], lbl = inject_spike(sensor_readings[0], spike_positions)
        true_labels = np.logical_or(true_labels, lbl).astype(int)
        for t in np.where(lbl)[0]:
            anomaly_type_labels[t] = "SPIKE"

        for _ in range(n_each["TAMPER"]):
            start    = np.random.randint(0, N_SAMPLES - 120)
            duration = np.random.randint(30, 120)
            sensor_readings[0], lbl = inject_tamper(
                sensor_readings[0], start, duration,
                reduction=np.random.uniform(0.05, 0.20)
            )
            true_labels = np.logical_or(true_labels, lbl).astype(int)
            for t in np.where(lbl)[0]:
                anomaly_type_labels[t] = "TAMPER"

        for _ in range(n_each["FAILURE"]):
            start    = np.random.randint(0, N_SAMPLES - 60)
            duration = np.random.randint(10, 60)
            sensor_readings[0], lbl = inject_failure(sensor_readings[0], start, duration)
            true_labels = np.logical_or(true_labels, lbl).astype(int)
            for t in np.where(lbl)[0]:
                anomaly_type_labels[t] = "FAILURE"

        for _ in range(n_each["GENUINE_EXCEEDANCE"]):
            start    = np.random.randint(0, N_SAMPLES - 60)
            duration = np.random.randint(15, 60)
            factor   = np.random.uniform(1.10, 2.00)
            for s in range(N_SENSORS):  # all sensors see genuine exceedance
                sensor_readings[s], lbl = inject_genuine_exceedance(
                    sensor_readings[s], start, duration, threshold, factor
                )
            true_labels = np.logical_or(true_labels, lbl).astype(int)
            for t in np.where(lbl)[0]:
                anomaly_type_labels[t] = "GENUINE_EXCEEDANCE"

        # ── Run Consensus ──────────────────────────────────────────────────────
        consensus, anomaly_flags = compute_consensus(sensor_readings)

        # Consensus-based detection: any anomaly flag = detected
        consensus_detected = anomaly_flags.any(axis=0).astype(int)
        # Also detect genuine exceedances via threshold crossing
        consensus_detected = np.logical_or(
            consensus_detected, consensus > threshold
        ).astype(int)

        all_results.extend(consensus_detected.tolist())
        all_labels.extend(true_labels.tolist())
        all_types.extend(anomaly_type_labels)

    # ─── Overall Performance Metrics ──────────────────────────────────────────
    from sklearn.metrics import precision_score, recall_score

    y_true = np.array(all_labels)
    y_pred = np.array(all_results)

    print("\n" + "=" * 65)
    print("  DETECTION PERFORMANCE RESULTS")
    print("=" * 65)
    print(classification_report(y_true, y_pred,
                                target_names=["Normal", "Anomaly"],
                                digits=3))

    # By anomaly type
    type_arr = np.array(all_types)
    print(f"{'Anomaly Type':<22} {'n':>6} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 60)
    for atype in ["DRIFT", "SPIKE", "TAMPER", "FAILURE", "GENUINE_EXCEEDANCE"]:
        mask = type_arr == atype
        if mask.sum() == 0:
            continue
        p = precision_score(y_true[mask], y_pred[mask], zero_division=0)
        r = recall_score(y_true[mask], y_pred[mask], zero_division=0)
        f = 2 * p * r / (p + r + 1e-9)
        print(f"{atype:<22} {mask.sum():>6} {p:>10.3f} {r:>8.3f} {f:>8.3f}")

    # False positive rate
    normal_mask = y_true == 0
    fpr = (y_pred[normal_mask] == 1).mean()
    print(f"\nFalse Positive Rate (normal samples): {fpr:.4f} ({fpr*100:.2f}%)")
    print(f"Overall F1 Score: {f1_score(y_true, y_pred):.4f}")

    return y_true, y_pred, type_arr


# ─── Gas Cost Simulation ───────────────────────────────────────────────────────

def simulate_gas_costs(n_runs: int = 50):
    """Simulate Hardhat gas measurements (realistic ranges from BCRRS baseline)."""
    print("\n" + "=" * 65)
    print("  SMART CONTRACT GAS COST SIMULATION (n=50 runs)")
    print("=" * 65)

    operations = {
        "registerFacility()":           (185000, 190000),
        "registerSensor()":             (210000, 216000),
        "recordCalibration()":          (47000,  50000),
        "recordReading()":              (239000, 244000),
        "recordAnomalyWithCCTV()":      (196000, 201000),
        "AlertRegistry.recordAlert()":  (222000, 227000),
        "acknowledgeAlert()":           (33000,  36000),
        "recordComplianceStatus()":     (160000, 165000),
        "getHistory() [view]":          (0, 0),
    }

    ETH_PRICE = 3000
    GWEI      = 1e-9

    print(f"\n{'Function':<36} {'Min':>9} {'Max':>9} {'Median':>9} {'Cost (USD)':>12}")
    print("-" * 80)
    for func, (lo, hi) in operations.items():
        if lo == 0:
            print(f"{func:<36} {'0':>9} {'0':>9} {'0':>9} {'$0.00':>12}")
            continue
        samples = np.random.randint(lo, hi + 1, n_runs)
        median  = int(np.median(samples))
        cost    = median * GWEI * ETH_PRICE
        print(f"{func:<36} {lo:>9,} {hi:>9,} {median:>9,} {'${:.2f}'.format(cost):>12}")

    daily_readings  = 1440 * N_FACILITIES  # 1/min per facility
    daily_cost      = daily_readings * 241500 * GWEI * ETH_PRICE
    annual_cost     = daily_cost * 365
    print(f"\nEstimated annual on-chain cost ({N_FACILITIES} facilities): "
          f"${annual_cost:,.0f}")
    print(f"Per-facility per-year: ${annual_cost/N_FACILITIES:,.0f}")


# ─── Notification Latency Simulation ──────────────────────────────────────────

def simulate_notification_latency(n_events: int = 200):
    """Simulate end-to-end notification latency for anomaly events."""
    print("\n" + "=" * 65)
    print("  NOTIFICATION LATENCY SIMULATION (n=200 events)")
    print("=" * 65)

    stages = {
        "Sensor to consensus (s)":    (1.5, 4.5),
        "Consensus to ML class. (s)": (0.8, 2.8),
        "ML to CCTV activation (s)":  (0.5, 1.5),
        "CCTV clip capture (s)":      (29.5, 31.5),
        "pHash computation (s)":      (0.2, 0.6),
        "Blockchain write (s)":       (2.0, 8.5),
        "LLM alert generation (s)":   (3.0, 9.5),
        "Notification dispatch (s)":  (0.7, 2.4),
    }

    total_excl_cctv = []
    total_incl_cctv = []

    print(f"\n{'Stage':<36} {'Mean':>8} {'P95':>8}")
    print("-" * 55)
    for stage, (lo, hi) in stages.items():
        samples = np.random.uniform(lo, hi, n_events)
        mean_v  = np.mean(samples)
        p95_v   = np.percentile(samples, 95)
        print(f"{stage:<36} {mean_v:>8.1f} {p95_v:>8.1f}")

        if "CCTV" not in stage:
            total_excl_cctv.append(samples)
        total_incl_cctv.append(samples)

    excl = np.sum(total_excl_cctv, axis=0)
    incl = np.sum(total_incl_cctv, axis=0)
    print(f"\n{'Total excl. CCTV clip':<36} {np.mean(excl):>8.1f} {np.percentile(excl,95):>8.1f}")
    print(f"{'Total incl. CCTV clip':<36} {np.mean(incl):>8.1f} {np.percentile(incl,95):>8.1f}")
    print(f"\nP95 total latency (incl. CCTV): {np.percentile(incl, 95):.1f}s "
          f"(<60s threshold: {'PASS' if np.percentile(incl, 95) < 60 else 'FAIL'})")


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    y_true, y_pred, type_arr = run_simulation()
    simulate_gas_costs(n_runs=50)
    simulate_notification_latency(n_events=200)
    print("\n[Done] All results reproducible with seed=42")
