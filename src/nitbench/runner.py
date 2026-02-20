import argparse
import sys
import traceback
from pathlib import Path

from nitbench.validation.validator import SchemaValidator
from nitbench.validation.package import validate_package_root, validate_spec_md, validate_index_md
from nitbench.validation.case import validate_case
from nitbench.sandbox.workspace import materialize_repo
from nitbench.sandbox.environment import AutSandbox
from nitbench.sandbox.orchestrator import TranscriptLogger, BudgetEnforcer
from nitbench.sandbox.validator import RunValidator
from nitbench.sandbox.checkpoint import CheckpointManager
from nitbench.sandbox.output import finalize_run
from nitbench.sandbox.package import create_deployable_package
from nitbench.oracle.bundle import select_and_place_aif, generate_oracle_bundle
from nitbench.oracle.harness import OracleHarness

def main():
    parser = argparse.ArgumentParser(description="NitBench Evaluation Runner v1.0.0")
    parser.add_argument("--package-dir", type=Path, required=True, help="Path to the NitBench package root")
    parser.add_argument("--case-id", type=str, required=True, help="ID of the case to run")
    parser.add_argument("--agent-family", type=str, required=True, help="Agent family (e.g., claude, openai)")
    parser.add_argument("--output-dir", type=Path, required=True, help="Path to write the output artifacts")
    
    args = parser.parse_args()
    
    package_dir: Path = args.package_dir
    case_id: str = args.case_id
    agent_family: str = args.agent_family
    output_dir: Path = args.output_dir
    
    try:
        print(f"Starting NitBench Runner for case: {case_id}")
        
        # --- PHASE 1: Validation ---
        print("Phase 1: Validating package and case...")
        validator = SchemaValidator()
        validate_package_root(package_dir)
        validate_spec_md(package_dir)
        validate_index_md(package_dir, validator)
        
        case_dir = package_dir / "cases" / case_id
        if not case_dir.exists():
            raise ValueError(f"Case directory not found: {case_dir}")
            
        case_cfg = validate_case(case_dir, validator)
        case_data = case_cfg["case"]
        checkpoints_data = case_cfg["checkpoints"]
        scoring_data = case_cfg["scoring"]
        
        # --- PHASE 3 Setup: Sandbox & Workspace ---
        print("Phase 3 Setup: Materializing workspace...")
        workspace_dir = output_dir / "workspace"
        harness_artifacts = output_dir / "harness_artifacts"
        harness_artifacts.mkdir(parents=True, exist_ok=True)
        
        repo_ws, repo_initial_sha256 = materialize_repo(case_dir, case_data, workspace_dir)
        
        sandbox = AutSandbox(workspace_dir, case_data)
        
        # --- PHASE 2: Oracle Bundle & AIF ---
        print("Phase 2: Placing AIF and generating Oracle Bundle...")
        aif_target, aif_hash = select_and_place_aif(case_dir, agent_family, repo_ws, case_data)
        
        bundle_out = harness_artifacts / "oracle_bundle"
        manifest_path, oracle_bundle_sha256 = generate_oracle_bundle(
            aif_target, scoring_data, {}, bundle_out
        )
        
        # --- PHASE 3 Execution: Orchestrator, PTY, Transcript ---
        print("Phase 3 & 4: Orchestrating agent run...")
        
        agent_profile = {
            "agent_family": agent_family,
            "model_id": "unknown", # Normally provided by agent adapter
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "tool_mode": "interactive_pty"
        }
        
        run_validator = RunValidator(case_data, agent_profile)
        run_validator.record_agent_profile()
        
        log_path = harness_artifacts / "transcript.cast"
        logger = TranscriptLogger(log_path, interaction_mode="pty")
        
        budgets = case_data.get("budgets", {})
        budget_enforcer = BudgetEnforcer(budgets)
        
        # --- PHASE 4: Checkpoints ---
        checkpoint_mgr = CheckpointManager(checkpoints_data, repo_ws, harness_artifacts, logger)
        
        # Initial checkpoint
        checkpoint_mgr.trigger_if_needed("at_proxy_value", 0)
        
        # For MVP, we simulate a single command execution
        print("Starting simulated interaction...")
        cmd = ["echo", "Agent attempting task..."]
        sandbox.run_pty(cmd, cwd=repo_ws)
        logger.log_output("Agent attempting task...\n")
        
        # Ensure AIF was not tampered with
        run_validator.check_aif_modification(aif_target, aif_hash)
        
        # End of run checkpoint
        checkpoint_mgr.trigger_if_needed("end_of_run")
        
        # Combine budget failures
        if budget_enforcer.is_invalid:
            run_validator.invalid_reasons.extend(budget_enforcer.invalid_reasons)
            
        # --- PHASE 5: Oracle Harness Execution ---
        print("Phase 5: Executing Oracles...")
        oracle_harness = OracleHarness(scoring_data)
        for checkpoint in checkpoint_mgr.executed_checkpoints:
            snap_path = harness_artifacts / "checkpoints" / checkpoint / "repo"
            oracle_harness.execute_all(checkpoint, snap_path, harness_artifacts)
            
        # --- PHASE 7 / FINAL: Output Generation ---
        print("Finalizing outputs...")
        result_path = finalize_run(
            case_dir,
            case_data,
            checkpoints_data,
            scoring_data,
            agent_profile,
            harness_artifacts,
            run_validator,
            checkpoint_mgr,
            oracle_bundle_sha256,
            repo_initial_sha256
        )
        
        pkg_tar = output_dir / f"{case_id}.run.tar.gz"
        create_deployable_package(harness_artifacts, pkg_tar)
        
        print(f"Run complete! Result validity: {run_validator.is_run_valid}")
        print(f"Deployable package: {pkg_tar}")
        
    except Exception as e:
        print(f"Runner failed: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
