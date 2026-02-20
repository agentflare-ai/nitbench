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
    
    ckpt_mgr.hashes.append({"checkpoint_id": "cp1", "repo_state_sha256": "abcdef"})
    
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
    
    # Needs a mock oracle result to parse
    oracle_dir = artifacts / "checkpoints" / "cp1" / "oracles" / "mock_lint"
    oracle_dir.mkdir(parents=True)
    (oracle_dir / "result.json").write_text('{"status": "ok", "exit_code": 0, "error_count": 0, "warning_count": 1, "info_count": 0}')
    
    result_path = finalize_run(
        case_dir,
        {"case_id": "test_case"},
        checkpoints_data,
        scoring_data,
        {"agent_family": "claude"},
        artifacts, validator, ckpt_mgr,
        oracle_bundle_sha256="BUNDLE_HASH",
        repo_initial_sha256="INITIAL_REPO_HASH"
    )
    
    assert result_path.exists()
    
    # Verify outputs
    out_dir = result_path.parent
    assert (out_dir / "scoring.yaml").exists()
    assert (out_dir / "transcript.cast").exists()
    assert (out_dir / "checkpoints.json").exists()
    
    with open(out_dir / "run_result.json", "r") as f:
        res = json.load(f)
        
    assert res["run_validity"] == "case_valid"
    assert len(res["run_hash"]) == 64
    assert res["oracle_bundle_sha256"] == "BUNDLE_HASH"
    assert res["repo_initial_sha256"] == "INITIAL_REPO_HASH"
    
    with open(out_dir / "checkpoints.json", "r") as f:
        cps = json.load(f)
        
    assert cps["repo_initial_sha256"] == "INITIAL_REPO_HASH"
    assert cps["checkpoints"][0]["repo_state_sha256"] == "abcdef"

def test_finalize_run_invalid(mock_output_setup):
    case_dir, artifacts, validator, ckpt_mgr = mock_output_setup
    
    validator.invalid_reasons.append("network_attempt")
    
    result_path = finalize_run(
        case_dir,
        {"case_id": "test_case"},
        {"checkpoints": []},
        {},
        {"agent_family": "claude"},
        artifacts, validator, ckpt_mgr,
        "BUNDLE", "REPO"
    )
    
    with open(result_path, "r") as f:
        res = json.load(f)
        
    assert res["run_validity"] == "case_invalid"
    assert "network_attempt" in res["invalid_reasons"]
