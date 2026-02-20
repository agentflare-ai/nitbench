import pytest
from pathlib import Path

from nitbench.sandbox.workspace import materialize_repo, SandboxError

def test_materialize_repo(tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    
    src_repo = case_dir / "repo"
    src_repo.mkdir()
    (src_repo / "main.py").write_text("print('hello')", encoding="utf-8")
    
    workspace_dir = tmp_path / "workspace"
    
    case_data = {
        "repo": {
            "representation": "git_worktree",
            "path": "repo"
        }
    }
    
    target, hashed = materialize_repo(case_dir, case_data, workspace_dir)
    assert target == workspace_dir / "repo"
    assert (target / "main.py").exists()
    assert len(hashed) == 64
