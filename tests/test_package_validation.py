import json
import pytest
from pathlib import Path

from nitbench.validation.package import (
    PackageValidationError,
    validate_package_root,
    validate_spec_md,
    validate_index_md,
)
from nitbench.validation.validator import SchemaValidator


def test_validate_package_root(tmp_path):
    # Ensure missing paths raise error
    with pytest.raises(PackageValidationError, match="Missing required path: nitbench.spec.md"):
        validate_package_root(tmp_path)

    # Add required paths
    (tmp_path / "nitbench.spec.md").touch()
    (tmp_path / "INDEX.md").touch()
    (tmp_path / "cases").mkdir()

    # Now it should pass
    validate_package_root(tmp_path)


def test_validate_spec_md(tmp_path):
    spec_md = tmp_path / "nitbench.spec.md"
    
    # Missing fields
    spec_md.write_text("Hello World", encoding="utf-8")
    with pytest.raises(PackageValidationError, match="Missing or incorrect spec identity fields: spec_name, spec_version, spec_status"):
        validate_spec_md(tmp_path)
        
    # Correct fields
    spec_md.write_text("""
    * **spec_name** MUST be `NitBench`.
    * **spec_version** MUST be `1.0.0`.
    * **spec_status** MUST be `stable`.
    """, encoding="utf-8")
    
    validate_spec_md(tmp_path)


def test_validate_index_md(tmp_path):
    validator = SchemaValidator()
    index_md = tmp_path / "INDEX.md"
    
    # Missing block
    index_md.write_text("Just some markdown", encoding="utf-8")
    with pytest.raises(PackageValidationError, match="Missing <!-- NITBENCH_INDEX_V1 -->"):
        validate_index_md(tmp_path, validator)
        
    # Invalid JSON
    index_md.write_text(
"<!-- NITBENCH_INDEX_V1 -->\n"
"```json\n"
"{ invalid }\n"
"```\n", encoding="utf-8")
    with pytest.raises(PackageValidationError, match="Invalid JSON"):
        validate_index_md(tmp_path, validator)
        
    # Valid JSON but fails schema (missing required fields)
    index_md.write_text(
"<!-- NITBENCH_INDEX_V1 -->\n"
"```json\n"
'{ "index_version": "nitbench.index.v1" }\n'
"```\n", encoding="utf-8")
    with pytest.raises(PackageValidationError, match="Schema validation failed"):
        validate_index_md(tmp_path, validator)
        
    # Valid Index
    valid_index = {
        "index_version": "nitbench.index.v1",
        "spec_version": "1.0.0",
        "cases": [
            {
                "case_id": "test.case.001",
                "title": "A correct test case",
                "path": "cases/test.case.001"
            }
        ]
    }
    index_md.write_text(
"<!-- NITBENCH_INDEX_V1 -->\n"
"```json\n"
f"{json.dumps(valid_index)}\n"
"```\n", encoding="utf-8")
    
    data = validate_index_md(tmp_path, validator)
    assert data["spec_version"] == "1.0.0"
    assert len(data["cases"]) == 1
