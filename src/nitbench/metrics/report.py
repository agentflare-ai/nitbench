from typing import Any, Dict, List, Tuple
from collections import defaultdict

def generate_report(
    suite_id: str,
    case_weights: Dict[str, float],
    runs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Aggregates run.json outputs into a suite-level report.json.
    """
    
    # Filter valid runs
    valid_runs = []
    for r in runs:
        val = r.get("validity", {})
        if val.get("case_valid") and val.get("run_valid"):
            valid_runs.append(r)
            
    # Group by profile signature
    # (agent_family, model_id, reasoning_level, interaction_mode, aut_mode)
    groups = defaultdict(list)
    for r in valid_runs:
        prof = r.get("agent_profile", {})
        sig = (
            prof.get("agent_family", "unknown"),
            prof.get("model_id", "unknown"),
            prof.get("reasoning_level", "none"),
            r.get("interaction_mode", "pty"),
            r.get("aut_mode", "manual")
        )
        groups[sig].append(r)
        
    results = []
    
    for sig, group_runs in groups.items():
        total_weight = 0.0
        sum_sras = 0.0
        sum_dr = 0.0
        sum_rr = 0.0
        sum_ivs = 0.0
        
        # OS / PIR can be null
        sum_os = 0.0
        sum_pir = 0.0
        os_weight = 0.0
        pir_weight = 0.0
        
        for r in group_runs:
            case_id = r.get("case_id")
            w = case_weights.get(case_id, 1.0)
            m = r.get("metrics", {})
            
            total_weight += w
            sum_sras += m.get("SRAS", 0.0) * w
            sum_dr += m.get("DR", 0.0) * w
            sum_rr += m.get("RR", 0.0) * w
            sum_ivs += m.get("IVS", 0.0) * w
            
            os = m.get("OS")
            if os is not None:
                sum_os += os * w
                os_weight += w
                
            pir = m.get("PIR")
            if pir is not None:
                sum_pir += pir * w
                pir_weight += w
                
        if total_weight > 0:
            suite_metrics = {
                "SRAS_suite": sum_sras / total_weight,
                "DR_suite": sum_dr / total_weight,
                "RR_suite": sum_rr / total_weight,
                "IVS_suite": sum_ivs / total_weight,
                "OS_suite": (sum_os / os_weight) if os_weight > 0 else None,
                "PIR_suite": (sum_pir / pir_weight) if pir_weight > 0 else None
            }
        else:
            suite_metrics = {
                "SRAS_suite": 0.0,
                "DR_suite": 0.0,
                "RR_suite": 0.0,
                "IVS_suite": 0.0,
                "OS_suite": None,
                "PIR_suite": None
            }
            
        results.append({
            "agent_family": sig[0],
            "model_id": sig[1],
            "reasoning_level": sig[2],
            "interaction_mode": sig[3],
            "aut_mode": sig[4],
            "suite_metrics": suite_metrics
        })
        
    # Build payload
    cases_manifest = [{"case_id": cid, "weight": float(w)} for cid, w in case_weights.items()]
    
    report = {
        "report_version": "nitbench.report.v1",
        "spec_version": "1.0.0",
        "suite_id": suite_id,
        "cases": cases_manifest,
        "results": results,
        "reasoning_sensitivity": _compute_sensitivity(results, "reasoning"),
        "model_sensitivity": _compute_sensitivity(results, "model")
    }
    return report

def _compute_sensitivity(results: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    # Simple MVP implementation: pairs varying only by the target attribute
    pairs = []
    
    for r1 in results:
        for r2 in results:
            if r1 == r2: continue
            
            match = (
                r1["agent_family"] == r2["agent_family"] and
                r1["interaction_mode"] == r2["interaction_mode"] and
                r1["aut_mode"] == r2["aut_mode"]
            )
            
            if not match: continue
            
            if mode == "reasoning":
                # Model must match, reasoning must differ
                if r1["model_id"] == r2["model_id"] and r1["reasoning_level"] != r2["reasoning_level"]:
                    key = f"{r1['agent_family']}/{r1['model_id']}:{r1['reasoning_level']}->{r2['reasoning_level']}"
                    pairs.append((key, r1, r2))
                    
            elif mode == "model":
                # Models differ, reasoning must match
                if r1["model_id"] != r2["model_id"] and r1["reasoning_level"] == r2["reasoning_level"]:
                    key = f"{r1['agent_family']}/{r1['reasoning_level']}:{r1['model_id']}->{r2['model_id']}"
                    pairs.append((key, r1, r2))
                    
    sensitivities = []
    for key, r1, r2 in pairs:
        m1 = r1["suite_metrics"]
        m2 = r2["suite_metrics"]
        
        sens = {
            "key": key,
            "SRAS": abs(m1["SRAS_suite"] - m2["SRAS_suite"]),
            "DR": abs(m1["DR_suite"] - m2["DR_suite"]),
            "RR": abs(m1["RR_suite"] - m2["RR_suite"]),
            "OS": abs(m1["OS_suite"] - m2["OS_suite"]) if m1["OS_suite"] is not None and m2["OS_suite"] is not None else None
        }
        # Deduplicate (A->B and B->A have the same absolute delta, just keep one stable representation)
        
        # Sort key to ensure uniqueness
        parts = key.split(":")
        sorted_key = f"{parts[0]}:{'<->'.join(sorted(parts[1].split('->')))}"
        sens["key"] = sorted_key
        
        if not any(s["key"] == sorted_key for s in sensitivities):
            sensitivities.append(sens)
            
    return sensitivities
