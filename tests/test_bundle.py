import json
import pytest
from pathlib import Path

from nitbench.oracle.bundle import (
    OracleBundleError,
    select_and_place_aif,
    extract_aif_markers,
    generate_oracle_bundle
)

def test_select_and_place_aif(tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "aif").mkdir()
    template_path = case_dir / "aif" / "template.md"
    template_path.write_text("AIF CONTENT", encoding="utf-8")
    
    repo_ws = tmp_path / "repo_ws"
    repo_ws.mkdir()
    
    case_data = {
        "aif_map": [
            {
                "agent_family": "claude",
                "template_path": "aif/template.md",
                "target_path": "CLAUDE.md"
            }
        ]
    }
    
    target, hashed = select_and_place_aif(case_dir, "claude", repo_ws, case_data)
    assert target == repo_ws / "CLAUDE.md"
    assert target.exists()
    assert target.read_text() == "AIF CONTENT"
    assert len(hashed) == 64

def test_extract_aif_markers(tmp_path):
    aif = tmp_path / "CLAUDE.md"
    # valid markers and invalid markers
    content = """
    # Rules
    <!-- NITBENCH_RULE:NO_TABS -->
      <!-- NITBENCH_RULE:CLEAN_IMPORTS -->  
    <!-- NITBENCH_RULE:NO_TABS --> 
    <!-- NITBENCH_RULE:-->
    """
    aif.write_text(content, encoding="utf-8")
    
    with pytest.raises(OracleBundleError, match="Duplicate AIF Rule Markers found: NO_TABS"):
        extract_aif_markers(aif)
        
    # Valid unique markers
    content = """
    # Rules
    <!-- NITBENCH_RULE:NO_TABS -->
    <!-- NITBENCH_RULE:CLEAN_IMPORTS -->
    """
    aif.write_text(content, encoding="utf-8")
    markers = extract_aif_markers(aif)
    assert markers == {"NO_TABS", "CLEAN_IMPORTS"}

def test_generate_oracle_bundle(tmp_path):
    aif = tmp_path / "CLAUDE.md"
    aif.write_text("<!-- NITBENCH_RULE:PYLINT_001 -->", encoding="utf-8")
    
    scoring_yaml = {
        "case_id": "test.case.001",
        "oracle_bundle": {
            "generator_id": "test-gen",
            "generator_version": "1.0.0"
        },
        "oracles": [
            {
                "id": "pylint",
                "soft_rule": True
            }
        ]
    }
    
    bundle_out = tmp_path / "artifacts" / "oracle_bundle"
    manifest, bundle_hash = generate_oracle_bundle(aif, scoring_yaml, {}, bundle_out)
    
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["generator_id"] == "test-gen"
    assert data["oracle_bundle_sha256"] == bundle_hash
    assert data["rules"][0]["oracle_id"] == "pylint"
    assert data["rules"][0]["aif_rule_refs"] == ["PYLINT_001"]
