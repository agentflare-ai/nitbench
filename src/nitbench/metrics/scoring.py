import json
import math
from typing import Any, Dict, List, Optional
from pathlib import Path

def calculate_metrics(
    scoring_data: Dict[str, Any],
    checkpoints_data: Dict[str, Any],
    oracle_results: Dict[str, Dict[str, Any]] # checkpoint_id -> {oracle_id -> OracleResult}
) -> Dict[str, Any]:
    """
    Computes NitBench metrics (mass, SRAS, DR, RR, IVS, OS, PIR) from oracle results.
    """
    # 1. Gather Weights
    severity_weights = scoring_data.get("severity_weights", {"error": 1.0, "warning": 0.5, "info": 0.1})
    category_weights = scoring_data.get("category_weights", {"format": 1.0, "lint": 1.0, "naming": 1.0})
    oracle_weights = scoring_data.get("oracle_weights", {})
    violation_budget = scoring_data.get("normalization", {}).get("violation_budget", 10.0)
    
    # Pre-compute oracle definitions index
    oracles_idx = {o["id"]: o for o in scoring_data.get("oracles", [])}
    
    # 2. Compute Mass per Checkpoint
    checkpoint_masses = {}
    baseline_mass = 0.0
    
    for cp in checkpoints_data.get("checkpoints", []):
        cp_id = cp["id"]
        if cp_id not in oracle_results:
            continue
            
        total_mass = 0.0
        for oracle_id, res in oracle_results[cp_id].items():
            odef = oracles_idx.get(oracle_id, {})
            # SRAS only includes soft_rule=true
            if not odef.get("soft_rule", True):
                continue
                
            w_S_err = severity_weights.get("error", 1.0) * res.get("error_count", 0)
            w_S_warn = severity_weights.get("warning", 0.5) * res.get("warning_count", 0)
            w_S_info = severity_weights.get("info", 0.1) * res.get("info_count", 0)
            
            cat = odef.get("category", "lint")
            w_C = category_weights.get(cat, 1.0)
            w_O = oracle_weights.get(oracle_id, 1.0)
            
            total_mass += (w_S_err + w_S_warn + w_S_info) * w_C * w_O
            
        checkpoint_masses[cp_id] = total_mass
        if cp.get("phase") == "baseline":
            baseline_mass = total_mass # Naive MVP assumption: only one baseline
            
    # 3. Compute SRAS per Checkpoint
    cp_metrics = []
    
    # For run-level totals
    total_new_mass = 0.0
    total_drift_mass = 0.0
    total_rec_mass = 0.0
    
    # Tracks for IVS
    proxy_values = []
    sras_values = []
    
    # Tracks for OS / PIR
    baseline_sras = []
    injection_sras_sum = 0.0
    injection_sras_count = 0
    
    for idx, cp in enumerate(checkpoints_data.get("checkpoints", [])):
        cp_id = cp["id"]
        if cp_id not in checkpoint_masses:
            continue
            
        c_mass = checkpoint_masses[cp_id]
        
        # new_mass_c = max(0, mass_c - baseline)
        new_mass = max(0.0, c_mass - baseline_mass)
        
        # SRAS_c = max(0, 1 - (new_mass / budget))
        sras_c = max(0.0, 1.0 - (new_mass / violation_budget))
        
        proxy_val = cp.get("trigger", {}).get("value", idx) # Fallback to index if end_of_run
        
        cp_metrics.append({
            "checkpoint_id": cp_id,
            "proxy_value": proxy_val,
            "mass": c_mass,
            "new_mass": new_mass,
            "sras": sras_c,
            "oracles": [
                {"oracle_id": oid, **res} 
                for oid, res in oracle_results.get(cp_id, {}).items()
            ]
        })
        
        if cp.get("phase") != "baseline":
            total_new_mass += new_mass
            
            # Drift is mass that increases
            if len(cp_metrics) > 1:
                prev_new_mass = cp_metrics[-2]["new_mass"]
                delta = new_mass - prev_new_mass
                if delta > 0:
                    total_drift_mass += delta
                elif delta < 0:
                    total_rec_mass += abs(delta)
                    
            proxy_values.append(proxy_val)
            sras_values.append(sras_c)
            
        if cp.get("phase") == "baseline":
            baseline_sras.append(sras_c)
        elif cp.get("phase") == "injection":
            injection_sras_sum += sras_c
            injection_sras_count += 1
            
    # 4. Run-level Metrics
    # SRAS
    work_sras_values = [c["sras"] for cp, c in zip(checkpoints_data.get("checkpoints", []), cp_metrics) if cp.get("phase") != "baseline"]
    sras_run = sum(work_sras_values) / len(work_sras_values) if work_sras_values else 1.0
    
    # DR / RR
    # Progress total is max proxy difference
    prog_total = proxy_values[-1] - proxy_values[0] if len(proxy_values) > 1 else 1.0
    prog_total = max(1.0, prog_total)
    
    dr_run = min(1.0, total_drift_mass / prog_total)
    rr_run = min(1.0, total_rec_mass / total_drift_mass) if total_drift_mass > 0 else 1.0
    
    # IVS (Slope)
    ivs_run = 1.0
    if len(proxy_values) > 1:
        n = len(proxy_values)
        mean_x = sum(proxy_values) / n
        mean_y = sum(sras_values) / n
        
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(proxy_values, sras_values))
        den = sum((x - mean_x) ** 2 for x in proxy_values)
        
        if den > 0:
            m = num / den
            m_clamped = max(-1.0, min(1.0, m))
            ivs_run = (m_clamped + 1.0) / 2.0
            
    # OS / PIR
    os_run = None
    pir_run = None
    if injection_sras_count > 0:
        base_sras_mean = sum(baseline_sras) / len(baseline_sras) if baseline_sras else 1.0
        inj_sras_mean = injection_sras_sum / injection_sras_count
        
        os_run = max(0.0, base_sras_mean - inj_sras_mean)
        pir_run = 1.0 - os_run
        
    metrics = {
        "SRAS": float(sras_run),
        "DR": float(dr_run),
        "RR": float(rr_run),
        "IVS": float(ivs_run),
        "OS": float(os_run) if os_run is not None else None,
        "PIR": float(pir_run) if pir_run is not None else None
    }
    
    return {"metrics": metrics, "checkpoints": cp_metrics}
