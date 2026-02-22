import pytest
import json
from pathlib import Path

from nitbench.oracle.harness import OracleHarness

def test_oracle_harness_execution(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    
    import tarfile
    snapshot_dir = tmp_path / "snapshot_dir"
    snapshot_dir.mkdir()
    (snapshot_dir / "code.py").write_text("print('bad')\n", encoding="utf-8")
    
    snapshot = tmp_path / "snapshot.tgz"
    with tarfile.open(snapshot, "w:gz") as tar:
        tar.add(snapshot_dir, arcname="repo")
        
    scoring_data = {
        "oracles": [
            {
                "id": "mock_lint",
                "cwd": ".",
                "command": ["echo", "Mock warning found"],
                "expected_exit_codes": {
                    "ok": [0],
                    "violations": [1]
                },
                "counting": {
                    "mode": "regex",
                    "regex_warning": "warning"
                }
            }
        ]
    }
    
    harness = OracleHarness(scoring_data)
    results = harness.execute_all("cp1", snapshot, artifacts)
    
    assert "mock_lint" in results
    res = results["mock_lint"]
    
    # "echo" exits with 0, which means "ok", but regex parsing overrides counts
    assert res["status"] == "ok"
    assert res["exit_code"] == 0
    assert res["error_count"] == 0
    assert res["warning_count"] == 1  # 1 match for "warning"
    
    # Check artifacts
    oracle_dir = artifacts / "checkpoints" / "cp1" / "oracles" / "mock_lint"
    assert oracle_dir.exists()
    assert (oracle_dir / "stdout.log").exists()
    assert (oracle_dir / "stderr.log").exists()
    assert (oracle_dir / "result.json").exists()
    
    with open(oracle_dir / "result.json", "r") as f:
        file_res = json.load(f)
    assert file_res["warning_count"] == 1
