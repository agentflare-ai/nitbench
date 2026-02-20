import glob
from pathlib import Path
from typing import Callable, Any, Dict, List

from nitbench.validation.case import CaseValidationError

# Harness-private, versioned list of repo-config candidate globs per tool family
# This MUST NOT be visible in the Agent Sandbox
CONFIG_CANDIDATE_GLOBS = {
    "pylint": [".pylintrc", "pylintrc", "pyproject.toml", "setup.cfg"],
    "flake8": [".flake8", "setup.cfg", "tox.ini"],
    "black": ["pyproject.toml"],
    "ruff": ["pyproject.toml", "ruff.toml", ".ruff.toml"],
    "prettier": [".prettierrc*", "prettier.config.*"],
    "eslint": [".eslintrc*", "eslint.config.*"]
}

def remove_config_candidates(directory: Path, tool_id: str) -> List[Path]:
    """
    Finds and neutralizes config candidates in a directory for a given tool.
    Returns the list of paths removed.
    """
    removed_paths = []
    globs = CONFIG_CANDIDATE_GLOBS.get(tool_id.lower(), [])
    for g in globs:
        for match in directory.rglob(g):
            if match.is_file():
                match.unlink()
                removed_paths.append(match)
    return removed_paths

def validate_oracle_differential(
    oracle_def: Dict[str, Any],
    snapshot_copy_a: Path,
    snapshot_copy_b: Path,
    runner: Callable[[Dict[str, Any], Path], Dict[str, Any]]
) -> None:
    """
    Runs an oracle on copy A (normal) and copy B (with configs removed).
    If the results differ, raises a CaseValidationError indicating repo config influences oracle.
    `runner` should be a function (oracle_def, snapshot_path) -> OracleResult dict
    """
    tool_id = oracle_def.get("tool_id", "")
    
    # 1. Neutralize configs in copy B
    removed = remove_config_candidates(snapshot_copy_b, tool_id)
    
    # Run on both
    result_a = runner(oracle_def, snapshot_copy_a)
    result_b = runner(oracle_def, snapshot_copy_b)
    
    # Compare status and counts
    keys_to_compare = ["status", "error_count", "warning_count", "info_count"]
    for key in keys_to_compare:
        if result_a.get(key) != result_b.get(key):
            raise CaseValidationError(
                f"case_invalid:repo_config_influences_oracle. "
                f"Oracle {oracle_def.get('id')} produced different {key} "
                f"({result_a.get(key)} vs {result_b.get(key)}) "
                f"when configs were removed: {removed}"
            )
