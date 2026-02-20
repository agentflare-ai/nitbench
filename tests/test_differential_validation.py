import pytest
from pathlib import Path

from nitbench.validation.differential import (
    validate_oracle_differential,
    CaseValidationError
)

def test_validate_oracle_differential_pass(tmp_path):
    # Setup two identical copies
    dir_a = tmp_path / "copy_a"
    dir_b = tmp_path / "copy_b"
    dir_a.mkdir()
    dir_b.mkdir()
    
    (dir_b / "pyproject.toml").write_text("[tool.pylint]\n")
    
    def runner(oracle, path):
        # Deterministic result regardless of file present
        return {
            "status": "ok",
            "error_count": 0,
            "warning_count": 0,
            "info_count": 0,
        }
        
    oracle_def = {"id": "pylint-1", "tool_id": "pylint"}
    validate_oracle_differential(oracle_def, dir_a, dir_b, runner)

def test_validate_oracle_differential_fail(tmp_path):
    dir_a = tmp_path / "copy_a"
    dir_b = tmp_path / "copy_b"
    dir_a.mkdir()
    dir_b.mkdir()
    
    # Write a config that affects the runner
    (dir_a / ".pylintrc").write_text("...")
    (dir_b / ".pylintrc").write_text("...")
    
    def runner(oracle, path):
        # Simulate different outputs based on whether .pylintrc exists
        if (path / ".pylintrc").exists():
            return {
                "status": "ok",
                "error_count": 0,
                "warning_count": 0,
                "info_count": 0,
            }
        else:
             return {
                "status": "violations",
                "error_count": 1,
                "warning_count": 0,
                "info_count": 0,
            }
            
    oracle_def = {"id": "pylint-1", "tool_id": "pylint"}
    
    with pytest.raises(CaseValidationError, match="case_invalid:repo_config_influences_oracle"):
        validate_oracle_differential(oracle_def, dir_a, dir_b, runner)
