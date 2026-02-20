import json
import pytest
import time
from pathlib import Path

from nitbench.sandbox.orchestrator import TranscriptLogger, BudgetEnforcer

def test_transcript_logger(tmp_path):
    log_file = tmp_path / "transcript.log"
    logger = TranscriptLogger(log_file, "pty")
    
    # Assert header
    lines = log_file.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert header["format"] == "nitbench.cast"
    assert header["interaction_mode"] == "pty"
    
    # Log events
    logger.log_input("ls\n", 1.0)
    logger.log_output("file1.txt\n", 1.5)
    logger.log_marker({"type": "checkpoint", "checkpoint_id": "cp1", "proxy_value": 0}, 2.0)
    
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    
    ev1 = json.loads(lines[1])
    assert ev1 == [1.0, "i", "ls\n"]
    
    ev3 = json.loads(lines[3])
    assert ev3 == [2.0, "m", {"type": "checkpoint", "checkpoint_id": "cp1", "proxy_value": 0}]

def test_budget_enforcer():
    budgets = {
        "max_agent_actions": 2,
        "max_commits": 1,
        "max_wall_seconds": 1
    }
    enforcer = BudgetEnforcer(budgets)
    
    assert not enforcer.is_invalid
    
    enforcer.record_action()
    enforcer.record_action()
    assert not enforcer.is_invalid
    
    enforcer.record_action()  # 3rd action
    assert enforcer.is_invalid
    assert "budget_exceeded:agent_actions" in enforcer.invalid_reasons
    
    enforcer.record_commit()
    enforcer.record_commit() # 2nd commit
    assert "budget_exceeded:commits" in enforcer.invalid_reasons

    # Check wall time
    time.sleep(1.1)
    enforcer.check_wall_time()
    assert "budget_exceeded:wall_seconds" in enforcer.invalid_reasons
