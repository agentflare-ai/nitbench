import pytest
from pathlib import Path
import json

from nitbench.sandbox.checkpoint import ContextProxyTracker, CheckpointManager
from nitbench.sandbox.orchestrator import TranscriptLogger

def test_context_proxy_tracker():
    tracker = ContextProxyTracker("agent_action_count")
    assert tracker.value == 0
    tracker.advance(5)
    assert tracker.value == 5
    
    with pytest.raises(ValueError, match="Invalid context proxy type"):
        ContextProxyTracker("invalid_type")

def test_checkpoint_manager_triggers(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "file.txt").write_text("content", encoding="utf-8")
    
    log = tmp_path / "transcript.log"
    logger = TranscriptLogger(log)
    
    def_data = {
        "context_proxy": {"type": "agent_action_count"},
        "checkpoints": [
            {"id": "cp1", "trigger": {"type": "at_proxy_value", "value": 0}},
            {"id": "cp2", "trigger": {"type": "at_proxy_value", "value": 5}},
            {"id": "cp_end", "trigger": {"type": "end_of_run"}}
        ]
    }
    
    mgr = CheckpointManager(def_data, repo, artifacts, logger)
    
    # Init state trigger
    mgr.trigger_if_needed("at_proxy_value")
    assert "cp1" in mgr.executed_checkpoints
    assert "cp2" not in mgr.executed_checkpoints
    assert "cp_end" not in mgr.executed_checkpoints
    
    mgr.tracker.advance(5)
    mgr.trigger_if_needed("at_proxy_value")
    assert "cp2" in mgr.executed_checkpoints
    
    mgr.trigger_if_needed("end_of_run")
    assert "cp_end" in mgr.executed_checkpoints
    
    # Check artifacts
    assert (artifacts / "checkpoints" / "cp1" / "repo" / "file.txt").exists()
    assert (artifacts / "checkpoints" / "cp2" / "repo" / "file.txt").exists()
    assert len(mgr.hashes) == 3
    assert "repo_state_sha256" in mgr.hashes[0]

    # Check transcript markers
    events = log.read_text().splitlines()
    assert len(events) >= 4 # Header + 3 markers
    cp2_marker = json.loads(events[-2])
    assert cp2_marker[1] == "m"
    assert cp2_marker[2]["checkpoint_id"] == "cp2"
    assert cp2_marker[2]["proxy_value"] == 5
