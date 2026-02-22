import pytest
from nitbench.metrics.report import generate_report

def test_generate_report():
    runs = [
        {
            "case_id": "case1",
            "validity": {"case_valid": True, "run_valid": True},
            "agent_profile": {
                "agent_family": "claude",
                "model_id": "claude-3-5-sonnet",
                "reasoning_level": "none"
            },
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "metrics": {
                "SRAS": 0.8,
                "DR": 0.2,
                "RR": 0.9,
                "IVS": 0.5,
                "OS": 0.1,
                "PIR": 0.9
            }
        },
        {
            "case_id": "case2",
            "validity": {"case_valid": True, "run_valid": True},
            "agent_profile": {
                "agent_family": "claude",
                "model_id": "claude-3-5-sonnet",
                "reasoning_level": "none"
            },
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "metrics": {
                "SRAS": 0.6,
                "DR": 0.4,
                "RR": 0.5,
                "IVS": 0.3,
                "OS": None,
                "PIR": None
            }
        },
        {
            "case_id": "case1",
            "validity": {"case_valid": True, "run_valid": True},
            "agent_profile": {
                "agent_family": "claude",
                "model_id": "claude-3-7-sonnet", # Different model
                "reasoning_level": "none"
            },
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "metrics": {
                "SRAS": 0.9,
                "DR": 0.1,
                "RR": 0.95,
                "IVS": 0.8,
                "OS": 0.0,
                "PIR": 1.0
            }
        }
    ]
    
    weights = {"case1": 2.0, "case2": 1.0}
    
    report = generate_report("test_suite", weights, runs)
    
    assert report["report_version"] == "nitbench.report.v1"
    assert len(report["results"]) == 2
    
    # Check aggregation for claude-3-5-sonnet (weight 2 for case1, 1 for case2)
    # SRAS = (0.8 * 2.0 + 0.6 * 1.0) / 3.0 = (1.6 + 0.6) / 3.0 = 2.2 / 3.0 = 0.7333
    res_35 = next(r for r in report["results"] if r["model_id"] == "claude-3-5-sonnet")
    assert abs(res_35["suite_metrics"]["SRAS_suite"] - 0.7333) < 0.001
    
    # OS has weight 2.0 from case1, case2 is None so it's excluded from denominator
    # OS = (0.1 * 2.0) / 2.0 = 0.1
    assert res_35["suite_metrics"]["OS_suite"] == 0.1
    
    # Check Model Sensitivity
    ms = report["model_sensitivity"]
    assert len(ms) == 1
    sens = ms[0]
    # Delta SRAS between 3.5 (0.733) and 3.7 (0.9, only runs case1)
    assert sens["SRAS"] > 0
    assert "claude/none" == sens["key"]
    # Check Reasoning Sensitivity (should be empty as all are "none")
    rs = report["reasoning_sensitivity"]
    assert rs is None
