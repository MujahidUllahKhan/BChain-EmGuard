"""
BChain-EmGuard: LLM Notification Simulation
=============================================
Simulates the LLM alert generation pipeline without requiring
a live API key. Generates template-based alerts that mirror
the LLM prompt/response structure, and evaluates latency,
hash anchoring, and escalation logic.

For actual LLM integration, set USE_REAL_LLM=True and provide
your API key in environment variable ANTHROPIC_API_KEY or OPENAI_API_KEY.

Usage:
    python llm_notification_sim.py
"""

import hashlib
import json
import time
import random
import numpy as np
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

USE_REAL_LLM = False   # Set True + set API key for real LLM calls

# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class AnomalyContext:
    facility_id: str
    facility_name: str
    facility_address: str
    gas_type: str
    consensus_value: float
    threshold: float
    unit: str
    anomaly_type: str          # DRIFT | SPIKE | TAMPER | FAILURE | GENUINE_EXCEEDANCE
    n_sensors_flagged: int
    n_sensors_total: int
    cctv_activated: bool
    cctv_hash: Optional[str]
    history_summary: str       # Last 24h compliance summary
    regulation_code: str
    officer_id: str
    officer_name: str
    officer_phone: str
    timestamp: str

@dataclass
class GeneratedAlert:
    alert_id: str
    anomaly_context: AnomalyContext
    alert_text: str
    severity: str
    alert_hash: str            # keccak256-equivalent (SHA3-256 used here)
    generation_latency_s: float
    dispatch_time: str
    acknowledged: bool
    ack_time: Optional[str]
    escalated: bool

# ─── Severity Classification ──────────────────────────────────────────────────

def classify_severity(consensus: float, threshold: float, anomaly_type: str) -> str:
    exceedance_pct = ((consensus - threshold) / threshold) * 100
    if anomaly_type == "TAMPER":
        return "CRITICAL"
    if anomaly_type == "FAILURE":
        return "HIGH"
    if exceedance_pct <= 0:
        return "LOW" if anomaly_type in ("DRIFT", "SPIKE") else "MEDIUM"
    if exceedance_pct <= 10:
        return "LOW"
    if exceedance_pct <= 30:
        return "MEDIUM"
    if exceedance_pct <= 100:
        return "HIGH"
    return "CRITICAL"

# ─── Template-Based Alert Generator (no API needed) ──────────────────────────

TEMPLATES = {
    "LOW": (
        "EMISSION NOTICE — Facility: {facility_name} (ID: {facility_id}), "
        "{facility_address}. {timestamp} UTC. {gas_type} measured at "
        "{consensus_value:.2f} {unit} (regulatory limit: {threshold:.2f} {unit}) "
        "— minor anomaly detected ({anomaly_type}). {n_sensors_flagged} of "
        "{n_sensors_total} sensors flagged. CCTV status: {cctv_status}. "
        "24h history: {history_summary}. RECOMMENDED ACTION: Monitor remotely. "
        "If reading persists above limit for >30 minutes, proceed to facility. "
        "Applicable regulation: {regulation_code}."
    ),
    "MEDIUM": (
        "EMISSION ALERT — Facility: {facility_name} (ID: {facility_id}), "
        "{facility_address}. {timestamp} UTC. {gas_type} at {consensus_value:.2f} "
        "{unit} — {exceedance_pct:.1f}% above regulatory limit ({threshold:.2f} {unit}). "
        "MEDIUM severity. Anomaly type: {anomaly_type}. {n_sensors_flagged} of "
        "{n_sensors_total} sensors flagged. CCTV: {cctv_status}. "
        "24h history: {history_summary}. RECOMMENDED ACTION: Contact facility "
        "shift manager and proceed to site within 4 hours. Document reading. "
        "Regulation: {regulation_code}."
    ),
    "HIGH": (
        "HIGH-PRIORITY EMISSION ALERT — Facility: {facility_name} (ID: {facility_id}), "
        "{facility_address}. {timestamp} UTC. URGENT: {gas_type} at "
        "{consensus_value:.2f} {unit} — {exceedance_pct:.1f}% above limit "
        "({threshold:.2f} {unit}). Anomaly: {anomaly_type}. {n_sensors_flagged}/"
        "{n_sensors_total} sensors anomalous. CCTV activated: {cctv_status}. "
        "24h history: {history_summary}. RECOMMENDED ACTION: Proceed to facility "
        "IMMEDIATELY. Issue formal notice under {regulation_code}. Preserve all "
        "sensor records as evidence. Notify district supervisor."
    ),
    "CRITICAL": (
        "*** CRITICAL EMISSION ALERT *** — Facility: {facility_name} "
        "(ID: {facility_id}), {facility_address}. {timestamp} UTC. "
        "POTENTIAL REGULATORY EVASION DETECTED. {gas_type} consensus reading: "
        "{consensus_value:.2f} {unit} (limit: {threshold:.2f} {unit}, "
        "{exceedance_pct:.1f}% exceedance). ANOMALY: {anomaly_type} — "
        "{n_sensors_flagged} of {n_sensors_total} sensors show implausible "
        "readings consistent with tampering. CCTV frame hash anchored on-chain: "
        "{cctv_hash}. 24h history: {history_summary}. RECOMMENDED ACTION: "
        "Proceed to facility IMMEDIATELY. DO NOT notify facility management in "
        "advance. Initiate formal inspection under {regulation_code} Section 16. "
        "Contact district enforcement officer. This alert is on-chain — "
        "evidence preserved for enforcement proceedings."
    )
}

def generate_alert_template(ctx: AnomalyContext, severity: str) -> str:
    """Generate alert text using severity-specific template."""
    exceedance_pct = max(0.0, ((ctx.consensus_value - ctx.threshold) / ctx.threshold) * 100)
    cctv_status = f"Activated — hash {ctx.cctv_hash[:16]}..." if ctx.cctv_activated else "Not activated"
    
    template = TEMPLATES.get(severity, TEMPLATES["MEDIUM"])
    return template.format(
        facility_id=ctx.facility_id,
        facility_name=ctx.facility_name,
        facility_address=ctx.facility_address,
        timestamp=ctx.timestamp,
        gas_type=ctx.gas_type,
        consensus_value=ctx.consensus_value,
        threshold=ctx.threshold,
        unit=ctx.unit,
        anomaly_type=ctx.anomaly_type,
        n_sensors_flagged=ctx.n_sensors_flagged,
        n_sensors_total=ctx.n_sensors_total,
        cctv_status=cctv_status,
        cctv_hash=ctx.cctv_hash or "N/A",
        history_summary=ctx.history_summary,
        regulation_code=ctx.regulation_code,
        exceedance_pct=exceedance_pct,
    )


def generate_alert_real_llm(ctx: AnomalyContext, severity: str) -> str:
    """
    Real LLM alert generation via Anthropic API.
    Only called if USE_REAL_LLM=True.
    """
    try:
        import anthropic
        client = anthropic.Anthropic()
        exceedance_pct = max(0.0, ((ctx.consensus_value - ctx.threshold) / ctx.threshold) * 100)
        
        prompt = f"""You are an environmental compliance notification system.
Generate a regulatory alert for a regulatory officer.
Be concise (under 200 words), legally precise, and include a clear recommended action.

FACILITY: {ctx.facility_name} (ID: {ctx.facility_id})
LOCATION: {ctx.facility_address}
TIMESTAMP: {ctx.timestamp} UTC
GAS TYPE: {ctx.gas_type}
MEASURED VALUE: {ctx.consensus_value:.2f} {ctx.unit}
REGULATORY THRESHOLD: {ctx.threshold:.2f} {ctx.unit}
EXCEEDANCE: {exceedance_pct:.1f}% above limit
SEVERITY: {severity}
ANOMALY TYPE: {ctx.anomaly_type}
SENSORS FLAGGED: {ctx.n_sensors_flagged} of {ctx.n_sensors_total}
CCTV ACTIVATED: {ctx.cctv_activated}
CCTV HASH: {ctx.cctv_hash}
24H COMPLIANCE HISTORY: {ctx.history_summary}

Generate: (1) Alert summary, (2) Probable cause assessment,
(3) Recommended immediate action, (4) Legal reference to {ctx.regulation_code}.
Plain text only. No disclaimers."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        print(f"  [LLM API error: {e}] — falling back to template")
        return generate_alert_template(ctx, severity)


# ─── Hash Function (SHA3-256 as keccak256 proxy) ──────────────────────────────

def hash_alert(text: str) -> str:
    """SHA3-256 of alert text — proxy for keccak256 in non-Ethereum context."""
    return "0x" + hashlib.sha3_256(text.encode()).hexdigest()


def simulate_phash(facility_id: str, timestamp: str) -> str:
    """Simulate a perceptual hash value for CCTV frame."""
    raw = f"{facility_id}{timestamp}{random.random()}"
    return "0x" + hashlib.sha256(raw.encode()).hexdigest()[:16]


# ─── Scenario Generator ───────────────────────────────────────────────────────

FACILITIES = [
    {"id": "PK-TEX-014", "name": "Karachi Textile Mill 14",
     "address": "SITE III, Karachi Industrial Zone, Sindh, Pakistan",
     "regulation": "PEPA Schedule III, Table 2"},
    {"id": "PK-CEM-007", "name": "Punjab Cement Works 7",
     "address": "Lahore Industrial Estate, Punjab, Pakistan",
     "regulation": "PEPA Schedule III, Table 4"},
    {"id": "BD-GAR-021", "name": "Dhaka Garment Factory 21",
     "address": "Ashulia Industrial Zone, Dhaka, Bangladesh",
     "regulation": "BEPZA Environment Rules 2023, Section 12"},
    {"id": "AE-STL-003", "name": "Dubai Steel Processing 3",
     "address": "Jebel Ali Industrial Area, Dubai, UAE",
     "regulation": "UAE Federal Law No. 24/1999, Article 18"},
]

GAS_CONFIG = {
    "CO2":  {"threshold": 400.0,  "unit": "ppm",    "base": 310.0},
    "CH4":  {"threshold": 1.9,    "unit": "ppm",    "base": 1.3},
    "NOx":  {"threshold": 0.1,    "unit": "ppm",    "base": 0.065},
    "PM25": {"threshold": 35.0,   "unit": "ug/m3",  "base": 22.0},
}

OFFICERS = [
    {"id": "OFF-001", "name": "Officer Ahmed Raza",    "phone": "+92-300-1234567"},
    {"id": "OFF-002", "name": "Officer Fatima Khan",   "phone": "+92-321-7654321"},
    {"id": "OFF-003", "name": "Officer Rahel Hossain", "phone": "+880-17-12345678"},
    {"id": "OFF-004", "name": "Officer Sara Al-Mansi", "phone": "+971-50-9876543"},
]

ANOMALY_SCENARIOS = [
    # (anomaly_type, gas, consensus_multiplier, n_flagged, cctv_activated)
    ("GENUINE_EXCEEDANCE", "CO2",  1.22, 0, True),
    ("DRIFT",              "CH4",  0.85, 1, False),
    ("SPIKE",              "NOx",  2.10, 1, True),
    ("TAMPER",             "CO2",  0.08, 2, True),
    ("FAILURE",            "PM25", 0.00, 1, True),
    ("GENUINE_EXCEEDANCE", "NOx",  3.50, 0, True),
    ("DRIFT",              "PM25", 1.05, 1, False),
    ("TAMPER",             "CH4",  0.05, 3, True),
]

HISTORY_TEMPLATES = [
    "No violations in past 24h. 3 minor drift events auto-resolved.",
    "1 MEDIUM alert 8h ago acknowledged by officer. Facility compliant.",
    "Clean record. Last inspection: 14 days ago — all parameters within limits.",
    "2 prior SPIKE events in last 6h. Pattern may indicate equipment degradation.",
    "CRITICAL event 3h ago unacknowledged — currently escalated to district supervisor.",
]


def generate_scenarios(n: int = 20) -> list:
    scenarios = []
    for i in range(n):
        fac     = FACILITIES[i % len(FACILITIES)]
        officer = OFFICERS[i % len(OFFICERS)]
        atype, gas, mult, n_flagged, cctv = ANOMALY_SCENARIOS[i % len(ANOMALY_SCENARIOS)]
        cfg     = GAS_CONFIG[gas]
        
        consensus = cfg["base"] * mult if mult < 1 else cfg["threshold"] * mult
        ts        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cctv_hash = simulate_phash(fac["id"], ts) if cctv else None

        ctx = AnomalyContext(
            facility_id=fac["id"],
            facility_name=fac["name"],
            facility_address=fac["address"],
            gas_type=gas,
            consensus_value=round(consensus, 3),
            threshold=cfg["threshold"],
            unit=cfg["unit"],
            anomaly_type=atype,
            n_sensors_flagged=n_flagged,
            n_sensors_total=3,
            cctv_activated=cctv,
            cctv_hash=cctv_hash,
            history_summary=HISTORY_TEMPLATES[i % len(HISTORY_TEMPLATES)],
            regulation_code=fac["regulation"],
            officer_id=officer["id"],
            officer_name=officer["name"],
            officer_phone=officer["phone"],
            timestamp=ts,
        )
        scenarios.append(ctx)
    return scenarios


# ─── Escalation Logic ─────────────────────────────────────────────────────────

ACK_TIMEOUT_SECONDS = 1800  # 30 minutes

def simulate_acknowledgment(alert: GeneratedAlert) -> GeneratedAlert:
    """Simulate officer acknowledgment or escalation."""
    # Simulate: CRITICAL alerts have 40% chance of non-acknowledgment (officer busy)
    ack_prob = {"LOW": 0.95, "MEDIUM": 0.85, "HIGH": 0.75, "CRITICAL": 0.60}
    prob = ack_prob.get(alert.severity, 0.80)
    
    if random.random() < prob:
        ack_delay = random.uniform(120, ACK_TIMEOUT_SECONDS - 60)
        alert.acknowledged = True
        alert.ack_time = f"+{ack_delay/60:.1f} min"
    else:
        alert.escalated = True
        alert.ack_time = None
    return alert


# ─── Main Evaluation ──────────────────────────────────────────────────────────

def run_notification_simulation(n_scenarios: int = 20):
    print("=" * 70)
    print("  BChain-EmGuard: LLM Notification Simulation  (seed=42)")
    print("=" * 70)

    scenarios = generate_scenarios(n_scenarios)
    alerts    = []

    print(f"\nGenerating {n_scenarios} alerts {'(REAL LLM)' if USE_REAL_LLM else '(TEMPLATE MODE)'}...\n")

    for i, ctx in enumerate(scenarios):
        severity = classify_severity(ctx.consensus_value, ctx.threshold, ctx.anomaly_type)

        t0 = time.time()
        if USE_REAL_LLM:
            alert_text = generate_alert_real_llm(ctx, severity)
        else:
            alert_text = generate_alert_template(ctx, severity)
        latency = time.time() - t0

        alert_hash = hash_alert(alert_text)
        alert_id   = f"ALT-{i+1:04d}-{ctx.facility_id}"

        alert = GeneratedAlert(
            alert_id=alert_id,
            anomaly_context=ctx,
            alert_text=alert_text,
            severity=severity,
            alert_hash=alert_hash,
            generation_latency_s=round(latency, 3),
            dispatch_time=datetime.now(timezone.utc).isoformat(),
            acknowledged=False,
            ack_time=None,
            escalated=False,
        )
        alert = simulate_acknowledgment(alert)
        alerts.append(alert)

    # ─── Print Sample Alerts ──────────────────────────────────────────────────
    print("─" * 70)
    print("SAMPLE GENERATED ALERTS (first 3):")
    print("─" * 70)
    for a in alerts[:3]:
        print(f"\n[{a.alert_id}] SEVERITY: {a.severity}")
        print(f"HASH: {a.alert_hash}")
        print(f"ACKNOWLEDGED: {a.acknowledged} | ACK_TIME: {a.ack_time} | ESCALATED: {a.escalated}")
        print(f"\nALERT TEXT:\n{a.alert_text}")
        print("─" * 70)

    # ─── Summary Statistics ───────────────────────────────────────────────────
    severity_counts  = {}
    ack_counts       = {"acknowledged": 0, "escalated": 0}
    for a in alerts:
        severity_counts[a.severity] = severity_counts.get(a.severity, 0) + 1
        if a.acknowledged:
            ack_counts["acknowledged"] += 1
        if a.escalated:
            ack_counts["escalated"] += 1

    print("\nALERT SEVERITY DISTRIBUTION:")
    for sev, count in sorted(severity_counts.items()):
        print(f"  {sev:<12}: {count:>3} ({count/n_scenarios*100:.1f}%)")

    print(f"\nACKNOWLEDGMENT RATE: {ack_counts['acknowledged']}/{n_scenarios} "
          f"({ack_counts['acknowledged']/n_scenarios*100:.1f}%)")
    print(f"ESCALATION RATE:     {ack_counts['escalated']}/{n_scenarios} "
          f"({ack_counts['escalated']/n_scenarios*100:.1f}%)")

    # ─── On-Chain Record Simulation ───────────────────────────────────────────
    print("\nSIMULATED ON-CHAIN RECORDS (AlertRegistry.sol):")
    print(f"{'Alert ID':<25} {'Severity':<10} {'Hash (first 20 chars)':<22} {'Ack'}")
    print("─" * 70)
    for a in alerts[:10]:
        print(f"{a.alert_id:<25} {a.severity:<10} {a.alert_hash[:22]:<22} "
              f"{'YES' if a.acknowledged else 'ESCALATED'}")

    # ─── Export to JSON ───────────────────────────────────────────────────────
    export_data = []
    for a in alerts:
        d = asdict(a)
        export_data.append(d)

    with open("alert_records.json", "w") as f:
        json.dump(export_data, f, indent=2)
    print(f"\n[Exported] {n_scenarios} alert records → alert_records.json")
    print("  (These represent the off-chain payload; hash is the on-chain record)")


if __name__ == "__main__":
    run_notification_simulation(n_scenarios=20)
