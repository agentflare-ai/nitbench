import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict

from nitbench.sandbox.checkpoint import CheckpointManager
from nitbench.sandbox.validator import RunValidator
from nitbench.metrics.scoring import calculate_metrics

def finalize_run(
    case_dir: Path,
    case_data: Dict[str, Any],
    checkpoints_data: Dict[str, Any],
    scoring_data: Dict[str, Any],
    agent_profile: Dict[str, Any],
    harness_artifacts: Path,
    validator: RunValidator,
    checkpoint_mgr: CheckpointManager,
    oracle_bundle_sha256: str,
    repo_initial_sha256: str
) -> Path:
    """
    Finalizes the NitBench case run, determining validity and writing the final output structure.
    Returns the final run_result.json path.
    """
    out_dir = harness_artifacts / "run_result"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Determine run validity
    run_validity = "case_invalid" if not validator.is_run_valid else "case_valid"
    
    # 2. Complete checkpoints.json hashes
    checkpoints_out = {
        "hashes_version": validator.hashes.get("hashes_version"),
        "spec_version": validator.hashes.get("spec_version"),
        "case_id": validator.hashes.get("case_id"),
        "agent_profile_sha256": validator.hashes.get("agent_profile_sha256"),
        "repo_initial_sha256": repo_initial_sha256,
        "checkpoints": checkpoint_mgr.hashes
    }
    
    cp_path = out_dir / "checkpoints.json"
    with open(cp_path, "w", encoding="utf-8") as f:
        json.dump(checkpoints_out, f, indent=2, sort_keys=True)
        
    # Calculate checkpoints_json_sha256
    cp_bytes = cp_path.read_bytes()
    cp_hash = hashlib.sha256(cp_bytes).hexdigest()
    
    # Calculate transcript_sha256
    ts_path = checkpoint_mgr.logger.log_path
    ts_hash = ""
    if ts_path.exists():
        ts_hash = hashlib.sha256(ts_path.read_bytes()).hexdigest()
        
    # Read Oracle Results
    oracle_results = {}
    for cp_id in checkpoint_mgr.executed_checkpoints:
        cp_oracles_dir = harness_artifacts / "checkpoints" / cp_id / "oracles"
        if not cp_oracles_dir.exists():
            continue
            
        cp_res = {}
        for oracle_dir in cp_oracles_dir.iterdir():
            if not oracle_dir.is_dir():
                continue
            res_json = oracle_dir / "result.json"
            if res_json.exists():
                with open(res_json, "r") as f:
                    cp_res[oracle_dir.name] = json.load(f)
        oracle_results[cp_id] = cp_res
        
    # Calculate Metrics
    metrics_data = calculate_metrics(scoring_data, checkpoints_data, oracle_results)
    
    # 3. Create run.json
    import time
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc).isoformat()
    
    run_json = {
        "run_version": "nitbench.run.v1",
        "spec_version": "1.0.0",
        "case_id": validator.hashes.get("case_id"),
        "agent_profile": agent_profile,
        "interaction_mode": "pty",
        "aut_mode": "manual",
        "start_time_utc": now_utc, # Simplified for MVP
        "end_time_utc": now_utc,
        "toolchain": {
            "os": "unknown",
            "arch": "unknown",
            "git_version": "unknown"
        },
        "checkpoints": metrics_data["checkpoints"],
        "metrics": metrics_data["metrics"],
        "validity": {
            "case_valid": True, # Assume true if we got this far
            "run_valid": validator.is_run_valid,
            "invalid_reasons": validator.invalid_reasons,
            "penalties": []
        }
    }
    
    run_path = out_dir / "run.json"
    with open(run_path, "w", encoding="utf-8") as f:
        json.dump(run_json, f, indent=2)
        
    # Calculate combined run_hash
    # We must deterministically hash all constituent parts.
    hash_str = f"{oracle_bundle_sha256}:{validator.hashes.get('agent_profile_sha256')}:{cp_hash}:{ts_hash}"
    run_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()
    
    # 4. Create run_result.json (Legacy, mapped structure for backward compat in MVP tests)
    run_result = {
        "run_hash": run_hash,
        "run_validity": run_validity,
        "invalid_reasons": validator.invalid_reasons,
        "oracle_bundle_sha256": oracle_bundle_sha256,
        "agent_profile_sha256": validator.hashes.get("agent_profile_sha256"),
        "repo_initial_sha256": repo_initial_sha256,
        "checkpoints_json_sha256": cp_hash,
        "transcript_sha256": ts_hash
    }
    
    result_path = out_dir / "run_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(run_result, f, indent=2, sort_keys=True)
        
    # In a full run, we would also copy scoring.yaml, debug info, etc. into `out_dir`
    if (case_dir / "scoring.yaml").exists():
        shutil.copy(case_dir / "scoring.yaml", out_dir / "scoring.yaml")
        
    if ts_path.exists():
        shutil.copy(ts_path, out_dir / "transcript.cast")
        
    return result_path
