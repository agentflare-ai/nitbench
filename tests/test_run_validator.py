import pytest
from pathlib import Path
import json

from nitbench.sandbox.validator import RunValidator

@pytest.fixture
def run_validator():
    case_data = {
        "case_id": "test.case",
        "allow_aif_modification": False
    }
    agent_profile = {
        "agent_family": "claude",
        "model_id": "claude-3-5-sonnet",
        "reasoning_level": "none",
        "interaction_mode": "pty",
        "aut_mode": "manual",
        "tool_mode": "interactive_pty"
    }
    return RunValidator(case_data, agent_profile)

def test_record_agent_profile(run_validator):
    run_validator.record_agent_profile()
    assert "agent_profile_sha256" in run_validator.hashes

def test_check_agent_profile_switch(run_validator):
    switched = run_validator.agent_profile.copy()
    switched["model_id"] = "claude-3-haiku"
    run_validator.check_agent_profile_switch(switched)
    assert "model_or_reasoning_switch" in run_validator.invalid_reasons

def test_detect_tampering(run_validator):
    run_validator.detect_tampering("command", ["cat", "../../../scoring.yaml"], "/repo")
    assert "oracle_tampering_attempt" in run_validator.invalid_reasons
    
    run_validator.detect_tampering("command", ["cat", "/etc/passwd"], "/repo")
    assert "sandbox_escape_attempt" in run_validator.invalid_reasons
    
    run_validator.detect_tampering("command", ["curl", "http://example.com"], "/repo")
    assert "network_attempt" in run_validator.invalid_reasons

def test_check_aif_modification(run_validator, tmp_path):
    aif_path = tmp_path / "CLAUDE.md"
    content = b"original rules"
    aif_path.write_bytes(content)
    
    import hashlib
    initial_hash = hashlib.sha256(content).hexdigest()
    
    run_validator.check_aif_modification(aif_path, initial_hash)
    assert run_validator.is_run_valid
    
    aif_path.write_bytes(b"modified rules")
    run_validator.check_aif_modification(aif_path, initial_hash)
    assert not run_validator.is_run_valid
    assert "aif_modified" in run_validator.invalid_reasons
