import json
import pytest
from pathlib import Path

import yaml

from nitbench.validation.case import (
    CaseValidationError,
    validate_case,
    validate_case_id,
    validate_case_paths,
)
from nitbench.validation.validator import SchemaValidator

@pytest.fixture
def valid_case_dir(tmp_path):
    case_dir = tmp_path / "valid.case.001"
    case_dir.mkdir()
    (case_dir / "aif").mkdir()
    (case_dir / "repo").mkdir()
    (case_dir / "task.md").write_text("# Task\n")

    case_json = {
        "case_version": "nitbench.case.v1",
        "case_id": "valid.case.001",
        "title": "A test case",
        "languages": ["python"],
        "difficulty": "easy",
        "weight": 1.0,
        "repo": {
            "representation": "git_worktree",
            "path": "repo"
        },
        "aif_map": [
            {
                "agent_family": "claude",
                "template_path": "aif/template.md",
                "target_path": "CLAUDE.md"
            }
        ],
        "aif_map_default": {
            "template_path": "aif/template.md",
            "target_path": "CLAUDE.md"
        },
        "budgets": {
            "max_agent_actions": 100
        },
        "oracle_model": {
            "oracle_model_version": "nitbench.oracle_model.v1",
            "execution": "harness_only",
            "config_visibility": "harness_private",
            "bundle_source": "aif_derived"
        },
        "aut_sandbox": {
            "network": "forbidden",
            "allowed_tools": [
                {
                    "name": "python",
                    "version_cmd": ["python", "--version"],
                    "version_regex": "Python 3\\.\\d+"
                }
            ],
            "allowed_write_globs": ["*"],
            "protected_globs": ["CLAUDE.md"],
            "prohibited_executable_sets": [
                "nitbench.prohibited.lint_format.standard",
                "nitbench.prohibited.install.standard"
            ],
            "prohibited_attempt_policy": {
                "lint_format": "invalid",
                "install": "invalid"
            }
        },
        "allow_aif_modification": False,
        "allow_batch_mode": False
    }

    (case_dir / "case.json").write_text(json.dumps(case_json))

    checkpoints_json = {
        "checkpoints_version": "nitbench.checkpoints.v1",
        "case_id": "valid.case.001",
        "context_proxy": {
            "type": "agent_action_count"
        },
        "checkpoints": [
            {
                "id": "cp_baseline",
                "phase": "baseline",
                "score": True,
                "trigger": {
                    "type": "at_proxy_value",
                    "value": 0
                }
            },
            {
                "id": "cp_work",
                "phase": "work",
                "score": True,
                "trigger": {
                    "type": "at_proxy_value",
                    "value": 10
                }
            }
        ]
    }
    (case_dir / "checkpoints.json").write_text(json.dumps(checkpoints_json))

    scoring_yaml = {
        "scoring_version": "nitbench.scoring.v1",
        "case_id": "valid.case.001",
        "oracle_bundle": {
            "bundle_type": "aif_derived_opaque",
            "generator_id": "python-default",
            "generator_version": "1.0.0",
            "manifest_version": "nitbench.oracle_manifest.v1"
        },
        "normalization": {
            "violation_budget": 10.0
        },
        "severity_weights": {
            "error": 1.0,
            "warning": 0.5,
            "info": 0.1
        },
        "category_weights": {
            "format": 1.0,
            "lint": 1.0,
            "naming": 1.0,
            "convention": 2.0
        },
        "oracle_weights": {
            "pylint": 1.0
        },
        "oracles": [
            {
                "id": "pylint",
                "exec_context": "harness",
                "tool_id": "pylint",
                "repo_config_policy": "ignore_repo_configs",
                "category": "lint",
                "soft_rule": True,
                "cwd": ".",
                "command": ["pylint", "repo"],
                "timeout_seconds": 30,
                "mutates_snapshot": False,
                "expected_exit_codes": {
                    "ok": [0],
                    "violations": [1, 2, 4, 8, 16, 32]
                },
                "counting": {
                    "mode": "exit_code"
                }
            }
        ]
    }
    
    with open(case_dir / "scoring.yaml", "w") as f:
        yaml.dump(scoring_yaml, f)

    return case_dir


def test_validate_case_id():
    validate_case_id(Path("valid.case.001"))
    with pytest.raises(CaseValidationError):
        validate_case_id(Path("T_O_O_C_A_P_S"))
    with pytest.raises(CaseValidationError):
        validate_case_id(Path("1."))


def test_validate_case_full(valid_case_dir):
    validator = SchemaValidator()
    # Should pass without errors
    validate_case(valid_case_dir, validator)

def test_validate_case_missing_file(valid_case_dir):
    (valid_case_dir / "task.md").unlink()
    validator = SchemaValidator()
    with pytest.raises(CaseValidationError, match="Missing required file: task.md"):
        validate_case(valid_case_dir, validator)

def test_validate_case_monotonic(valid_case_dir):
    # Alter checkpoints to not be monotonic
    cp_path = valid_case_dir / "checkpoints.json"
    data = json.loads(cp_path.read_text())
    data["checkpoints"][0]["trigger"]["value"] = 10
    data["checkpoints"][1]["trigger"]["value"] = 5
    cp_path.write_text(json.dumps(data))
    
    validator = SchemaValidator()
    with pytest.raises(CaseValidationError, match="must be monotonic non-decreasing"):
        validate_case(valid_case_dir, validator)

def test_validate_case_repo_config_policy(valid_case_dir):
    yaml_path = valid_case_dir / "scoring.yaml"
    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)
        
    # Introduce error
    data["oracles"][0]["repo_config_policy"] = "no"
    with open(yaml_path, "w") as f:
        yaml.dump(data, f)
        
    validator = SchemaValidator()
    with pytest.raises(CaseValidationError, match="Schema validation failed"):
        # "no" violates the schema enum "ignore_repo_configs"
        validate_case(valid_case_dir, validator)
