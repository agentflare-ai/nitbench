import pytest
from pathlib import Path

from nitbench.sandbox.environment import AutSandbox, SandboxError

@pytest.fixture
def sandbox_env(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    repo = ws / "repo"
    repo.mkdir()
    
    case_data = {
        "aut_sandbox": {
            "network": "forbidden",
            "prohibited_executable_sets": [
                "nitbench.prohibited.lint_format.standard"
            ],
            "prohibited_attempt_policy": {
                "lint_format": "invalid"
            }
        }
    }
    return AutSandbox(ws, case_data)

def test_run_pty_allowed(sandbox_env):
    code, stdout, stderr = sandbox_env.run_pty(["echo", "hello"])
    assert code == 0
    assert stdout.strip() == b"hello"

def test_run_pty_prohibited(sandbox_env):
    # This simulates attempting to run a prohibited linting tool
    with pytest.raises(SandboxError, match="prohibited_tool_attempt:lint_format"):
        sandbox_env.run_pty(["pylint", "repo"])

def test_harness_exposure_check(sandbox_env, tmp_path):
    # Harness file lives OUTSIDE the workspace
    harness_file = tmp_path / "case.json"
    harness_file.write_text("{}")
    
    original_run_pty = sandbox_env.run_pty
    def mock_run_pty(command, cwd=None):
        if command[:2] == ["test", "-e"]:
            target = Path(command[2]).resolve()
            if not str(target).startswith(str(sandbox_env.workspace_dir.resolve())):
                return 1, b"", b""
        return original_run_pty(command, cwd)
        
    sandbox_env.run_pty = mock_run_pty
    
    # Should be False (isolated)
    assert sandbox_env.check_harness_exposure(harness_file) is False
    
    # If the harness accidentally writes a secret INTO the workspace
    leaked_file = sandbox_env.workspace_dir / "scoring.yaml"
    leaked_file.write_text("{}")
    assert sandbox_env.check_harness_exposure(leaked_file) is True
