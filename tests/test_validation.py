import pytest
from pathlib import Path
from nitbench.validation.validator import SchemaValidator, parse_yaml_file

def test_schema_validator_loads():
    validator = SchemaValidator()
    assert validator.schema["$id"] == "nitbench:schema:1.0.0"

def test_validate_case_invalid(tmp_path):
    validator = SchemaValidator()
    # Missing required fields
    invalid_case = {
        "case_version": "nitbench.case.v1"
    }
    with pytest.raises(ValueError, match="Validation failed"):
        validator.validate(invalid_case, "Case")

def test_parse_yaml_file_invalid(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("a: b\nc: - [")
    with pytest.raises(ValueError, match="Invalid YAML"):
        parse_yaml_file(bad_yaml)
