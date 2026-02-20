import sys
import json
import tarfile
from unittest.mock import patch
from pathlib import Path

from nitbench.reporter import main

def test_reporter_main(tmp_path):
    suite_def = tmp_path / "suite.json"
    suite_def.write_text('{"case_weights": {"case1": 1.0, "case2": 2.0}}')
    
    run_dir = tmp_path / "run_dir"
    run_dir.mkdir()
    run_data = {
        "case_id": "case1",
        "validity": {"case_valid": True, "run_valid": True},
        "agent_profile": {
            "agent_family": "claude",
            "model_id": "claude-3-5-sonnet",
            "reasoning_level": "none"
        },
        "interaction_mode": "pty",
        "aut_mode": "manual",
        "metrics": {"SRAS": 1.0, "DR": 0.0, "RR": 1.0, "IVS": 1.0}
    }
    (run_dir / "run.json").write_text(json.dumps(run_data))
    
    # Create an archive mock
    archive_path = tmp_path / "run2.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        run_data2 = run_data.copy()
        run_data2["case_id"] = "case2"
        run_data2["metrics"] = {"SRAS": 0.5, "DR": 0.0, "RR": 1.0, "IVS": 1.0}
        
        json_path = tmp_path / "tmp_run.json"
        json_path.write_text(json.dumps(run_data2))
        tar.add(json_path, arcname="artifacts/run.json")
        
    output_path = tmp_path / "report.json"
    
    test_args = [
        "reporter.py",
        "--suite-id", "test_suite",
        "--suite-def", str(suite_def),
        "--run-dirs", str(run_dir),
        "--run-archives", str(archive_path),
        "--output", str(output_path)
    ]
    
    with patch.object(sys, 'argv', test_args):
        main()
        
    assert output_path.exists()
    with open(output_path, "r") as f:
        report = json.load(f)
        
    assert report["suite_id"] == "test_suite"
    assert len(report["results"]) == 1
    
    res = report["results"][0]
    # Weight avg of SRAS: (1.0 * 1.0 + 0.5 * 2.0) / 3.0 = 2.0 / 3.0 = 0.666
    assert abs(res["suite_metrics"]["SRAS_suite"] - 0.666) < 0.01
