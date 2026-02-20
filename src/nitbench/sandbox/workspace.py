import hashlib
import json
import shutil
import tarfile
from pathlib import Path
from typing import Any, Dict, Tuple

class SandboxError(ValueError):
    """Exception raised for sandbox orchestration errors."""

def materialize_repo(case_dir: Path, case_data: Dict[str, Any], workspace_dir: Path) -> Tuple[Path, str]:
    """
    Materialize the initial repo state into an isolated workspace.
    Returns the path to the workspace repo root and the repo_initial_sha256.
    """
    repo_cfg = case_data.get("repo", {})
    repr_type = repo_cfg.get("representation")
    src_path = case_dir / repo_cfg.get("path", "repo")
    
    if not src_path.exists():
        raise SandboxError(f"Repo source path does not exist: {src_path}")
        
    workspace_dir.mkdir(parents=True, exist_ok=True)
    target_repo_dir = workspace_dir / "repo"
    
    if target_repo_dir.exists():
        shutil.rmtree(target_repo_dir)

    if repr_type == "git_worktree":
        # For simplicity in this mock/MVP, we just copy the directory contents
        shutil.copytree(src_path, target_repo_dir, symlinks=True)
    elif repr_type == "patchset":
        # MVP: just copy if it's a directory
        shutil.copytree(src_path, target_repo_dir, symlinks=True)
    else:
        raise SandboxError(f"Unsupported repo representation: {repr_type}")
        
    # Calculate deterministic hash of initial repo state
    # We'll create a reproducible tarball in memory to hash it
    hasher = hashlib.sha256()
    
    # Sort files to ensure deterministic hashing
    paths = sorted([p for p in target_repo_dir.rglob("*") if p.is_file()])
    for p in paths:
        rel_path = p.relative_to(target_repo_dir).as_posix()
        hasher.update(rel_path.encode("utf-8"))
        hasher.update(p.read_bytes())
        
    repo_initial_sha256 = hasher.hexdigest()
    return target_repo_dir, repo_initial_sha256
