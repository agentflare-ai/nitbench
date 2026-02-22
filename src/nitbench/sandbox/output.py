import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict

from nitbench.sandbox.checkpoint import CheckpointManager
from nitbench.sandbox.validator import RunValidator
from nitbench.metrics.scoring import calculate_metrics
from nitbench.validation.validator import SchemaValidator

def finalize_run(
    case_dir: Path,
    case_data: Dict[str, Any],
    checkpoints_data: Dict[str, Any],
    scoring_data: Dict[str, Any],
    agent_profile: Dict[str, Any],
    harness_artifacts: Path,
    artifacts_dir: Path,
    validator: RunValidator,
    checkpoint_mgr: CheckpointManager,
    oracle_bundle_sha256: str,
    repo_initial_sha256: str,
    aif_sha256: str,
    task_md_sha256: str,
    start_time_utc: str = None
) -> Path:
    """
    Finalizes the NitBench case run, determining validity and writing the final output structure.
    Returns the final run.json path.
    """
    out_dir = harness_artifacts
    
    # 1. Determine run validity
    case_invalid_reasons = [r for r in validator.invalid_reasons if r.startswith("case_invalid:")]
    run_invalid_reasons = [r for r in validator.invalid_reasons if not r.startswith("case_invalid:")]
    
    is_case_valid = len(case_invalid_reasons) == 0
    is_run_valid = len(run_invalid_reasons) == 0
    
    # 2. Complete hashes.json
    hashes_out = {
        "hashes_version": validator.hashes.get("hashes_version"),
        "spec_version": validator.hashes.get("spec_version"),
        "case_id": validator.hashes.get("case_id"),
        "agent_profile_sha256": validator.hashes.get("agent_profile_sha256"),
        "task_md_sha256": task_md_sha256,
        "aif_sha256": aif_sha256,
        "repo_initial_sha256": repo_initial_sha256,
        "oracle_bundle_sha256": oracle_bundle_sha256,
        "checkpoints": checkpoint_mgr.hashes
    }
    
    hashes_path = artifacts_dir / "hashes.json"

    # Validate hashes.json against $defs.Hashes schema
    schema_val = SchemaValidator()
    schema_val.validate(hashes_out, "Hashes")

    with open(hashes_path, "w", encoding="utf-8") as f:
        json.dump(hashes_out, f, indent=2, sort_keys=True)
        
    # Calculate transcript_sha256
    ts_path = checkpoint_mgr.logger.log_path
    ts_hash = ""
    if ts_path.exists():
        ts_hash = hashlib.sha256(ts_path.read_bytes()).hexdigest()
        
    # Read Oracle Results
    oracle_results = {}
    for cp_id in checkpoint_mgr.executed_checkpoints:
        cp_oracles_dir = artifacts_dir / "checkpoints" / cp_id / "oracles"
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
    metrics_data = calculate_metrics(scoring_data, checkpoints_data, oracle_results, checkpoint_mgr.executed_proxies)
    
    # 3. Create run.json
    from datetime import datetime, timezone
    end_time = datetime.now(timezone.utc).isoformat()
    actual_start = start_time_utc if start_time_utc else end_time
    
    import platform
    import subprocess
    try:
        git_version = subprocess.check_output(["git", "--version"], text=True).strip()
    except Exception:
        git_version = "unknown"

    run_json = {
        "run_version": "nitbench.run.v1",
        "spec_version": "1.0.0",
        "case_id": validator.hashes.get("case_id"),
        "agent_profile": agent_profile,
        "interaction_mode": agent_profile.get("interaction_mode", "pty"),
        "aut_mode": agent_profile.get("aut_mode", "manual"),
        "start_time_utc": actual_start,
        "end_time_utc": end_time,
        "toolchain": {
            "os": platform.system().lower(),
            "arch": platform.machine().lower(),
            "git_version": git_version
        },
        "checkpoints": metrics_data["checkpoints"],
        "metrics": metrics_data["metrics"],
        "validity": {
            "case_valid": is_case_valid,
            "run_valid": is_run_valid,
            "invalid_reasons": validator.invalid_reasons,
            "penalties": []
        }
    }
    
    run_path = out_dir / "run.json"
    
    # Validate final output schema
    schema_val = SchemaValidator()
    schema_val.validate(run_json, "Run")
    
    with open(run_path, "w", encoding="utf-8") as f:
        json.dump(run_json, f, indent=2)
        
    if ts_path.exists() and ts_path != out_dir / "transcript.log":
        shutil.copy(ts_path, out_dir / "transcript.log")
        
    return run_path
