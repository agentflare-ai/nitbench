import json
import re
from pathlib import Path
from typing import Any, Dict

from nitbench.validation.validator import SchemaValidator, parse_yaml_file

class CaseValidationError(ValueError):
    """Exception raised when a case fails validation."""


def validate_case_id(case_dir: Path) -> str:
    """Validate case directory name matches regex."""
    case_id = case_dir.name
    if not re.match(r"^[a-z0-9][a-z0-9._-]{2,63}$", case_id):
        raise CaseValidationError(f"Invalid case_id format: {case_id}")
    return case_id


def validate_case_paths(case_dir: Path) -> None:
    """Validate required paths within a case directory."""
    required_files = ["case.json", "task.md", "checkpoints.json", "scoring.yaml"]
    required_dirs = ["aif", "repo"]

    for f in required_files:
        if not (case_dir / f).is_file():
            raise CaseValidationError(f"Missing required file: {f}")

    for d in required_dirs:
        if not (case_dir / d).is_dir():
            raise CaseValidationError(f"Missing required directory: {d}")


def validate_case_json(case_dir: Path, validator: SchemaValidator, expected_case_id: str) -> Dict[str, Any]:
    """Validate case.json against schema and checklist rules."""
    path = case_dir / "case.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise CaseValidationError(f"Invalid case.json: {e}")

    try:
        validator.validate(data, "Case")
    except ValueError as e:
        raise CaseValidationError(f"Schema validation failed for case.json: {e}")

    if data.get("case_id") != expected_case_id:
        raise CaseValidationError(f"case.json case_id ({data.get('case_id')}) does not match directory ({expected_case_id})")

    # Oracle checks
    oracle = data.get("oracle_model", {})
    if oracle.get("execution") != "harness_only":
        raise CaseValidationError(f"oracle_model.execution must be 'harness_only', got {oracle.get('execution')}")
    if oracle.get("bundle_source") != "aif_derived":
        raise CaseValidationError(f"case_invalid:oracle_not_aif_derived. bundle_source must be 'aif_derived', got {oracle.get('bundle_source')}")

    # Sandbox checks
    sandbox = data.get("aut_sandbox", {})
    if sandbox.get("network") != "forbidden":
        raise CaseValidationError(f"aut_sandbox.network must be 'forbidden', got {sandbox.get('network')}")

    prohibited_sets = sandbox.get("prohibited_executable_sets", [])
    required_sets = [
        "nitbench.prohibited.lint_format.standard",
        "nitbench.prohibited.install.standard",
    ]
    for rset in required_sets:
        if rset not in prohibited_sets:
            raise CaseValidationError(f"Missing required prohibited executable set: {rset}")

    return data


def validate_checkpoints_json(case_dir: Path, validator: SchemaValidator, expected_case_id: str) -> Dict[str, Any]:
    """Validate checkpoints.json against schema and monotonic proxy constraints."""
    path = case_dir / "checkpoints.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise CaseValidationError(f"Invalid checkpoints.json: {e}")

    try:
        validator.validate(data, "Checkpoints")
    except ValueError as e:
        raise CaseValidationError(f"Schema validation failed for checkpoints.json: {e}")

    if data.get("case_id") != expected_case_id:
        raise CaseValidationError(f"checkpoints.json case_id mismatch: expected {expected_case_id}")

    # Enforce monotonic proxy values
    checkpoints = data.get("checkpoints", [])
    last_value = -1
    for cp in checkpoints:
        trigger = cp.get("trigger", {})
        if trigger.get("type") == "at_proxy_value":
            val = trigger.get("value", -1)
            if val < last_value:
                raise CaseValidationError(f"Checkpoint triggers must be monotonic non-decreasing, got {val} after {last_value}")
            last_value = val

    return data


def validate_scoring_yaml(case_dir: Path, validator: SchemaValidator, expected_case_id: str) -> Dict[str, Any]:
    """Validate scoring.yaml against schema and checklist rules."""
    path = case_dir / "scoring.yaml"
    try:
        data = parse_yaml_file(path)
    except Exception as e:
        raise CaseValidationError(f"Invalid scoring.yaml: {e}")

    try:
        validator.validate(data, "Scoring")
    except ValueError as e:
        raise CaseValidationError(f"Schema validation failed for scoring.yaml: {e}")

    if data.get("case_id") != expected_case_id:
        raise CaseValidationError(f"scoring.yaml case_id mismatch: expected {expected_case_id}")

    norm = data.get("normalization", {})
    if norm.get("violation_budget", 0) <= 0:
        raise CaseValidationError("normalization.violation_budget must be > 0")

    oracles = data.get("oracles", [])
    for oracle in oracles:
        if oracle.get("exec_context") != "harness":
            raise CaseValidationError(f"Oracle {oracle.get('id')} exec_context must be 'harness'")
        if oracle.get("repo_config_policy") != "ignore_repo_configs":
            raise CaseValidationError(f"Oracle {oracle.get('id')} repo_config_policy must be 'ignore_repo_configs'")

    return data


def validate_case(case_dir: Path, validator: SchemaValidator) -> Dict[str, Any]:
    """
    Perform all static validations for a case.
    Returns parsed configuration dictionaries if valid.
    """
    case_id = validate_case_id(case_dir)
    validate_case_paths(case_dir)
    
    case_json = validate_case_json(case_dir, validator, case_id)
    checkpoints_json = validate_checkpoints_json(case_dir, validator, case_id)
    scoring_yaml = validate_scoring_yaml(case_dir, validator, case_id)

    # Note: Validate oracles are repository-config agnostic (differential tests)
    # is a dynamic runtime check, but statically we checked `repo_config_policy` = 'ignore_repo_configs'
    
    return {
        "case_id": case_id,
        "case": case_json,
        "checkpoints": checkpoints_json,
        "scoring": scoring_yaml
    }
