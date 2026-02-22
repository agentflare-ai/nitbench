import json
import pytest
from pathlib import Path

from nitbench.sandbox.output import finalize_run
from nitbench.sandbox.validator import RunValidator
from nitbench.sandbox.checkpoint import CheckpointManager
from nitbench.sandbox.orchestrator import TranscriptLogger

@pytest.fixture
def mock_output_setup(tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "scoring.yaml").write_text("scoring_data", encoding="utf-8")
    
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    
    repo = tmp_path / "repo"
    repo.mkdir()
    
    logger = TranscriptLogger(tmp_path / "transcript.cast", "pty")
    logger.log_input("hello")
    
    validator = RunValidator({"case_id": "test_case"}, {"agent_family": "claude"})
    validator.record_agent_profile()
    
    ckpt_mgr = CheckpointManager(
        {"context_proxy": {"type": "agent_action_count"}, "checkpoints": []}, 
        repo, 
        artifacts, 
        logger
    )
    
    ckpt_mgr.hashes.append({"checkpoint_id": "cp1", "repo_state_sha256": "e" * 64})
    ckpt_mgr.executed_checkpoints.append("cp1")
    
    return case_dir, artifacts, validator, ckpt_mgr

def test_finalize_run_valid(mock_output_setup):
    case_dir, artifacts, validator, ckpt_mgr = mock_output_setup
    
    scoring_data = {
        "oracles": [{"id": "mock_lint", "soft_rule": True, "category": "lint"}],
        "normalization": {"violation_budget": 10.0}
    }
    checkpoints_data = {
        "checkpoints": [{"id": "cp1", "phase": "work"}]
    }
    
    artifacts_dir = artifacts / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    # Needs a mock oracle result to parse
    oracle_dir = artifacts_dir / "checkpoints" / "cp1" / "oracles" / "mock_lint"
    oracle_dir.mkdir(parents=True)
    (oracle_dir / "result.json").write_text('{"status": "ok", "exit_code": 0, "error_count": 0, "warning_count": 1, "info_count": 0}')
    
    # Use valid SHA256 hex strings for schema compliance
    mock_bundle_sha = "a" * 64
    mock_repo_sha = "b" * 64
    mock_aif_sha = "c" * 64
    mock_task_sha = "d" * 64

    result_path = finalize_run(
        case_dir,
        {"case_id": "test_case"},
        checkpoints_data,
        scoring_data,
        {
            "agent_family": "claude",
            "agent_version": "1.0",
            "model_id": "mock_model",
            "reasoning_level": "none",
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "tool_mode": "interactive_pty"
        },
        artifacts, artifacts_dir, validator, ckpt_mgr,
        oracle_bundle_sha256=mock_bundle_sha,
        repo_initial_sha256=mock_repo_sha,
        aif_sha256=mock_aif_sha,
        task_md_sha256=mock_task_sha
    )

    assert result_path.exists()

    # Verify outputs
    out_dir = result_path.parent
    assert (out_dir / "transcript.log").exists()
    assert (artifacts_dir / "hashes.json").exists()

    with open(out_dir / "run.json", "r") as f:
        res = json.load(f)

    assert res["validity"]["run_valid"] is True

    with open(artifacts_dir / "hashes.json", "r") as f:
        hashes = json.load(f)

    assert hashes["oracle_bundle_sha256"] == mock_bundle_sha
    assert hashes["repo_initial_sha256"] == mock_repo_sha

def test_finalize_run_invalid(mock_output_setup):
    case_dir, artifacts, validator, ckpt_mgr = mock_output_setup
    
    validator.invalid_reasons.append("network_attempt")
    artifacts_dir = artifacts / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    # Needs a mock oracle result to parse
    oracle_dir = artifacts_dir / "checkpoints" / "cp1" / "oracles" / "test_oracle"
    oracle_dir.mkdir(parents=True)
    (oracle_dir / "result.json").write_text('{"status": "ok", "exit_code": 0, "error_count": 0, "warning_count": 1, "info_count": 0}')
    
    result_path = finalize_run(
        case_dir,
        {"case_id": "test_case"},
        {"checkpoints": [{"id": "cp1", "phase": "work"}]},
        {"oracles": [{"id": "test_oracle", "soft_rule": True, "category": "lint"}], "normalization": {"violation_budget": 10.0}},
        {
            "agent_family": "claude",
            "agent_version": "1.0",
            "model_id": "mock_model",
            "reasoning_level": "none",
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "tool_mode": "interactive_pty"
        },
        artifacts, artifacts_dir, validator, ckpt_mgr,
        oracle_bundle_sha256="a" * 64,
        repo_initial_sha256="b" * 64,
        aif_sha256="c" * 64,
        task_md_sha256="d" * 64
    )
    
    with open(result_path, "r") as f:
        res = json.load(f)
        
    assert res["validity"]["run_valid"] is False
    assert "network_attempt" in res["validity"]["invalid_reasons"]
