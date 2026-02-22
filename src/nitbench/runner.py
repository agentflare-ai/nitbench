import argparse
import json
import sys
import traceback
from pathlib import Path

from nitbench.validation.validator import SchemaValidator
from nitbench.validation.package import validate_package_root, validate_spec_md, validate_index_md
from nitbench.validation.case import validate_case
from nitbench.sandbox.workspace import materialize_repo
from nitbench.sandbox.environment import AutSandbox
from nitbench.sandbox.orchestrator import TranscriptLogger, BudgetEnforcer, ActionLogger
from nitbench.sandbox.validator import RunValidator
from nitbench.sandbox.checkpoint import CheckpointManager
from nitbench.sandbox.output import finalize_run
from nitbench.sandbox.package import create_deployable_package
from nitbench.sandbox.pty_harness import InteractivePtyHarness
from nitbench.oracle.bundle import select_and_place_aif, generate_oracle_bundle
from nitbench.oracle.harness import OracleHarness
from nitbench.agents.registry import get_adapter
import nitbench.agents  # noqa: F401 — triggers adapter registration


def run_single(
    package_dir: Path,
    case_id: str,
    agent_family: str,
    output_dir: Path,
    aut_argv: list[str],
    model: str | None = None,
    reasoning_level: str | None = None,
) -> Path:
    """Execute a single benchmark run and return the path to run.json."""
    import datetime
    import hashlib

    run_start_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
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

    # --- PHASE 2: Setup - Sandbox & Workspace ---
    print("Phase 2: Materializing workspace...")
    workspace_dir = output_dir / "workspace"
    harness_artifacts = output_dir / "harness_artifacts"
    artifacts_dir = harness_artifacts / "artifacts"
    harness_artifacts.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    repo_ws, repo_initial_sha256 = materialize_repo(case_dir, case_data, workspace_dir)

    actions_file = artifacts_dir / "actions.jsonl"
    open(actions_file, "w").close()
    action_logger = ActionLogger(actions_file)

    sandbox = AutSandbox(workspace_dir, case_data, action_logger)

    # --- PHASE 3: AIF Placement & Oracle Bundle ---
    print("Phase 3: Placing AIF and generating Oracle Bundle...")
    aif_target, aif_hash = select_and_place_aif(case_dir, agent_family, repo_ws, case_data)

    bundle_out = artifacts_dir / "oracle_bundle"
    manifest_path, oracle_bundle_sha256 = generate_oracle_bundle(
        aif_target, scoring_data, {}, bundle_out
    )

    # --- PHASE 4: Orchestration & Agent Interaction ---
    print("Phase 4: Orchestrating agent run...")

    adapter = get_adapter(agent_family)

    agent_profile = adapter.build_agent_profile(
        **({"model": model} if model else {}),
        **({"reasoning_level": reasoning_level} if reasoning_level else {}),
    )

    run_validator = RunValidator(case_data, agent_profile)
    run_validator.record_agent_profile()

    log_path = harness_artifacts / "transcript.log"
    logger = TranscriptLogger(log_path, interaction_mode="pty")
    sandbox.transcript_logger = logger

    budgets = case_data.get("budgets", {})
    budget_enforcer = BudgetEnforcer(budgets)

    # --- PHASE 4: Checkpoints ---
    checkpoint_mgr = CheckpointManager(checkpoints_data, repo_ws, artifacts_dir, logger)

    # Initial checkpoint
    checkpoint_mgr.trigger_if_needed("at_proxy_value", 0)

    # Deliver task text to AUT (spec §7.2: MUST explicitly state AUT MUST follow placed AIF)
    task_md_path = case_dir / "task.md"
    task_text = sandbox.deliver_task_text(task_md_path)
    logger.log_output(task_text)

    # Launch AUT via interactive PTY harness
    print("Starting interactive PTY session...")

    adapter.pre_flight(repo_ws)

    pty_harness = InteractivePtyHarness(
        aut_command=aut_argv,
        sandbox=sandbox,
        workspace_repo=repo_ws,
        logger=logger,
        action_logger=action_logger,
        budget_enforcer=budget_enforcer,
        checkpoint_mgr=checkpoint_mgr,
        run_validator=run_validator,
        task_text=task_text,
        agent_adapter=adapter,
    )
    try:
        aut_exit_code = pty_harness.run()
    finally:
        adapter.post_flight()
    print(f"AUT exited with code {aut_exit_code}")

    # Update agent_profile with model detected from live PTY output
    if pty_harness.detected_model_id is not None:
        agent_profile["model_id"] = pty_harness.detected_model_id

    # Ensure AIF was not tampered with
    run_validator.check_aif_modification(aif_target, aif_hash)
    run_validator.check_oracle_bundle_lineage(manifest_path, aif_hash)

    # Combine budget failures
    if budget_enforcer.is_invalid:
        run_validator.invalid_reasons.extend(budget_enforcer.invalid_reasons)

    # --- PHASE 5: Oracle Harness Execution ---
    print("Phase 5: Executing Oracles...")
    oracle_harness = OracleHarness(scoring_data)
    for checkpoint in checkpoint_mgr.executed_checkpoints:
        snap_tgz = artifacts_dir / "checkpoints" / checkpoint / "repo.snapshot.tgz"
        oracle_harness.execute_all(checkpoint, snap_tgz, artifacts_dir)

    # --- PHASE 7 / FINAL: Output Generation ---
    print("Finalizing outputs...")
    task_md_sha256 = hashlib.sha256(task_md_path.read_bytes()).hexdigest() if task_md_path.exists() else ""

    result_path = finalize_run(
        case_dir,
        case_data,
        checkpoints_data,
        scoring_data,
        agent_profile,
        harness_artifacts,
        artifacts_dir,
        run_validator,
        checkpoint_mgr,
        oracle_bundle_sha256,
        repo_initial_sha256,
        aif_hash,
        task_md_sha256,
        start_time_utc=run_start_time
    )

    pkg_tar = output_dir / f"{case_id}.run.tar.gz"
    create_deployable_package(harness_artifacts, pkg_tar)

    print(f"Run complete! Result validity: {run_validator.is_run_valid}")
    print(f"Deployable package: {pkg_tar}")

    return result_path


def _load_run_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _count_violations(run_data: dict) -> tuple[int, int]:
    """Sum error_count and warning_count across all checkpoint oracles."""
    errors = 0
    warnings = 0
    for cp in run_data.get("checkpoints", []):
        for oracle in cp.get("oracles", []):
            errors += oracle.get("error_count", 0)
            warnings += oracle.get("warning_count", 0)
    return errors, warnings


def print_summary_table(case_id: str, agent_family: str, results: list[dict]) -> None:
    """Print a plain-text comparison table after a multi-run sweep."""
    print()
    print(f"{case_id} -- {agent_family} sweep ({len(results)} runs)")
    print()

    header = f" {'Model':<25} {'Reasoning':<12} {'SRAS':>6} {'DR':>6} {'Errors':>8} {'Warnings':>9}"
    print(header)

    for r in results:
        run_data = r["run_data"]
        metrics = run_data.get("metrics", {})
        errors, warnings = _count_violations(run_data)
        sras = metrics.get("SRAS", 0.0)
        dr = metrics.get("DR", 0.0)
        model = r["model"]
        reasoning = r["reasoning_level"]

        row = f" {model:<25} {reasoning:<12} {sras:>6.3f} {dr:>6.3f} {errors:>8} {warnings:>9}"
        print(row)

    print()


def main():
    parser = argparse.ArgumentParser(description="NitBench Evaluation Runner v1.0.0")
    parser.add_argument("--package-dir", type=Path, required=True, help="Path to the NitBench package root")
    parser.add_argument("--case-id", type=str, required=True, help="ID of the case to run")
    parser.add_argument("--agent-family", type=str, required=True, help="Agent family (e.g., claude, gemini, codex)")
    parser.add_argument("--output-dir", type=Path, required=True, help="Path to write the output artifacts")
    parser.add_argument("--model", type=str, default=None, help="Specific model to run (uses adapter default if omitted)")
    parser.add_argument("--reasoning-level", type=str, default=None, help="Specific reasoning level to run")
    parser.add_argument("--all-models", action="store_true", help="Run every model the adapter supports")
    parser.add_argument("--all-reasoning-levels", action="store_true", help="Run every reasoning level the adapter supports")

    args = parser.parse_args()

    package_dir: Path = args.package_dir
    case_id: str = args.case_id
    agent_family: str = args.agent_family
    output_dir: Path = args.output_dir

    try:
        adapter = get_adapter(agent_family)
        if adapter is None:
            print(f"Error: no registered adapter for '{agent_family}'", file=sys.stderr)
            sys.exit(1)

        # --- Resolve the (model, reasoning_level) matrix ---
        if args.all_models or args.all_reasoning_levels:
            models = adapter.supported_models if args.all_models else [args.model or adapter.supported_models[0]]
            reasoning_levels = adapter.supported_reasoning_levels if args.all_reasoning_levels else [args.reasoning_level or adapter.supported_reasoning_levels[0]]
        else:
            models = [args.model or adapter.supported_models[0]]
            reasoning_levels = [args.reasoning_level or adapter.supported_reasoning_levels[0]]

        combos = [(m, r) for m in models for r in reasoning_levels]
        is_sweep = len(combos) > 1

        results = []
        for model, reasoning_level in combos:
            aut_argv = adapter.aut_command_for(model, reasoning_level)

            if is_sweep:
                slug = f"{model}_{reasoning_level}"
                run_output_dir = output_dir / slug
                print(f"\n{'='*60}")
                print(f"  Sweep: model={model}  reasoning={reasoning_level}")
                print(f"{'='*60}\n")
            else:
                run_output_dir = output_dir

            try:
                run_json_path = run_single(
                    package_dir, case_id, agent_family, run_output_dir, aut_argv,
                    model=model, reasoning_level=reasoning_level,
                )
                run_data = _load_run_json(run_json_path)
                results.append({
                    "model": model,
                    "reasoning_level": reasoning_level,
                    "run_data": run_data,
                    "status": "ok",
                })
            except Exception as e:
                print(f"Run failed for {model}/{reasoning_level}: {e}", file=sys.stderr)
                traceback.print_exc()
                results.append({
                    "model": model,
                    "reasoning_level": reasoning_level,
                    "run_data": {"metrics": {}, "checkpoints": []},
                    "status": "failed",
                })

        # --- Summary ---
        if is_sweep:
            ok_results = [r for r in results if r["status"] == "ok"]
            if ok_results:
                print_summary_table(case_id, agent_family, ok_results)

            failed = [r for r in results if r["status"] == "failed"]
            if failed:
                print(f"{len(failed)} run(s) failed:")
                for r in failed:
                    print(f"  - {r['model']} / {r['reasoning_level']}")

    except Exception as e:
        print(f"Runner failed: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
