import pytest
import math
from nitbench.metrics.scoring import calculate_metrics

def test_calculate_metrics():
    scoring_data = {
        "normalization": {"violation_budget": 10.0},
        "severity_weights": {"error": 1.0, "warning": 0.5, "info": 0.1},
        "category_weights": {"lint": 1.0},
        "oracle_weights": {"mock1": 1.0},
        "oracles": [
            {"id": "mock1", "soft_rule": True, "category": "lint"}
        ]
    }
    
    checkpoints_data = {
        "checkpoints": [
            {"id": "cp_baseline", "phase": "baseline", "score": True, "trigger": {"value": 0}},
            {"id": "cp_work1", "phase": "work", "score": True, "trigger": {"value": 10}},
            {"id": "cp_work2", "phase": "work", "score": True, "trigger": {"value": 20}}
        ]
    }    
    oracle_results = {
        "cp_baseline": {
            "mock1": {"error_count": 0, "warning_count": 0, "info_count": 0}
        },
        "cp_work1": {
            # 5 errors = mass 5.0 -> new_mass 5.0 -> sras 0.5
            "mock1": {"error_count": 5, "warning_count": 0, "info_count": 0}
        },
        "cp_work2": {
            # 2 errors = mass 2.0 -> new_mass 2.0 -> sras 0.8
            "mock1": {"error_count": 2, "warning_count": 0, "info_count": 0}
        }
    }
    
    res = calculate_metrics(scoring_data, checkpoints_data, oracle_results)
    
    cp_list = res["checkpoints"]
    assert len(cp_list) == 3
    assert cp_list[0]["sras"] == 1.0
    assert cp_list[1]["sras"] == 0.5
    assert cp_list[2]["sras"] == 0.8
    
    m = res["metrics"]
    assert m["SRAS"] == 0.65  # (0.5 + 0.8) / 2
    
    # Progress total = 20 - 0 = 20
    # Drift mass = 5.0 (from 0 to 5 in work1)
    # violation_budget = 10.0
    assert m["DR"] == 0.025 # 5.0 / (10.0 * 20)
    
    # Recovery mass = 3.0 (from 5 down to 2 in work2)
    assert m["RR"] == 0.6 # 3.0 / 5.0
    
    assert m["OS"] is None
    assert m["PIR"] is None
