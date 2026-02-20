import sys
import json
import pytest
import tarfile
from unittest.mock import patch
from pathlib import Path

from nitbench.runner import main


@pytest.fixture
def mock_package_dir(tmp_path):
    pkg = tmp_path / "mock_pkg"
    pkg.mkdir()
    
    # nitbench.spec.md
    (pkg / "nitbench.spec.md").write_text("* **spec_name** MUST be `NitBench`.\n* **spec_version** MUST be `1.0.0`.\n* **spec_status** MUST be `stable`.")
    
    # INDEX.md
    index = {
        "index_version": "nitbench.index.v1",
        "spec_version": "1.0.0",
        "cases": [{"case_id": "test.case.001", "title": "Test", "path": "cases/test.case.001"}]
    }
    (pkg / "INDEX.md").write_text(f"<!-- NITBENCH_INDEX_V1 -->\n```json\n{json.dumps(index)}\n```")
    
    # Case directory
    case_dir = pkg / "cases" / "test.case.001"
    case_dir.mkdir(parents=True)
    
    (case_dir / "task.md").write_text("# Task")
    
    (case_dir / "aif").mkdir()
    (case_dir / "aif" / "template.md").write_text("<!-- NITBENCH_RULE:TEST_RULE -->")
    
    (case_dir / "repo").mkdir()
    (case_dir / "repo" / "main.py").write_text("print('hello')")
    
    # case.json
    case_data = {
        "case_version": "nitbench.case.v1",
        "case_id": "test.case.001",
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
    (case_dir / "case.json").write_text(json.dumps(case_data))
    
    # checkpoints.json
    checkpoints_data = {
        "checkpoints_version": "nitbench.checkpoints.v1",
        "case_id": "test.case.001",
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
                "id": "cp_end",
                "phase": "work",
                "score": True,
                "trigger": {
                    "type": "end_of_run"
                }
            }
        ]
    }
    (case_dir / "checkpoints.json").write_text(json.dumps(checkpoints_data))
    
    # scoring.yaml (JSON formatting is valid YAML)
    scoring_data = {
        "scoring_version": "nitbench.scoring.v1",
        "case_id": "test.case.001",
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
            "test_oracle": 1.0
        },
        "oracles": [
            {
                "id": "test_oracle",
                "exec_context": "harness",
                "tool_id": "test_tool",
                "repo_config_policy": "ignore_repo_configs",
                "category": "lint",
                "soft_rule": True,
                "cwd": ".",
                "command": ["echo", "test"],
                "timeout_seconds": 30,
                "mutates_snapshot": False,
                "expected_exit_codes": {
                    "ok": [0],
                    "violations": [1]
                },
                "counting": {
                    "mode": "exit_code"
                }
            }
        ]
    }
    (case_dir / "scoring.yaml").write_text(json.dumps(scoring_data))
    
    return pkg


def test_runner_main(mock_package_dir, tmp_path):
    output_dir = tmp_path / "output"
    
    test_args = [
        "runner.py",
        "--package-dir", str(mock_package_dir),
        "--case-id", "test.case.001",
        "--agent-family", "claude",
        "--output-dir", str(output_dir)
    ]
    
    with patch.object(sys, 'argv', test_args):
        main()
        
    # Verify outputs
    assert output_dir.exists()
    
    # Workspace should have CLAUDE.md placed inside repo
    assert (output_dir / "workspace" / "repo" / "CLAUDE.md").exists()
    
    # Harness Artifacts should have oracle_bundle, run_result.json, etc.
    artifacts = output_dir / "harness_artifacts"
    assert (artifacts / "oracle_bundle" / "manifest.json").exists()
    assert (artifacts / "run_result" / "run_result.json").exists()
    assert (artifacts / "run_result" / "checkpoints.json").exists()
    assert (artifacts / "transcript.cast").exists()
    
    # Run result validity should be "case_valid" for the simulated happy path
    with open(artifacts / "run_result" / "run_result.json", "r") as f:
        res = json.load(f)
    assert res["run_validity"] == "case_valid"
    
    # Deployable tarball should exist
    pkg_tar = output_dir / "test.case.001.run.tar.gz"
    assert pkg_tar.exists()
    with tarfile.open(pkg_tar, "r:gz") as tar:
        names = tar.getnames()
        assert any(n.endswith("run_result.json") for n in names)
