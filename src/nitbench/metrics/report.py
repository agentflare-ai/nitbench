from typing import Any, Dict, List, Tuple
from collections import defaultdict
from nitbench.validation.validator import SchemaValidator

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
    
    schema_val = SchemaValidator()
    schema_val.validate(report, "Report")
    
    return report

def _compute_sensitivity(results: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    # Spec 17.7: RS and MS MUST be computed for fixed attributes.
    groups = defaultdict(list)
    
    for r in results:
        if r.get("interaction_mode") != "pty" or r.get("aut_mode") != "manual":
            continue
            
        if mode == "reasoning":
            # Fixed: agent_family, model_id, interaction_mode, aut_mode
            key = (r.get("agent_family"), r.get("model_id"))
        elif mode == "model":
            # Fixed: agent_family, reasoning_level, interaction_mode, aut_mode
            # Serialize reasoning_level to handle both string and int safely
            key = (r.get("agent_family"), str(r.get("reasoning_level")))
        else:
            continue
            
        groups[key].append(r)
        
    sensitivities = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
            
        sras_vals = [r["suite_metrics"]["SRAS_suite"] for r in group if r["suite_metrics"]["SRAS_suite"] is not None]
        dr_vals = [r["suite_metrics"]["DR_suite"] for r in group if r["suite_metrics"]["DR_suite"] is not None]
        rr_vals = [r["suite_metrics"]["RR_suite"] for r in group if r["suite_metrics"]["RR_suite"] is not None]
        os_vals = [r["suite_metrics"]["OS_suite"] for r in group if r["suite_metrics"].get("OS_suite") is not None]
        
        sens = {
            "key": f"{key[0]}/{key[1]}",
            "SRAS": max(sras_vals) - min(sras_vals) if sras_vals else None,
            "DR": max(dr_vals) - min(dr_vals) if dr_vals else None,
            "RR": max(rr_vals) - min(rr_vals) if rr_vals else None,
            "OS": max(os_vals) - min(os_vals) if os_vals else None
        }
        sensitivities.append(sens)
        
    if not sensitivities:
        return None
        
    return sensitivities
