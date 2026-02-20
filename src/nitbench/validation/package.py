import json
import re
from pathlib import Path
from typing import Any, Dict

from nitbench.validation.validator import SchemaValidator


class PackageValidationError(ValueError):
    """Exception raised when a package fails validation."""


def validate_package_root(package_dir: Path) -> None:
    """Validate that the package root has required paths."""
    required_paths = ["nitbench.spec.md", "INDEX.md", "cases"]
    for path in required_paths:
        if not (package_dir / path).exists():
            raise PackageValidationError(f"Missing required path: {path}")

    if not (package_dir / "cases").is_dir():
        raise PackageValidationError("cases must be a directory")


def validate_spec_md(package_dir: Path) -> None:
    """
    Validate nitbench.spec.md declares:
    - spec_name: NitBench
    - spec_version: 1.0.0
    - spec_status: stable
    """
    spec_path = package_dir / "nitbench.spec.md"
    try:
        content = spec_path.read_text(encoding="utf-8")
    except Exception as e:
        raise PackageValidationError(f"Could not read nitbench.spec.md: {e}")

    # To be robust, we look for these specific strings or patterns in the markdown
    # A simple regex lookup or exact line matching.
    patterns = {
        "spec_name": r"spec_name.*?(NitBench)",
        "spec_version": r"spec_version.*?(1\.0\.0)",
        "spec_status": r"spec_status.*?(stable)",
    }

    errors = []
    for field, pattern in patterns.items():
        if not re.search(pattern, content, flags=re.IGNORECASE):
            errors.append(field)
            
    if errors:
        raise PackageValidationError(f"Missing or incorrect spec identity fields: {', '.join(errors)}")


def validate_index_md(package_dir: Path, validator: SchemaValidator) -> Dict[str, Any]:
    """
    Validate INDEX.md machine readable block.
    """
    index_path = package_dir / "INDEX.md"
    try:
        content = index_path.read_text(encoding="utf-8")
    except Exception as e:
        raise PackageValidationError(f"Could not read INDEX.md: {e}")

    # Look for the exact delimiter and a fenced json block
    # <!-- NITBENCH_INDEX_V1 -->
    # ```json
    # { ... }
    # ```
    match = re.search(r"<!-- NITBENCH_INDEX_V1 -->\s*```json\n(.*?)\n```", content, flags=re.DOTALL)
    if not match:
        raise PackageValidationError("Missing <!-- NITBENCH_INDEX_V1 --> JSON block in INDEX.md")

    json_str = match.group(1)
    try:
        index_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise PackageValidationError(f"Invalid JSON in INDEX.md: {e}")

    try:
        validator.validate(index_data, "Index")
    except ValueError as e:
        raise PackageValidationError(f"Schema validation failed for INDEX.md: {e}")

    if index_data.get("spec_version") != "1.0.0":
        raise PackageValidationError(f"INDEX.md spec_version must be 1.0.0, got {index_data.get('spec_version')}")

    return index_data
